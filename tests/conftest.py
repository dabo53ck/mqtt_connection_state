"""Fixtures for the MQTT connection state tests."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mqtt_connection_state.const import (
    CONF_DEVICE_ID,
    CONF_TOPIC,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

# A Zigbee2MQTT-shaped availability topic; its root ("zigbee2mqtt") is what the
# bridge sensor is derived from.
SOURCE_TOPIC = "zigbee2mqtt/test_device/availability"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom component in every test."""
    yield


@pytest.fixture(autouse=True)
def expected_lingering_timers() -> bool:
    """Allow HA's own MQTT client 'misc' periodic timer to outlive the test.

    It is started by the mqtt integration (via the mqtt_mock fixture), not by
    this component, and mqtt_mock does not cancel it on teardown.
    """
    return True


@pytest.fixture
def source_device(hass: HomeAssistant, mqtt_mock) -> dr.DeviceEntry:
    """An mqtt-owned device that a connection sensor attaches to."""
    device_registry = dr.async_get(hass)
    mqtt_entry = hass.config_entries.async_entries("mqtt")[0]
    return device_registry.async_get_or_create(
        config_entry_id=mqtt_entry.entry_id,
        identifiers={("mqtt", "test_device")},
        name="Test Device",
    )


@pytest.fixture
def device_config_entry(source_device: dr.DeviceEntry) -> MockConfigEntry:
    """A per-device config entry pointing at SOURCE_TOPIC."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Test Device",
        data={CONF_DEVICE_ID: source_device.id, CONF_TOPIC: SOURCE_TOPIC},
        unique_id=source_device.id,
    )


@pytest.fixture
async def init_device(hass: HomeAssistant, device_config_entry: MockConfigEntry):
    """Set up one per-device connection sensor (plus the auto system entry)."""
    device_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(device_config_entry.entry_id)
    await hass.async_block_till_done()
    yield device_config_entry
    if device_config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(device_config_entry.entry_id)
        await hass.async_block_till_done()
