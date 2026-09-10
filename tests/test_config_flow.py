"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mqtt_connection_state.const import (
    CONF_DEVICE_ID,
    CONF_KIND,
    CONF_TOPIC,
    DOMAIN,
    KIND_SYSTEM,
)
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

_FIND_TOPIC = "custom_components.mqtt_connection_state.config_flow.find_connection_topic"
_SETUP_ENTRY = "custom_components.mqtt_connection_state.async_setup_entry"


async def test_system_discovery_creates_singleton_entry(hass: HomeAssistant) -> None:
    """The self-discovery flow creates the one 'system' entry."""
    with patch(_SETUP_ENTRY, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_INTEGRATION_DISCOVERY},
            data={CONF_KIND: KIND_SYSTEM},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].data == {CONF_KIND: KIND_SYSTEM}
    assert result["result"].unique_id == f"{DOMAIN}_{KIND_SYSTEM}"


async def test_system_discovery_aborts_when_already_configured(
    hass: HomeAssistant,
) -> None:
    """A second self-discovery is aborted, so there is never more than one."""
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_KIND: KIND_SYSTEM},
        unique_id=f"{DOMAIN}_{KIND_SYSTEM}",
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_INTEGRATION_DISCOVERY},
        data={CONF_KIND: KIND_SYSTEM},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_creates_device_entry(
    hass: HomeAssistant, mqtt_mock, source_device
) -> None:
    """The user flow stores the picked device and the resolved topic."""
    with (
        patch(_FIND_TOPIC, return_value="zigbee2mqtt/test_device/availability"),
        patch(_SETUP_ENTRY, return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_ID: source_device.id}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DEVICE_ID] == source_device.id
    assert result["data"][CONF_TOPIC] == "zigbee2mqtt/test_device/availability"


async def test_user_flow_no_connection_topic(
    hass: HomeAssistant, mqtt_mock, source_device
) -> None:
    """A device with no availability/state topic re-shows the form with an error."""
    with patch(_FIND_TOPIC, return_value=None):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DEVICE_ID: source_device.id}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_connection_topic"}
