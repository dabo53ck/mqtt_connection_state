"""Tests for the connection-state, broker and bridge binary sensors."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_fire_mqtt_message,
)

from custom_components.mqtt_connection_state.const import EVENT_CHANGED
from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

DEVICE_SENSOR = "binary_sensor.test_device_connection_state"
BROKER_SENSOR = "binary_sensor.mqtt_broker_connection_state"
Z2M_BRIDGE_SENSOR = "binary_sensor.zigbee2mqtt_bridge_connection_state"
TOPIC = "zigbee2mqtt/test_device/availability"


# --------------------------------------------------------------------------- #
# Per-device sensor: the startup restore is not a change                       #
# --------------------------------------------------------------------------- #


async def test_initial_state_restore_fires_no_event(
    hass: HomeAssistant, init_device
) -> None:
    """The first known state (replayed on every restart) must not fire an event."""
    events = async_capture_events(hass, EVENT_CHANGED)

    async_fire_mqtt_message(hass, TOPIC, "online")
    await hass.async_block_till_done()

    assert hass.states.get(DEVICE_SENSOR).state == "on"
    assert events == []


async def test_real_transition_fires_event(
    hass: HomeAssistant, init_device
) -> None:
    """A genuine online<->offline change still fires mqtt_connection_state_changed."""
    async_fire_mqtt_message(hass, TOPIC, "online")  # restore, no event
    await hass.async_block_till_done()

    events = async_capture_events(hass, EVENT_CHANGED)

    async_fire_mqtt_message(hass, TOPIC, "offline")
    await hass.async_block_till_done()
    assert hass.states.get(DEVICE_SENSOR).state == "off"
    assert len(events) == 1
    assert events[0].data["state"] == "offline"
    assert events[0].data["entity_id"] == DEVICE_SENSOR
    assert events[0].data["device_id"] == init_device.data["device_id"]

    async_fire_mqtt_message(hass, TOPIC, "online")
    await hass.async_block_till_done()
    assert hass.states.get(DEVICE_SENSOR).state == "on"
    assert len(events) == 2
    assert events[1].data["state"] == "online"


async def test_empty_payload_marks_unavailable(
    hass: HomeAssistant, init_device
) -> None:
    """A cleared retained message takes the sensor to 'unavailable'."""
    async_fire_mqtt_message(hass, TOPIC, "online")
    await hass.async_block_till_done()
    assert hass.states.get(DEVICE_SENSOR).state == "on"

    async_fire_mqtt_message(hass, TOPIC, "")
    await hass.async_block_till_done()
    assert hass.states.get(DEVICE_SENSOR).state == STATE_UNAVAILABLE


# --------------------------------------------------------------------------- #
# Broker sensor                                                                #
# --------------------------------------------------------------------------- #


async def test_broker_sensor_is_created(hass: HomeAssistant, init_device) -> None:
    """The singleton broker sensor appears automatically."""
    assert hass.states.get(BROKER_SENSOR) is not None


async def test_broker_sensor_follows_connection_status(
    hass: HomeAssistant, init_device
) -> None:
    """It tracks the MQTT client connection and never goes 'unavailable'."""
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    await hass.async_block_till_done()
    state = hass.states.get(BROKER_SENSOR)
    assert state.state == "off"
    assert state.state != STATE_UNAVAILABLE

    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done()
    assert hass.states.get(BROKER_SENSOR).state == "on"


# --------------------------------------------------------------------------- #
# Bridge sensors                                                               #
# --------------------------------------------------------------------------- #


async def test_bridge_sensor_from_configured_topic(
    hass: HomeAssistant, init_device
) -> None:
    """A bridge sensor is derived from the root of each configured device topic."""
    assert hass.states.get(Z2M_BRIDGE_SENSOR) is not None

    async_fire_mqtt_message(hass, "zigbee2mqtt/bridge/state", '{"state": "online"}')
    await hass.async_block_till_done()
    assert hass.states.get(Z2M_BRIDGE_SENSOR).state == "on"

    async_fire_mqtt_message(hass, "zigbee2mqtt/bridge/state", '{"state": "offline"}')
    await hass.async_block_till_done()
    assert hass.states.get(Z2M_BRIDGE_SENSOR).state == "off"


async def test_bridge_sensor_unavailable_while_broker_down(
    hass: HomeAssistant, init_device
) -> None:
    """While the broker is unreachable the bridge state is unknowable."""
    async_fire_mqtt_message(hass, "zigbee2mqtt/bridge/state", '{"state": "online"}')
    await hass.async_block_till_done()
    assert hass.states.get(Z2M_BRIDGE_SENSOR).state == "on"

    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    await hass.async_block_till_done()
    assert hass.states.get(Z2M_BRIDGE_SENSOR).state == STATE_UNAVAILABLE

    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done()
    assert hass.states.get(Z2M_BRIDGE_SENSOR).state != STATE_UNAVAILABLE


async def test_new_bridge_discovered_dynamically(
    hass: HomeAssistant, init_device
) -> None:
    """An MQTT root not seen at setup gets its own bridge sensor at runtime."""
    ent = "binary_sensor.othermqtt_bridge_connection_state"
    assert hass.states.get(ent) is None

    async_fire_mqtt_message(hass, "othermqtt/bridge/state", '{"state": "online"}')
    await hass.async_block_till_done()
    assert hass.states.get(ent) is not None

    async_fire_mqtt_message(hass, "othermqtt/bridge/state", '{"state": "online"}')
    await hass.async_block_till_done()
    assert hass.states.get(ent).state == "on"
