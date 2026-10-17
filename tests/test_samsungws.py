"""Tests for Samsung TV Art Mode messages."""

import json

import pytest

from custom_components.samsungtv_smart.api.samsungws import ArtModeStatus, SamsungTVWS


@pytest.mark.parametrize(
    ("event", "status_field"),
    [
        ("art_mode_changed", "status"),
        ("artmode_status", "value"),
        ("get_artmode_status", "value"),
    ],
)
@pytest.mark.parametrize(
    ("value", "expected_status"),
    [("on", ArtModeStatus.On), ("off", ArtModeStatus.Off)],
)
def test_art_mode_status_message(event, status_field, value, expected_status):
    """Recognize Art Mode updates and status replies from the art channel."""
    websocket = SamsungTVWS("192.0.2.1")
    message = json.dumps(
        {
            "event": "d2d_service_message",
            "data": json.dumps({"event": event, status_field: value}),
        }
    )

    websocket._on_message_art(None, message)

    assert websocket.artmode_status == expected_status
