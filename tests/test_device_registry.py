"""Tests for the device-registry lookups in helpers.py and discovery.py."""

from __future__ import annotations

from unittest.mock import patch

import attr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mqtt_connection_state.const import CONF_DEVICE_ID, DOMAIN
from custom_components.mqtt_connection_state.discovery import async_discover_devices
from custom_components.mqtt_connection_state.helpers import (
    find_duplicate_entries,
    resolve_source_device_id,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

TOPIC = "zigbee2mqtt/test_device/availability"
MQTT_IDENTIFIER = ("mqtt", "test_device")
PRE_MIGRATION_ID = "pre-2026-8-merged-device-id"


@pytest.fixture
def registry(hass: HomeAssistant) -> dr.DeviceRegistry:
    """The device registry."""
    return dr.async_get(hass)


@pytest.fixture
def own_entry(hass: HomeAssistant) -> MockConfigEntry:
    """A config entry of this integration, which can own (fork) devices."""
    entry = MockConfigEntry(domain=DOMAIN, title="Own")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def forked_device(
    registry: dr.DeviceRegistry,
    own_entry: MockConfigEntry,
    source_device: dr.DeviceEntry,
) -> dr.DeviceEntry:
    """A device owned by this integration that shares the mqtt device's identity."""
    device = registry.async_get_or_create(
        config_entry_id=own_entry.entry_id,
        identifiers={MQTT_IDENTIFIER},
        name="Forked Test Device",
    )
    assert device.id != source_device.id
    return device


def _split_from_composite(
    registry: dr.DeviceRegistry, *devices: dr.DeviceEntry
) -> None:
    """Make the devices the splits of one pre-2026.8 merged device.

    Home Assistant does this in its device-registry migration; there is no public
    API to reproduce it.
    """
    for device in devices:
        registry._devices[device.id] = attr.evolve(
            device,
            composite_device_id=PRE_MIGRATION_ID,
            composite_primary_config_entry=devices[0].config_entry_id,
        )


# --------------------------------------------------------------------------- #
# resolve_source_device_id                                                     #
# --------------------------------------------------------------------------- #


async def test_resolve_keeps_a_concrete_mqtt_device(
    hass: HomeAssistant, source_device: dr.DeviceEntry
) -> None:
    """A stored id that already is the mqtt device resolves to itself."""
    assert resolve_source_device_id(hass, source_device.id) == source_device.id


async def test_resolve_forked_device_to_the_mqtt_device(
    hass: HomeAssistant,
    source_device: dr.DeviceEntry,
    forked_device: dr.DeviceEntry,
) -> None:
    """A device forked off by this integration resolves via its hardware identity."""
    assert resolve_source_device_id(hass, forked_device.id) == source_device.id


async def test_resolve_pre_migration_composite_id(
    hass: HomeAssistant,
    registry: dr.DeviceRegistry,
    source_device: dr.DeviceEntry,
    forked_device: dr.DeviceEntry,
) -> None:
    """A pre-2026.8 merged-device id resolves to the split owned by mqtt."""
    _split_from_composite(registry, forked_device, source_device)

    assert resolve_source_device_id(hass, PRE_MIGRATION_ID) == source_device.id


async def test_resolve_own_split_of_a_composite(
    hass: HomeAssistant,
    registry: dr.DeviceRegistry,
    source_device: dr.DeviceEntry,
    forked_device: dr.DeviceEntry,
) -> None:
    """This integration's own split resolves to the mqtt split of the same device."""
    _split_from_composite(registry, source_device, forked_device)

    assert resolve_source_device_id(hass, forked_device.id) == source_device.id


@pytest.mark.parametrize("device_id", [None, "", "no-such-device"])
async def test_resolve_unknown_device_id(
    hass: HomeAssistant, source_device: dr.DeviceEntry, device_id: str | None
) -> None:
    """Nothing to resolve to -> None."""
    assert resolve_source_device_id(hass, device_id) is None


async def test_entries_for_the_same_device_are_duplicates(
    hass: HomeAssistant,
    registry: dr.DeviceRegistry,
    source_device: dr.DeviceEntry,
    forked_device: dr.DeviceEntry,
) -> None:
    """An entry storing a pre-migration id duplicates one storing the split id."""
    _split_from_composite(registry, forked_device, source_device)
    first = MockConfigEntry(
        domain=DOMAIN, data={CONF_DEVICE_ID: source_device.id}, unique_id="a"
    )
    second = MockConfigEntry(
        domain=DOMAIN, data={CONF_DEVICE_ID: PRE_MIGRATION_ID}, unique_id="b"
    )
    first.add_to_hass(hass)
    second.add_to_hass(hass)

    keep, remove = find_duplicate_entries(hass)

    assert keep == [first]
    assert remove == [second]


# --------------------------------------------------------------------------- #
# async_discover_devices                                                       #
# --------------------------------------------------------------------------- #


async def test_discovery_lists_only_new_mqtt_devices(
    hass: HomeAssistant,
    registry: dr.DeviceRegistry,
    source_device: dr.DeviceEntry,
    forked_device: dr.DeviceEntry,
) -> None:
    """Configured, disabled, own and non-mqtt devices are not offered."""
    mqtt_entry = hass.config_entries.async_entries("mqtt")[0]
    other_entry = MockConfigEntry(domain="other")
    other_entry.add_to_hass(hass)

    configured = registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "configured")},
        name="Configured",
    )
    disabled = registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "disabled")},
        name="Disabled",
        disabled_by=dr.DeviceEntryDisabler.USER,
    )
    registry.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={("other", "not_mqtt")},
        name="Not MQTT",
    )
    MockConfigEntry(
        domain=DOMAIN, data={CONF_DEVICE_ID: configured.id}, unique_id="configured"
    ).add_to_hass(hass)
    hass.data[DOMAIN] = {"seen_device_ids": set(), "new_devices": []}

    with patch(
        "custom_components.mqtt_connection_state.discovery.find_connection_topic",
        return_value=TOPIC,
    ):
        discovered = await async_discover_devices(hass)

    assert [device.id for device in discovered] == [source_device.id]
    assert forked_device.id not in hass.data[DOMAIN]["seen_device_ids"]
    assert disabled.id not in hass.data[DOMAIN]["seen_device_ids"]
    assert hass.data[DOMAIN]["new_devices"] == [
        {"id": source_device.id, "name": "Test Device"}
    ]

    # Already offered once: not offered again.
    with patch(
        "custom_components.mqtt_connection_state.discovery.find_connection_topic",
        return_value=TOPIC,
    ):
        assert await async_discover_devices(hass) == []


async def test_discovery_skips_devices_without_a_connection_topic(
    hass: HomeAssistant, source_device: dr.DeviceEntry
) -> None:
    """An mqtt device that has no availability topic cannot be monitored."""
    hass.data[DOMAIN] = {"seen_device_ids": set(), "new_devices": []}

    with patch(
        "custom_components.mqtt_connection_state.discovery.find_connection_topic",
        return_value=None,
    ):
        assert await async_discover_devices(hass) == []
