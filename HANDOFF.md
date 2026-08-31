# Handoff — fix for studioIngrid/mqtt_connection_state issue #7

**Status: FIX COMPLETE & VERIFIED on the live HA instance (build `1.0.2-test4`). Only the upstream PR remains.**

Date of this handoff: 2026-08-31. Branch: `fix/issue-7-duplicate-devices-2026.8` (committed, not pushed).
Full design notes: `C:\Users\david\.claude\plans\look-a-https-github-com-studioingrid-mqt-jaunty-octopus.md`

## The problem (issue #7 + what we found beyond it)

HA 2026.8 made each device belong to a single config entry (no more cross-integration
merging). This integration:
1. attached its `binary_sensor` to the source MQTT device via a shared-identifier
   `DeviceInfo` → post-2026.8 that forks a **duplicate empty device** per entry (issue #7);
2. `discovery.py` compares real device ids against the **pre-migration ids** stored in
   `entry.data` → after the migration renamed every device it re-discovered them all and
   created a **second config entry per device** (~65 duplicates on the reporter's box,
   created 2026-08-14…08-23);
3. entries created before 2026.8 store a now-non-concrete "composite" device id.

## The fix (build 1.0.2-test4)

- **`helpers.py`** `resolve_source_device_id(hass, device_id)` — maps a stored/composite id
  to the current concrete MQTT device via
  `device_registry.devices.get_devices_for_composite_device_id()` (identifier/connection
  match as fallback). Plus `entry_source_key`, `configured_source_device_ids`,
  `find_duplicate_entries`, `async_sync_duplicate_issue`, `async_remove_duplicate_entries`.
- **`binary_sensor.py`** — link via `self.device_entry = <concrete device>` (no `DeviceInfo`);
  resolve the stored id; `_device_name` fallback property.
- **`__init__.py` `async_setup_entry`** — heal `entry.data[CONF_DEVICE_ID]` (and `unique_id`,
  collision-guarded) to the concrete id; `async_remove_helper_devices(remove_all_devices=True)`
  removes the duplicate device and relinks the entity. Removed the old orphaned-device
  watchdog. Per-entry logs dropped to DEBUG.
- **`__init__.py` `async_setup`** — `async_at_started` → `_report_state`: one heal-summary
  line + `async_sync_duplicate_issue` (raises/clears the repair issue).
- **`discovery.py`** — match by `configured_source_device_ids` (resolved identity); skip
  devices this integration owns.
- **`repairs.py`** (re-added) — `DuplicateEntriesRepairFlow` (canonical `ConfirmRepairFlow`
  shape); Settings → Repairs one-click removal of the duplicate entries.
- **`services.py`** — `mqtt_connection_state.remove_duplicate_entries` with `dry_run`
  (default true) → shared `async_remove_duplicate_entries` helper.
- **`const.py`** `SERV_REMOVE_DUPLICATE_ENTRIES`, `ISSUE_DUPLICATE_ENTRIES`.
- **`manifest.json`** `"homeassistant": "2026.8.0"`, `"version": "1.0.2-test4"` (TEST MARKER).
- **`translations/{en,nl,sv}.json`** — removed `issues.orphaned_device`; added
  `issues.duplicate_entries`.

## Verified on the live instance (core-2026.8.3, ~77 real devices)

- v3 restart: 77 detached sensors re-attached; duplicate devices gone.
- v4 restart: 2 INFO log lines total, no "logging too frequently", no errors; repair issue
  raised (count 65).
- Repair run + restart: **77 config entries** (was 142), 77 sensors each on its real device,
  0 detached, 0 `_2`, repair issue auto-cleared, no new discovery.
- The `binary_sensor.zigbee2mqtt_bridge_*_connection_state` entities are Z2M-native
  (`platform: mqtt`), not ours.

## Open housekeeping on the user's box

- `/config/custom_components/mqtt_connection_state.bak/` — HA logs
  `Loaded mqtt_connection_state from custom_components.mqtt_connection_state.bak`. Two folders
  with the same domain. Move it out of `custom_components/` or delete it once satisfied.

## To resume — build the PR

1. `cd` to this working dir, `git checkout fix/issue-7-duplicate-devices-2026.8`.
2. `manifest.json`: set a real `version` (e.g. `1.1.0`); consider `"integration_type": "helper"`.
3. Run hassfest if available (reorders manifest keys): otherwise fine.
4. Fork `studioIngrid/mqtt_connection_state` to the user's GitHub, push the branch, open a PR
   referencing issue #7. Body: summarise the 2026.8 single-config-entry breakage, the
   device-link fix, the discovery-dedup fix, and the guided cleanup (repair + service).
5. Rebuild the test zip if needed:
   `python -c "import shutil; shutil.make_archive('<dest>/mqtt_connection_state','zip','custom_components','mqtt_connection_state')"`

## Reference IDs (this instance)

- "3D Drucker" real device: `c7e43dc43766b78eafcc6b65ca1f0210` (z2m entry `fc71d198d35a47ee001e9953754739e2`)
- "Wohnzimmer Licht" pre-migration id `3f76e943e072dae6f9ad865aa5dc32e8` → concrete `4e23d1e72fa8d3500d93cee722ee4944`
- HA-MCP is READ-ONLY; use `ha_eval_template` for device-registry introspection.
