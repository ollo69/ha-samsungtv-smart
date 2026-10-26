"""Regression tests for unavailable Art Mode telemetry (no device I/O)."""

import json
from unittest.mock import Mock

import pytest

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN

from custom_components.samsungtv_smart.api.samsungws import ArtModeStatus, SamsungTVWS
from custom_components.samsungtv_smart.media_player import (
    ATTR_ART_MODE_STATUS,
    SamsungTVDevice,
)


@pytest.fixture
def remote():
    """Build a real protocol client, replacing all command paths with mocks."""
    client = SamsungTVWS("tv.example.invalid")
    client.send_key = Mock()
    client._get_artmode_status = Mock()
    return client


def attributes(remote):
    """Read the real HA property without initializing unrelated services."""
    device = SamsungTVDevice.__new__(SamsungTVDevice)
    device._host = "tv.example.invalid"
    device._ws = remote
    device._st = None
    return device.extra_state_attributes


def receive(remote, event, **payload):
    """Pass a sanitized Art-channel data envelope to the actual parser."""
    remote._handle_artmode_status({"data": json.dumps({"event": event, **payload})})


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ArtModeStatus.On, STATE_ON),
        (ArtModeStatus.Off, STATE_OFF),
        (ArtModeStatus.Unavailable, STATE_UNKNOWN),
        (ArtModeStatus.Unsupported, None),
    ],
)
def test_attribute_preserves_unavailable_and_unsupported(remote, status, expected):
    """Unavailable must not look off; unsupported keeps the attribute absent."""
    remote._artmode_status = status
    result = attributes(remote)
    if expected is None:
        assert ATTR_ART_MODE_STATUS not in result
    else:
        assert result[ATTR_ART_MODE_STATUS] == expected


@pytest.mark.parametrize(
    ("event", "field"),
    [("artmode_status", "value"), ("art_mode_changed", "status")],
)
@pytest.mark.parametrize("value", ["nav", "unexpected", "", None, True, 0, {}, []])
@pytest.mark.parametrize("initial", [ArtModeStatus.On, ArtModeStatus.Off])
def test_invalid_status_is_unknown_and_does_not_toggle(
    remote, event, field, value, initial
):
    """An invalid reply is not evidence for either mode, even with a request pending."""
    remote._artmode_status = initial
    remote._power_on_requested = True
    remote._power_on_artmode = True
    receive(remote, event, **{field: value})
    assert remote.artmode_status == ArtModeStatus.Unavailable
    assert attributes(remote)[ATTR_ART_MODE_STATUS] == STATE_UNKNOWN
    remote.send_key.assert_not_called()
    assert remote._power_on_requested


@pytest.mark.parametrize("event", ["artmode_status", "art_mode_changed"])
def test_missing_status_is_unknown(remote, event):
    """A recognized event without a status must not default to off."""
    remote._artmode_status = ArtModeStatus.On
    receive(remote, event)
    assert remote.artmode_status == ArtModeStatus.Unavailable
    assert attributes(remote)[ATTR_ART_MODE_STATUS] == STATE_UNKNOWN
    remote.send_key.assert_not_called()


@pytest.mark.parametrize(
    ("event", "field"),
    [("artmode_status", "value"), ("art_mode_changed", "status")],
)
@pytest.mark.parametrize(
    ("value", "status", "expected"),
    [("on", ArtModeStatus.On, STATE_ON), ("off", ArtModeStatus.Off, STATE_OFF)],
)
def test_valid_replies_keep_existing_behavior(
    remote, event, field, value, status, expected
):
    """Explicit on/off values remain supported and passive without a pending request."""
    receive(remote, event, **{field: value})
    assert remote.artmode_status == status
    assert attributes(remote)[ATTR_ART_MODE_STATUS] == expected
    remote.send_key.assert_not_called()


@pytest.mark.parametrize("want_art", [False, True])
@pytest.mark.parametrize("value", ["on", "off"])
def test_pending_request_waits_for_valid_status(remote, want_art, value):
    """Unknown replies must neither toggle power nor consume the pending request."""
    remote._power_on_requested = True
    remote._power_on_artmode = want_art
    receive(remote, "artmode_status", value="unexpected")
    remote.send_key.assert_not_called()
    assert remote._power_on_requested
    receive(remote, "artmode_status", value=value)
    if (value == "on") != want_art:
        remote.send_key.assert_called_once_with("KEY_POWER", key_press_delay=0)
    else:
        remote.send_key.assert_not_called()
    assert not remote._power_on_requested


def test_standby_preserves_unknown_art_status(remote):
    """Standby is not an Art-off/TV-mode confirmation."""
    remote._artmode_status = ArtModeStatus.On
    remote._power_on_requested = True
    receive(remote, "go_to_standby")
    assert remote.artmode_status == ArtModeStatus.Unavailable
    assert attributes(remote)[ATTR_ART_MODE_STATUS] == STATE_UNKNOWN
    remote.send_key.assert_not_called()
    assert remote._power_on_requested


def test_wakeup_requests_status_without_changing_it(remote):
    """Preserve wakeup's existing explicit query behavior."""
    remote._artmode_status = ArtModeStatus.On
    receive(remote, "wakeup")
    remote._get_artmode_status.assert_called_once_with()
    assert remote.artmode_status == ArtModeStatus.On
    remote.send_key.assert_not_called()


def test_unrelated_event_keeps_current_status(remote):
    """Unrelated messages must not invalidate a known status."""
    remote._artmode_status = ArtModeStatus.On
    receive(remote, "unrelated", value="off")
    assert remote.artmode_status == ArtModeStatus.On
    remote.send_key.assert_not_called()
