"""Tests for integration setup."""

from __future__ import annotations

from custom_components.mqtt_connection_state.const import CONF_KIND, DOMAIN, KIND_SYSTEM
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component


def _system_entries(hass: HomeAssistant) -> list:
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_KIND) == KIND_SYSTEM
    ]


async def test_setup_creates_exactly_one_system_entry(
    hass: HomeAssistant, mqtt_mock
) -> None:
    """async_setup auto-creates the single 'system' entry, and only one."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert len(_system_entries(hass)) == 1

    # A second setup pass (e.g. reload) must not add another.
    await hass.config_entries.async_reload(_system_entries(hass)[0].entry_id)
    await hass.async_block_till_done()
    assert len(_system_entries(hass)) == 1
