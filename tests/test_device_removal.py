"""Tests for the cleanup of an entry whose source MQTT device was deleted."""

from __future__ import annotations

from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.mqtt_connection_state.const import DEVICE_REMOVED_GRACE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

DEVICE_SENSOR = "binary_sensor.test_device_connection_state"


async def _wait_out_grace(hass: HomeAssistant) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + DEVICE_REMOVED_GRACE + timedelta(seconds=1)
    )
    await hass.async_block_till_done()


async def test_entry_is_removed_after_its_device_is_deleted(
    hass: HomeAssistant, init_device: MockConfigEntry, source_device: dr.DeviceEntry
) -> None:
    """Deleting the source device removes the entry, but only after the grace."""
    dr.async_get(hass).async_remove_device(source_device.id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_get_entry(init_device.entry_id) is not None
    assert hass.states.get(DEVICE_SENSOR) is not None

    await _wait_out_grace(hass)

    assert hass.config_entries.async_get_entry(init_device.entry_id) is None
    assert hass.states.get(DEVICE_SENSOR) is None


async def test_entry_is_kept_when_the_device_comes_back(
    hass: HomeAssistant, init_device: MockConfigEntry, source_device: dr.DeviceEntry
) -> None:
    """A device that is re-added within the grace keeps its entry."""
    registry = dr.async_get(hass)
    registry.async_remove_device(source_device.id)
    await hass.async_block_till_done()

    mqtt_entry = hass.config_entries.async_entries("mqtt")[0]
    restored = registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "test_device")},
        name="Test Device",
    )
    assert restored.id == source_device.id

    await _wait_out_grace(hass)

    assert init_device.state is ConfigEntryState.LOADED
    assert hass.states.get(DEVICE_SENSOR) is not None


async def test_entry_whose_device_is_already_gone_is_removed(
    hass: HomeAssistant,
    device_config_entry: MockConfigEntry,
    source_device: dr.DeviceEntry,
) -> None:
    """An entry left behind without a device goes away after the grace."""
    dr.async_get(hass).async_remove_device(source_device.id)
    device_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(device_config_entry.entry_id)
    await hass.async_block_till_done()

    assert device_config_entry.state is ConfigEntryState.LOADED

    await _wait_out_grace(hass)

    assert hass.config_entries.async_get_entry(device_config_entry.entry_id) is None


async def test_entry_without_device_is_kept_when_the_device_appears(
    hass: HomeAssistant,
    device_config_entry: MockConfigEntry,
    source_device: dr.DeviceEntry,
) -> None:
    """Discovery re-creating the device after start keeps the entry."""
    registry = dr.async_get(hass)
    registry.async_remove_device(source_device.id)
    device_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(device_config_entry.entry_id)
    await hass.async_block_till_done()

    mqtt_entry = hass.config_entries.async_entries("mqtt")[0]
    restored = registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "test_device")},
        name="Test Device",
    )
    assert restored.id == source_device.id

    await _wait_out_grace(hass)

    assert device_config_entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(device_config_entry.entry_id)


async def test_entry_is_kept_when_another_device_is_deleted(
    hass: HomeAssistant, init_device: MockConfigEntry
) -> None:
    """Removing an unrelated device leaves the entry alone."""
    registry = dr.async_get(hass)
    mqtt_entry = hass.config_entries.async_entries("mqtt")[0]
    other = registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "other_device")},
        name="Other Device",
    )
    registry.async_remove_device(other.id)

    await _wait_out_grace(hass)

    assert init_device.state is ConfigEntryState.LOADED
