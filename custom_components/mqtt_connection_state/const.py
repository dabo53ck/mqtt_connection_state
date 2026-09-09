"""Constants for MQTT connection state custom integration."""

from datetime import timedelta
import json
from logging import Logger, getLogger
from pathlib import Path

LOGGER: Logger = getLogger(__name__)

manifestfile = Path(__file__).parent / "manifest.json"
with Path(manifestfile).open(encoding="UTF-8") as json_file:
    manifest_data = json.load(json_file)

DOMAIN = manifest_data.get("domain")
DOMAIN_NAME = manifest_data.get("name")
VERSION = manifest_data.get("version")

DOMAIN_NAME = "MQTT connection state"

CONF_DEVICE_ID = "device_id"
CONF_DISCOVERY_INTERVAL = timedelta(minutes=10)
CONF_ERROR_BASE = "base"
CONF_TOPIC = "topic"

# Marks the single, auto-created config entry that owns the broker/bridge sensors
# (as opposed to the per-device entries, which carry CONF_DEVICE_ID/CONF_TOPIC).
CONF_KIND = "kind"
KIND_SYSTEM = "system"

# Bus event fired on every connection-state change (device, broker and bridge).
EVENT_CHANGED = f"{DOMAIN}_changed"

BROKER_TRANSLATION_KEY = "broker_connection_state"
BRIDGE_TRANSLATION_KEY = "bridge_connection_state"

# Dispatcher signal carrying an MQTT root prefix seen on "<root>/bridge/state".
# Deliberately not equal to DOMAIN (HA's own MQTT client signal is "mqtt_connection_state").
SIGNAL_NEW_BRIDGE = f"{DOMAIN}_new_bridge"

SERV_LIST_NEW_DEVICES = "list_new_devices"
SERV_ADD_NEW_DEVICES = "add_new_devices"
SERV_REMOVE_DUPLICATE_ENTRIES = "remove_duplicate_entries"

ISSUE_DUPLICATE_ENTRIES = "duplicate_entries"
