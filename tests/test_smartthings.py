"""Tests for the SmartThings TV API."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.samsungtv_smart.api.smartthings import SmartThingsTV


@pytest.mark.parametrize(
    ("enabled", "mode"),
    [
        (True, "TurnOn"),
        (False, "TurnOff"),
    ],
)
@pytest.mark.asyncio
async def test_async_set_hue_sync_sends_expected_mode(enabled, mode):
    """Hue Sync uses the Samsung light-control capability in the background."""
    response = AsyncMock()
    response.json.return_value = {}
    response_context = AsyncMock()
    response_context.__aenter__.return_value = response
    session = MagicMock()
    session.post.return_value = response_context
    smartthings = SmartThingsTV(
        api_key="test-api-key",
        device_id="test-device-id",
        session=session,
    )
    smartthings._device_refresh = AsyncMock()

    await smartthings.async_set_hue_sync(enabled)

    session.post.assert_called_once_with(
        "https://api.smartthings.com/v1/devices/test-device-id/commands",
        headers={
            "Authorization": "Bearer test-api-key",
            "Accept": "application/json",
            "Connection": "keep-alive",
        },
        data=str(
            {
                "commands": [
                    {
                        "component": "main",
                        "capability": "samsungvd.lightControl",
                        "command": "setLightControlMode",
                        "arguments": [mode],
                    }
                ]
            }
        ),
        raise_for_status=True,
    )
    smartthings._device_refresh.assert_awaited_once_with()
