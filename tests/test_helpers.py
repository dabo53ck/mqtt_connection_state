"""Unit tests for the payload parser in helpers.py."""

from __future__ import annotations

import pytest

from custom_components.mqtt_connection_state.helpers import process_message_payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("online", "online"),
        ("ONLINE", "online"),
        ("on", "online"),
        ("true", "online"),
        ("1", "online"),
        ("  online  ", "online"),
        ("offline", "offline"),
        ("off", "offline"),
        ("0", "offline"),
        ("anything else", "offline"),
        ("", "offline"),
        (b"online", "online"),
        (b"offline", "offline"),
        (1, "online"),
        (0, "offline"),
        (True, "online"),
        ('{"state": "online"}', "online"),
        ('{"state": "offline"}', "offline"),
        ('{"status": "online"}', "online"),
        ('{"availability": "online"}', "online"),
        # valid JSON, but no recognised key -> conservative "offline", not a crash
        ('{"foo": "online"}', "offline"),
        ("[1, 2, 3]", "offline"),
    ],
)
def test_process_message_payload(payload: object, expected: str) -> None:
    """Every supported payload shape maps to 'online' or 'offline'."""
    assert process_message_payload(None, "some/topic", payload) == expected


def test_process_message_payload_invalid_json_returns_none() -> None:
    """Malformed JSON is reported as unparseable (entity goes unavailable)."""
    assert process_message_payload(None, "some/topic", "{not json") is None


def test_process_message_payload_unsupported_type_returns_none() -> None:
    """A non-scalar, non-bytes payload is rejected rather than guessed."""
    assert process_message_payload(None, "some/topic", {"a": 1}) is None
