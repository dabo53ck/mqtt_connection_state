# Repository guide

Home Assistant **custom integration** — `mqtt_connection_state`, David's
maintained fork of [`studioIngrid/mqtt_connection_state`](https://github.com/studioIngrid/mqtt_connection_state).
Adds a `binary_sensor` per MQTT device showing its connection state, plus a
broker sensor and one sensor per Zigbee2MQTT bridge.

## Layout

- `custom_components/mqtt_connection_state/` — the integration
  - `binary_sensor.py` — per-device sensor, plus `MqttBrokerConnectionSensorEntity`
    and `MqttBridgeConnectionSensorEntity` (on the auto-created `kind: system` entry)
  - `__init__.py` — global `async_setup` (discovery, services, the system entry),
    per-entry `async_setup_entry`
  - `helpers.py` — `process_message_payload`, `resolve_source_device_id`,
    duplicate-entry detection
  - `config_flow.py`, `discovery.py`, `repairs.py`, `services.py`
  - `translations/{en,de,nl,sv}.json`
- `tests/` — pytest (`pytest-homeassistant-custom-component`)
- `.github/workflows/` — `tests.yml` (pytest + coverage), `validate.yml`
  (hassfest, HACS action, ruff)
- `pyproject.toml` — ruff + pytest config; `hacs.json`, `manifest.json`

## Conventions

- Branch `dev` → PR → `main`. Plain imperative commit subjects.
- Release = git tag `vX.Y.Z` + GitHub release on the fork. Pre-release betas use
  a tag like `vX.Y.Z-beta.N` marked "pre-release" (so it is not "Latest" and HACS
  only offers it with "Show beta versions" on).
- **`manifest.json` `version` must be plain numeric** (`1.1.1`, or `1.1.1.1` for a
  numbered beta) — a non-numeric suffix like `1.0.1b` makes HA refuse to load the
  whole integration. The `-beta.N` marker lives only in the git tag.
- `ruff check .` and `pytest` must pass; `validate.yml` (hassfest + HACS) must be
  green. A new `manifest.json` key that hassfest rejects for custom integrations
  (e.g. `homeassistant`) belongs in `hacs.json` instead.

## Event contract — do not break

The companion blueprint
[`mqtt-connection-state-monitor`](https://github.com/dabo53ck/mqtt-connection-state-monitor)
triggers on the `mqtt_connection_state_changed` event and hard-depends on:

- event type **`mqtt_connection_state_changed`**
- `event.data.state` is exactly the string **`"online"`** or **`"offline"`**
- `event.data.entity_id` is the connection-state entity id; the blueprint derives
  the device name as
  `entity_id | replace('binary_sensor.', '') | replace('_connection_state', '')`

Changing the event type, a `state` value, or the `entity_id` shape breaks the
blueprint trigger **silently**. The event may only be suppressed for the
startup state-restore (`old_state is None` in `_handle_message_updates`) — a
genuine `online`↔`offline` transition, including a mass recovery, must keep
firing one event per device.

## Commit messages

Do **not** add AI / assistant attribution to commit messages or PR descriptions:
no `Co-Authored-By:` line naming an AI, no `Claude-Session:` line, no
"Generated with …" footer. Commits are authored solely by the repository owner.
Human `Co-Authored-By:` lines are fine.

A `commit-msg` hook enforces this — enable it once per clone:

```sh
git config core.hooksPath .githooks
```
