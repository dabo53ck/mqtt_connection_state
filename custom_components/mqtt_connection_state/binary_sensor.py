"""Binary sensor platform for MQTT connection state custom integration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.mqtt import (
    async_subscribe,
    async_subscribe_connection_status,
    is_connected,
    models,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_device_registry_updated_event

from .const import (
    BRIDGE_TRANSLATION_KEY,
    BROKER_TRANSLATION_KEY,
    CONF_DEVICE_ID,
    CONF_KIND,
    CONF_TOPIC,
    DOMAIN,
    EVENT_CHANGED,
    KIND_SYSTEM,
    SIGNAL_NEW_BRIDGE,
)
from .helpers import (
    find_connection_topic,
    process_message_payload,
    resolve_source_device_id,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize from the config entry."""
    if entry.data.get(CONF_KIND) == KIND_SYSTEM:
        _async_setup_system_entities(hass, entry, async_add_entities)
        return

    async_add_entities([MqttConnectionSensorEntity(hass, entry)])


@callback
def _configured_bridge_roots(hass: HomeAssistant) -> set[str]:
    """Return the distinct MQTT root prefixes of every configured device topic."""
    roots: set[str] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_KIND) == KIND_SYSTEM:
            continue
        topic = entry.data.get(CONF_TOPIC)
        if isinstance(topic, str) and "/" in topic:
            roots.add(topic.split("/", 1)[0])
    return roots


@callback
def _async_setup_system_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the broker sensor plus one sensor per known MQTT bridge."""
    known: set[str] = _configured_bridge_roots(hass)

    entities: list[BinarySensorEntity] = [MqttBrokerConnectionSensorEntity(entry)]
    entities.extend(
        MqttBridgeConnectionSensorEntity(hass, entry, root) for root in sorted(known)
    )
    async_add_entities(entities)

    @callback
    def _async_add_bridge(root: str) -> None:
        if root in known:
            return
        known.add(root)
        _LOGGER.debug("New MQTT bridge seen: %s", root)
        async_add_entities([MqttBridgeConnectionSensorEntity(hass, entry, root)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_BRIDGE, _async_add_bridge)
    )


@callback
def _fire_changed_event(
    hass: HomeAssistant,
    *,
    topic: str | None,
    is_on: bool,
    device_name: str,
    entity_id: str,
) -> None:
    """Fire the shared connection-state event (broker/bridge carry no device_id)."""
    if not hass.is_running:
        return
    hass.bus.async_fire(
        EVENT_CHANGED,
        {
            "topic": topic,
            "state": "online" if is_on else "offline",
            "device_id": None,
            "device_name": device_name,
            "entity_id": entity_id,
        },
    )


class MqttConnectionSensorEntity(BinarySensorEntity):
    """Binary Sensor Entity."""

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "connection_state"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize Sensor."""
        _LOGGER.debug("Setup Binary Sensor: %s", entry.title)

        self.hass = hass
        self.entry = entry
        self.entity_id = async_generate_entity_id(
            BINARY_SENSOR_DOMAIN + ".{}_connection_state", entry.title, hass=hass
        )

        # The stored id can be a pre-2026.8 merged-device id; resolve it to the
        # current concrete MQTT device.
        stored_device_id = entry.data[CONF_DEVICE_ID]
        device_id = resolve_source_device_id(hass, stored_device_id) or stored_device_id
        self._device_id = device_id

        device_registry = dr.async_get(hass)

        # Home Assistant 2026.8+: a device belongs to a single config entry. Link
        # this helper entity directly to the source integration's device instead
        # of declaring a DeviceInfo that carries that device's identifiers, which
        # would fork a duplicate, config-entry-owned device.
        self.device_entry = device_registry.async_get(device_id)

        self._attr_unique_id = f"{entry.entry_id}_connection_state"
        self._attr_is_on = None
        self._attr_available = True
        self._connection_topic: str | None = entry.data.get(CONF_TOPIC)

        self._unsubscribe = None
        self._unsub_device = None
        self._unsub_bridge = None
        self._message_received = None
        self._last_mqtt_message: datetime | None = None

    @property
    def _device_name(self) -> str:
        """Best-effort device name for logs and events."""
        if self.device_entry and self.device_entry.name:
            return self.device_entry.name
        return self.entry.title

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        device_registry = dr.async_get(self.hass)

        async def _async_delayed_resolve() -> None:
            await asyncio.sleep(1)

            new_topic = find_connection_topic(self.hass, self._device_id, log=False)

            if new_topic and new_topic != self._connection_topic:
                _LOGGER.info(
                    "Connection topic updated via registry: %s -> %s",
                    self._connection_topic,
                    new_topic,
                )

                if self._unsubscribe:
                    self._unsubscribe()
                    self._unsubscribe = None

                self._connection_topic = new_topic
                self.hass.config_entries.async_update_entry(
                    self.entry,
                    data={**self.entry.data, CONF_TOPIC: new_topic},
                )

                self._unsubscribe = await async_subscribe(
                    self.hass,
                    new_topic,
                    self._message_received,
                )

        @callback
        def _on_device_registry_updated(event: Event) -> None:
            if event.data.get("action") == "remove":
                return

            if event.data.get("device_id") != self._device_id:
                return

            new_device_entry = device_registry.async_get(self._device_id)
            if (
                new_device_entry.primary_config_entry if new_device_entry else None
            ) is None:
                return

            _LOGGER.debug(
                "Registry updated, check topic of %s",
                self._device_name,
            )
            self.hass.async_create_task(_async_delayed_resolve())

        async def _on_bridge_state(message: models.ReceiveMessage) -> None:
            try:
                payload = json.loads(message.payload)
            except ValueError:
                return

            if payload["state"] == "online":
                # if a message has been received in the last minute before bride online state don't recheck.
                now = datetime.now(UTC)
                if (
                    self._last_mqtt_message
                    and now - self._last_mqtt_message < timedelta(minutes=1)
                ):
                    return
                # if a massage has been receive in the first minute after bride online state don't recheck.
                await asyncio.sleep(59)
                now2 = datetime.now(UTC)
                if (
                    self._last_mqtt_message
                    and now2 - self._last_mqtt_message < timedelta(minutes=1)
                ):
                    return

                _LOGGER.debug(
                    "Bridge online on %s, check topic of %s",
                    message.topic,
                    self._device_name,
                )
                self.hass.async_create_task(_async_delayed_resolve())

        @callback
        def message_received(message: models.ReceiveMessage) -> None:
            """Receive a MQTT message."""
            self._last_mqtt_message = datetime.now(UTC)

            _LOGGER.debug(
                "Message received on %s: %s",
                message.topic,
                message.payload,
            )

            if not message.payload:
                self._handle_message_updates(None, None)
                return

            self.hass.async_create_task(message_received_process(message))

        async def message_received_process(message: models.ReceiveMessage) -> None:
            state_message = await self.hass.async_add_executor_job(
                process_message_payload,
                self.hass,
                message.topic,
                message.payload,
            )

            self._handle_message_updates(message.topic, state_message)

        self._message_received = message_received

        _LOGGER.debug(
            "Subscribed to topic %s",
            self._connection_topic,
        )

        self._unsubscribe = await async_subscribe(
            self.hass,
            self._connection_topic,
            message_received,
        )
        self._unsub_device = async_track_device_registry_updated_event(
            self.hass,
            [self._device_id],
            _on_device_registry_updated,
        )

        base = self._connection_topic.split("/", 1)[0]
        self._unsub_bridge = await async_subscribe(
            self.hass,
            f"{base}/bridge/state",
            _on_bridge_state,
        )

    async def async_will_remove_from_hass(self) -> None:
        """When removing unsubscribe all."""

        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

        if self._unsub_device:
            self._unsub_device()
            self._unsub_device = None

        if self._unsub_bridge:
            self._unsub_bridge()
            self._unsub_bridge = None

    def _handle_message_updates(self, state_topic, state_message: str | None) -> None:
        old_state = self._attr_is_on
        old_available = self._attr_available

        if state_message is None:
            self._attr_available = False
            if old_available:
                self.async_write_ha_state()
            return

        self._attr_is_on = state_message == "online"

        self._attr_available = True

        if old_state != self._attr_is_on or old_available != self._attr_available:
            self.async_write_ha_state()

            # A None -> on/off update is the initial state being restored, not a
            # change: every HA restart replays the retained availability message,
            # so firing an event per device on every restart would be noise. The
            # entity state already carries the value; only genuine on<->off
            # transitions are events.
            if old_state is None:
                return

            self.hass.bus.async_fire(
                EVENT_CHANGED,
                {
                    "topic": state_topic,
                    "state": "online" if self._attr_is_on else "offline",
                    "device_id": self._device_id,
                    "device_name": self._device_name,
                    "entity_id": self.entity_id,
                },
            )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return {
            "topic": self._connection_topic,
        }


class MqttBrokerConnectionSensorEntity(BinarySensorEntity):
    """Connectivity between Home Assistant and the MQTT broker.

    Fed by Home Assistant's own MQTT client status, not by a topic, so it stays
    accurate even when the broker is unreachable (no messages arrive then).
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = BROKER_TRANSLATION_KEY
    _attr_available = True  # never tie availability to the broker being up

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the broker connection sensor."""
        self.entry = entry
        self._attr_unique_id = f"{DOMAIN}_broker"
        self.entity_id = f"{BINARY_SENSOR_DOMAIN}.mqtt_broker_connection_state"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "broker")},
            entry_type=DeviceEntryType.SERVICE,
            name="MQTT Broker",
        )
        self._attr_is_on = None

    async def async_added_to_hass(self) -> None:
        """Seed the state and subscribe to MQTT client connection changes."""
        try:
            self._attr_is_on = is_connected(self.hass)
        except KeyError:
            self._attr_is_on = None

        @callback
        def _connection_changed(connected: bool) -> None:
            if connected == self._attr_is_on:
                return
            self._attr_is_on = connected
            self.async_write_ha_state()
            _fire_changed_event(
                self.hass,
                topic=None,
                is_on=connected,
                device_name="MQTT Broker",
                entity_id=self.entity_id,
            )

        self.async_on_remove(
            async_subscribe_connection_status(self.hass, _connection_changed)
        )


class MqttBridgeConnectionSensorEntity(BinarySensorEntity):
    """Online state of one MQTT bridge, e.g. a Zigbee2MQTT instance.

    Reads ``<root>/bridge/state``. While the broker is unreachable the state is
    unknowable, so the sensor reports ``unavailable`` until it reconnects.
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = BRIDGE_TRANSLATION_KEY

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, root: str) -> None:
        """Initialize a bridge connection sensor for one MQTT root prefix."""
        self.entry = entry
        self._root = root
        self._state_topic = f"{root}/bridge/state"
        self._attr_unique_id = f"{DOMAIN}_bridge_{root}"
        self.entity_id = async_generate_entity_id(
            BINARY_SENSOR_DOMAIN + ".{}_bridge_connection_state", root, hass=hass
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"bridge_{root}")},
            entry_type=DeviceEntryType.SERVICE,
            name=root,
        )
        self._attr_is_on = None
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Subscribe to the bridge state topic and broker connection changes."""
        try:
            self._attr_available = is_connected(self.hass)
        except KeyError:
            pass

        @callback
        def _message(message: models.ReceiveMessage) -> None:
            self.hass.async_create_task(self._async_handle_message(message))

        self.async_on_remove(
            await async_subscribe(self.hass, self._state_topic, _message)
        )

        @callback
        def _connection_changed(connected: bool) -> None:
            if bool(connected) == self._attr_available:
                return
            self._attr_available = bool(connected)
            self.async_write_ha_state()

        self.async_on_remove(
            async_subscribe_connection_status(self.hass, _connection_changed)
        )

    async def _async_handle_message(self, message: models.ReceiveMessage) -> None:
        result = await self.hass.async_add_executor_job(
            process_message_payload,
            self.hass,
            message.topic,
            message.payload,
        )
        is_on = result == "online"
        if is_on == self._attr_is_on and self._attr_available:
            return
        self._attr_is_on = is_on
        self._attr_available = True
        self.async_write_ha_state()
        _fire_changed_event(
            self.hass,
            topic=message.topic,
            is_on=is_on,
            device_name=f"{self._root} bridge",
            entity_id=self.entity_id,
        )
