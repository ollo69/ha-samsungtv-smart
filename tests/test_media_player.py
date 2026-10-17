"""Tests for Samsung TV power and Art Mode status."""

import json
from unittest.mock import patch

import pytest

from custom_components.samsungtv_smart.api.samsungws import ArtModeStatus, SamsungTVWS
from custom_components.samsungtv_smart.media_player import (
    ATTR_ART_MODE_STATUS,
    SamsungTVDevice,
)


@pytest.mark.parametrize(
    ("power_state", "art_mode_status", "expected_status"),
    [
        ("on", ArtModeStatus.On, False),
        ("on", ArtModeStatus.Off, True),
        ("on", ArtModeStatus.Unavailable, True),
        ("on", ArtModeStatus.Unsupported, True),
        ("off", ArtModeStatus.On, False),
        ("off", ArtModeStatus.Off, False),
        ("off", ArtModeStatus.Unavailable, False),
        ("off", ArtModeStatus.Unsupported, False),
        (None, ArtModeStatus.On, False),
        (None, ArtModeStatus.Off, False),
        (None, ArtModeStatus.Unavailable, False),
        (None, ArtModeStatus.Unsupported, False),
    ],
)
@pytest.mark.asyncio
async def test_check_status_with_device_power_state(
    power_state, art_mode_status, expected_status
):
    """Treat art as off even when the device reports its power is on."""
    device = SamsungTVDevice.__new__(SamsungTVDevice)
    device._host = "192.0.2.1"
    device._device_info = {"device": {"PowerState": "on"}}
    device._ws = SamsungTVWS(device._host)
    device._ws._artmode_status = art_mode_status
    device_info = (
        {"device": {"PowerState": power_state}} if power_state is not None else None
    )

    with patch.object(
        device, "_async_load_device_info", return_value=device_info
    ) as load_device_info:
        status = await device._check_status()

    assert status is expected_status
    load_device_info.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
async def test_frame_art_mode_status_reply():
    """Expose the 2024 Frame reply as art on and media player off."""
    device = SamsungTVDevice.__new__(SamsungTVDevice)
    device._host = "192.0.2.1"
    device._device_info = {"device": {"PowerState": "on"}}
    device._ws = SamsungTVWS(device._host)
    device._st = None
    message = json.dumps(
        {
            "event": "d2d_service_message",
            "data": json.dumps({"event": "get_artmode_status", "value": "on"}),
        }
    )

    device._ws._on_message_art(None, message)

    assert device.extra_state_attributes[ATTR_ART_MODE_STATUS] == "on"
    with patch.object(
        device, "_async_load_device_info", return_value=device._device_info
    ):
        assert await device._check_status() is False
