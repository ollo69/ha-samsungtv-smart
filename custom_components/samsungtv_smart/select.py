"""Samsung Frame TV - Matte type and color select entities."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_ID, CONF_NAME, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.art import SamsungTVAsyncArt
from .const import (
    DATA_ART_API,
    DATA_CFG,
    DEFAULT_PORT,
    DOMAIN,
    WS_PREFIX,
    CONF_WS_NAME,
)

_LOGGER = logging.getLogger(__name__)

# Retry settings when TV is off at startup
_RETRY_INTERVAL = 30   # seconds between retries
_MAX_RETRIES = 10      # give up after 5 minutes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Samsung Frame TV matte select entities from config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]
    host = config[CONF_HOST]
    port = config.get(CONF_PORT, DEFAULT_PORT)
    token = config.get(CONF_TOKEN)
    ws_name = config.get(CONF_WS_NAME, "HomeAssistant")
    device_unique_id = config.get(CONF_ID, entry.entry_id)
    device_name = config.get(CONF_NAME) or entry.title or host

    session = async_get_clientsession(hass)

    # Reuse shared art_api if already created by sensor.py, otherwise create one
    art_api = hass.data[DOMAIN][entry.entry_id].get(DATA_ART_API)
    if not art_api:
        art_api = SamsungTVAsyncArt(
            host=host,
            port=port,
            token=token,
            session=session,
            timeout=5,
            name=f"{WS_PREFIX} {ws_name} Art Select",
        )

    # Check Frame TV support quickly - if not supported, skip
    try:
        async with asyncio.timeout(5):
            is_supported = await art_api.supported()
    except Exception:
        is_supported = False

    if not is_supported:
        _LOGGER.debug("Frame TV not supported on %s, skipping matte select entities", host)
        return

    # Create the two select entities
    matte_type_select = SamsungTVMatteTypeSelect(
        hass, entry, art_api, device_name, device_unique_id
    )
    matte_color_select = SamsungTVMatteColorSelect(
        hass, entry, art_api, device_name, device_unique_id
    )

    async_add_entities([matte_type_select, matte_color_select])

    # Populate options from TV in background (TV might be off at boot)
    hass.async_create_background_task(
        _load_matte_options(hass, art_api, matte_type_select, matte_color_select),
        f"samsungtv_matte_options_{entry.entry_id}",
    )


async def _load_matte_options(
    hass: HomeAssistant,
    art_api: SamsungTVAsyncArt,
    type_select: "SamsungTVMatteTypeSelect",
    color_select: "SamsungTVMatteColorSelect",
) -> None:
    """Fetch matte list from TV and populate select options, with retries."""
    for attempt in range(_MAX_RETRIES):
        try:
            async with asyncio.timeout(10):
                matte_types, matte_colors = await art_api.get_matte_list(include_color=True)

            # Extract string values from dict objects returned by the TV
            type_options = [
                m["matte_type"] if isinstance(m, dict) else str(m)
                for m in matte_types
            ]
            color_options = [
                m["color"] if isinstance(m, dict) else str(m)
                for m in matte_colors
            ]

            if type_options:
                type_select.set_options(type_options)
            if color_options:
                color_select.set_options(color_options)

            _LOGGER.info(
                "Matte selects populated — types: %s | colors: %s",
                type_options,
                color_options,
            )
            return

        except asyncio.TimeoutError:
            _LOGGER.debug(
                "Timeout fetching matte list (attempt %d/%d), retrying in %ds",
                attempt + 1, _MAX_RETRIES, _RETRY_INTERVAL,
            )
        except Exception as ex:
            _LOGGER.debug(
                "Error fetching matte list (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES, ex,
            )

        await asyncio.sleep(_RETRY_INTERVAL)

    _LOGGER.warning("Could not populate matte options after %d attempts", _MAX_RETRIES)


class SamsungTVMatteSelectBase(SelectEntity):
    """Base class for Samsung Frame TV matte select entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        art_api: SamsungTVAsyncArt,
        device_name: str,
        device_unique_id: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._art_api = art_api
        self._device_name = device_name
        self._device_unique_id = device_unique_id
        self._attr_options: list[str] = []
        self._attr_current_option: str | None = None
        self._attr_should_poll = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=self._device_name,
        )

    def set_options(self, options: list[str]) -> None:
        """Update available options and refresh HA state."""
        self._attr_options = options
        if self._attr_current_option not in options:
            self._attr_current_option = options[0] if options else None
        self.async_write_ha_state()

    async def _async_refresh_current(self) -> None:
        """Read current artwork matte from TV and update state."""
        try:
            async with asyncio.timeout(5):
                current = await self._art_api.get_current()
            if current:
                matte_id: str = current.get("matte_id", "")
                self._parse_matte_id(matte_id)
                self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.debug("Could not refresh current matte: %s", ex)

    def _parse_matte_id(self, matte_id: str) -> None:
        """To be implemented by subclass."""
        raise NotImplementedError


class SamsungTVMatteTypeSelect(SamsungTVMatteSelectBase):
    """Select entity for matte frame type (e.g. modern, shadowbox, triptych...)."""

    _attr_icon = "mdi:border-style"
    _attr_has_entity_name = True

    def __init__(self, hass, entry, art_api, device_name, device_unique_id):
        super().__init__(hass, entry, art_api, device_name, device_unique_id)
        self._attr_unique_id = f"{device_unique_id}_matte_type"
        self._attr_name = "Matte Type"
        self._attr_options = ["none"]
        self._attr_current_option = "none"

    def _parse_matte_id(self, matte_id: str) -> None:
        """Extract type part from matte_id (format: type_color or just type)."""
        if "_" in matte_id:
            matte_type = matte_id.rsplit("_", 1)[0]
        else:
            matte_type = matte_id or "none"
        if matte_type in self._attr_options:
            self._attr_current_option = matte_type

    async def async_select_option(self, option: str) -> None:
        """Called when user picks a new matte type."""
        try:
            current = await self._art_api.get_current()
            if not current:
                _LOGGER.warning("Cannot change matte type: no current artwork")
                return

            content_id: str = current.get("content_id", "")
            existing_matte: str = current.get("matte_id", "none_polar")

            # Keep existing color, change only the type
            if "_" in existing_matte:
                color_part = existing_matte.rsplit("_", 1)[1]
            else:
                color_part = "polar"

            new_matte_id = f"{option}_{color_part}" if option != "none" else "none"

            await self._art_api.change_matte(content_id=content_id, matte_id=new_matte_id)
            self._attr_current_option = option
            self.async_write_ha_state()
            _LOGGER.debug("Matte type changed to %s (full id: %s)", option, new_matte_id)

        except Exception as ex:
            _LOGGER.error("Error changing matte type: %s", ex)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_current()


class SamsungTVMatteColorSelect(SamsungTVMatteSelectBase):
    """Select entity for matte color (e.g. polar, black, apricot...)."""

    _attr_icon = "mdi:palette"
    _attr_has_entity_name = True

    def __init__(self, hass, entry, art_api, device_name, device_unique_id):
        super().__init__(hass, entry, art_api, device_name, device_unique_id)
        self._attr_unique_id = f"{device_unique_id}_matte_color"
        self._attr_name = "Matte Color"
        self._attr_options = ["polar"]
        self._attr_current_option = "polar"

    def _parse_matte_id(self, matte_id: str) -> None:
        """Extract color part from matte_id (format: type_color)."""
        if "_" in matte_id:
            color = matte_id.rsplit("_", 1)[1]
            if color in self._attr_options:
                self._attr_current_option = color

    async def async_select_option(self, option: str) -> None:
        """Called when user picks a new matte color."""
        try:
            current = await self._art_api.get_current()
            if not current:
                _LOGGER.warning("Cannot change matte color: no current artwork")
                return

            content_id: str = current.get("content_id", "")
            existing_matte: str = current.get("matte_id", "none")

            # Keep existing type, change only the color
            if "_" in existing_matte:
                type_part = existing_matte.rsplit("_", 1)[0]
            else:
                type_part = existing_matte or "shadowbox"

            new_matte_id = f"{type_part}_{option}"

            await self._art_api.change_matte(content_id=content_id, matte_id=new_matte_id)
            self._attr_current_option = option
            self.async_write_ha_state()
            _LOGGER.debug("Matte color changed to %s (full id: %s)", option, new_matte_id)

        except Exception as ex:
            _LOGGER.error("Error changing matte color: %s", ex)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self._async_refresh_current()
