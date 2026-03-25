"""Samsung Frame TV Art Mode switch entity."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_ID,
    CONF_NAME,
    CONF_PORT,
    CONF_TOKEN,
    STATE_ON,
    STATE_OFF,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from pysmartthings import Capability, Command
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

from .api.art import SamsungTVAsyncArt
from .const import (
    CONF_WS_NAME,
    DATA_ART_API,
    DATA_CFG,
    DEFAULT_PORT,
    DOMAIN,
    WS_PREFIX,
)
from . import async_get_samsungtv_api_key

_LOGGER = logging.getLogger(__name__)

COMPONENT_MAIN = "main"  # SmartThings component

# Time to wait for TV to be ready after WOL
TV_STARTUP_DELAY = 8  # seconds


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Samsung Frame Art Mode switch from config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]
    host = config[CONF_HOST]
    port = config.get(CONF_PORT, DEFAULT_PORT)
    token = config.get(CONF_TOKEN)
    ws_name = config.get(CONF_WS_NAME, "HomeAssistant")

    # Get device unique ID - must match entity.py logic for device grouping
    device_unique_id = config.get(CONF_ID, entry.entry_id)

    # Get device name from config or entry title, fallback to host
    device_name = config.get(CONF_NAME) or entry.title or host

    session = async_get_clientsession(hass)

    # SmartThings config (needed for power off via Command.OFF)
    from .const import CONF_API_KEY, CONF_DEVICE_ID, CONF_AUTH_METHOD, CONF_OAUTH_TOKEN, AUTH_METHOD_OAUTH
    api_key = config.get(CONF_API_KEY)
    device_id = config.get(CONF_DEVICE_ID)
    auth_method = config.get(CONF_AUTH_METHOD)
    if auth_method == AUTH_METHOD_OAUTH and not api_key:
        oauth_token = config.get(CONF_OAUTH_TOKEN)
        if oauth_token and isinstance(oauth_token, dict):
            api_key = oauth_token.get("access_token")

    entities = []

    # Power switch is always created.
    # If SmartThings is configured, turn_off uses Command.OFF (works in Art Mode too).
    # Without SmartThings, turn_off falls back to media_player which handles Art Mode
    # natively via KEY_POWER over WebSocket.
    entities.append(
        SamsungTVPowerSwitch(
            hass=hass,
            entry=entry,
            device_id=device_id if (api_key and device_id) else None,
            device_name=device_name,
            session=session,
            device_unique_id=device_unique_id,
        )
    )
    _LOGGER.debug(
        "Power switch created for %s (SmartThings: %s)",
        device_name,
        "yes" if (api_key and device_id) else "no — WebSocket fallback",
    )
    
    # Check if art_api already exists (created by sensor platform)
    art_api = hass.data[DOMAIN][entry.entry_id].get(DATA_ART_API)
    
    if art_api is None:
        # Create the Art API instance if not already created
        art_api = SamsungTVAsyncArt(
            host=host,
            port=port,
            token=token,
            session=session,
            timeout=5,
            name=f"{WS_PREFIX} {ws_name} Art",
        )
        
        # Quick check if Frame TV is supported
        try:
            async with asyncio.timeout(5):
                is_supported = await art_api.supported()
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout checking Frame TV support for %s", host)
            is_supported = False
        except Exception as ex:
            _LOGGER.debug("Frame TV support check failed: %s", ex)
            is_supported = False
        
        if not is_supported:
            _LOGGER.info("Frame TV art mode not supported on %s - art mode switch not created", host)
        else:
            # Store for later use
            hass.data[DOMAIN][entry.entry_id][DATA_ART_API] = art_api
            # Add Art Mode switch
            entities.append(FrameArtModeSwitch(hass, entry, art_api, device_name, host, device_unique_id))
            _LOGGER.info("Frame Art Mode switch created for %s", device_name)
    else:
        # Art API exists, so Frame TV is supported
        entities.append(FrameArtModeSwitch(hass, entry, art_api, device_name, host, device_unique_id))
        _LOGGER.info("Frame Art Mode switch created for %s", device_name)
    
    # Create the switch entities
    if entities:
        async_add_entities(entities)


class FrameArtModeSwitch(SwitchEntity):
    """Switch to control Samsung Frame TV Art Mode."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True
    _attr_name = "Art Mode"
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        art_api: SamsungTVAsyncArt,
        device_name: str,
        host: str,
        device_unique_id: str,
    ) -> None:
        """Initialize the Art Mode switch."""
        self._hass = hass
        self._entry = entry
        self._art_api = art_api
        self._device_name = device_name
        self._host = host
        self._device_unique_id = device_unique_id
        self._attr_unique_id = f"{entry.entry_id}_art_mode_switch"
        self._attr_is_on = None
        self._available = True
        self._updating = False
        self._media_player_entity_id: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the TV device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=self._device_name,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def is_on(self) -> bool | None:
        """Return True if Art Mode is on."""
        return self._attr_is_on

    def _get_media_player_entity_id(self) -> str | None:
        """Get the media_player entity_id for this TV."""
        if self._media_player_entity_id:
            return self._media_player_entity_id
        
        # Find media_player entity for this config entry using the correct API
        entity_registry = er.async_get(self._hass)
        for entity in entity_registry.entities.values():
            if (
                entity.config_entry_id == self._entry.entry_id
                and entity.domain == "media_player"
            ):
                self._media_player_entity_id = entity.entity_id
                return entity.entity_id
        
        return None

    async def _is_tv_on(self) -> bool:
        """Check if TV is currently on."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            return False
        
        state = self._hass.states.get(entity_id)
        if state is None:
            return False
        
        # TV is "on" if state is not off/unavailable
        return state.state not in (STATE_OFF, "unavailable", "unknown")

    async def _turn_on_tv(self) -> bool:
        """Turn on the TV using media_player service."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            _LOGGER.warning("Could not find media_player entity for %s", self._device_name)
            return False
        
        _LOGGER.info("Turning on TV %s before activating Art Mode", entity_id)
        
        try:
            await self._hass.services.async_call(
                "media_player",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )
            return True
        except Exception as ex:
            _LOGGER.error("Failed to turn on TV: %s", ex)
            return False

    async def _wait_for_tv_ready(self, max_wait: int = 15) -> bool:
        """Wait for TV to be ready after turning on."""
        _LOGGER.debug("Waiting for TV to be ready (max %ds)...", max_wait)
        
        for i in range(max_wait):
            await asyncio.sleep(1)
            
            # Try to connect to Art API
            try:
                async with asyncio.timeout(3):
                    is_supported = await self._art_api.supported()
                    if is_supported:
                        _LOGGER.debug("TV ready after %d seconds", i + 1)
                        return True
            except Exception:
                pass
            
            _LOGGER.debug("TV not ready yet, waiting... (%d/%d)", i + 1, max_wait)
        
        _LOGGER.warning("TV did not become ready within %d seconds", max_wait)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn Art Mode on."""
        _LOGGER.debug("Turning Art Mode ON for %s", self._device_name)
        
        # Check if TV is on
        tv_is_on = await self._is_tv_on()
        
        if not tv_is_on:
            _LOGGER.info("TV is off, turning it on first...")
            
            # Turn on TV
            if not await self._turn_on_tv():
                _LOGGER.error("Failed to turn on TV, cannot activate Art Mode")
                return
            
            # Wait for TV to be ready
            if not await self._wait_for_tv_ready(max_wait=20):
                _LOGGER.warning("TV may not be fully ready, attempting Art Mode anyway...")
            
            # Additional delay for TV to stabilize
            await asyncio.sleep(2)
        
        # Now activate Art Mode with retry
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(10):
                    _LOGGER.debug("Art Mode ON attempt %d/%d for %s", attempt + 1, max_retries, self._device_name)
                    result = await self._art_api.set_artmode(True)
                    if result:
                        # Set state immediately for responsive UI
                        self._attr_is_on = True
                        self._available = True
                        self.async_write_ha_state()
                        _LOGGER.info("Art Mode turned ON for %s", self._device_name)
                        
                        # Wait for TV to confirm, then refresh state
                        await asyncio.sleep(2)
                        await self.async_update()
                        return  # Success, exit
                    else:
                        _LOGGER.debug("Art Mode set_artmode returned None/False on attempt %d", attempt + 1)
                        if attempt < max_retries - 1:
                            _LOGGER.debug("Retrying in %d seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout on attempt %d/%d", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
            except Exception as ex:
                _LOGGER.debug("Error on attempt %d/%d: %s", attempt + 1, max_retries, ex)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        
        # All retries failed
        _LOGGER.warning("Failed to turn Art Mode ON for %s after %d attempts", self._device_name, max_retries)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn Art Mode off (switch to normal TV mode)."""
        _LOGGER.debug("Turning Art Mode OFF for %s", self._device_name)
        
        # Check if TV is on
        tv_is_on = await self._is_tv_on()
        
        if not tv_is_on:
            _LOGGER.debug("TV is already off, Art Mode is already off")
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(10):
                    _LOGGER.debug("Art Mode OFF attempt %d/%d for %s", attempt + 1, max_retries, self._device_name)
                    result = await self._art_api.set_artmode(False)
                    if result:
                        # Set state immediately for responsive UI
                        self._attr_is_on = False
                        self._available = True
                        self.async_write_ha_state()
                        _LOGGER.info("Art Mode turned OFF for %s", self._device_name)
                        
                        # Wait for TV to confirm, then refresh state
                        await asyncio.sleep(2)
                        await self.async_update()
                        return  # Success, exit
                    else:
                        _LOGGER.debug("Art Mode set_artmode(False) returned None/False on attempt %d", attempt + 1)
                        if attempt < max_retries - 1:
                            _LOGGER.debug("Retrying in %d seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                        
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout on attempt %d/%d", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
            except Exception as ex:
                _LOGGER.debug("Error on attempt %d/%d: %s", attempt + 1, max_retries, ex)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        
        # All retries failed
        _LOGGER.warning("Failed to turn Art Mode OFF for %s after %d attempts", self._device_name, max_retries)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the Art Mode state."""
        if self._updating:
            return
        
        self._updating = True
        try:
            # FIRST: Check if TV is powered off
            tv_is_on = await self._is_tv_on()
            
            if not tv_is_on:
                # TV is off, Art Mode must be off too
                _LOGGER.debug("TV is off, setting Art Mode to off")
                self._attr_is_on = False
                self._available = True
                return
            
            # TV is on, get actual Art Mode status
            async with asyncio.timeout(8):
                art_mode = await self._art_api.get_artmode()
                if art_mode is not None:
                    self._attr_is_on = art_mode == "on"
                    self._available = True
                    _LOGGER.debug("Art Mode state updated: %s", self._attr_is_on)
                else:
                    _LOGGER.debug("Could not get Art Mode state")
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout updating Art Mode state")
            # Don't mark as unavailable on timeout - TV might be off
        except Exception as ex:
            _LOGGER.debug("Error updating Art Mode state: %s", ex)
        finally:
            self._updating = False

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        # Schedule initial state update
        self.hass.async_create_background_task(
            self.async_update(),
            f"frame_art_switch_initial_update_{self._entry.entry_id}",
        )


class SamsungTVPowerSwitch(SwitchEntity):
    """Switch for turning Samsung TV on/off.

    Delegates all commands to the media_player entity so there is a single
    source of truth for the TV power state (WOL, WebSocket, SmartThings are
    all handled there).  This switch is a pure UI convenience wrapper.
    """

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_has_entity_name = True
    _attr_translation_key = "power"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str | None,
        device_name: str,
        session,
        device_unique_id: str,
    ) -> None:
        """Initialize the power switch."""
        self.hass = hass
        self._entry = entry
        self._device_id = device_id  # None if SmartThings not configured
        self._session = session
        self._device_name = device_name
        self._device_unique_id = device_unique_id
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._media_player_entity_id: str | None = None

    async def _get_st_client(self):
        """Get SmartThings client with current (possibly refreshed) token."""
        from pysmartthings import SmartThings
        from .const import CONF_API_KEY, CONF_OAUTH_TOKEN, CONF_AUTH_METHOD, AUTH_METHOD_OAUTH

        api_key = await async_get_samsungtv_api_key(self.hass, self._entry)
        if not api_key:
            config = self.hass.data[DOMAIN][self._entry.entry_id][DATA_CFG]
            api_key = config.get(CONF_API_KEY)
            if not api_key:
                oauth_token = config.get(CONF_OAUTH_TOKEN)
                if oauth_token and isinstance(oauth_token, dict):
                    api_key = oauth_token.get("access_token")
        if not api_key:
            _LOGGER.warning("Power switch: no SmartThings API key available")
            return None
        st_client = SmartThings(session=self._session)
        st_client.authenticate(api_key)
        return st_client

    def _get_media_player_entity_id(self) -> str | None:
        """Get the media_player entity_id for this TV (cached after first lookup)."""
        if self._media_player_entity_id:
            return self._media_player_entity_id

        entity_registry = er.async_get(self.hass)
        for entity in entity_registry.entities.values():
            if (
                entity.config_entry_id == self._entry.entry_id
                and entity.domain == "media_player"
            ):
                self._media_player_entity_id = entity.entity_id
                return entity.entity_id

        return None

    def _get_media_player_state(self):
        """Return the current HA state object of the media_player, or None."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            return None
        return self.hass.states.get(entity_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=self._device_name,
        )

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return "Power"

    @property
    def available(self) -> bool:
        """Available unless the media_player is truly unreachable."""
        state = self._get_media_player_state()
        if state is None:
            return False
        return state.state != "unavailable"

    @property
    def is_on(self) -> bool | None:
        """TV is physically on if media_player is on OR Art Mode is active.

        A Frame TV in Art Mode reports media_player state as "off", but the
        screen is physically on.  We treat that as on so that automations
        reading this switch never send a spurious turn_on to an already-lit TV.
        """
        state = self._get_media_player_state()
        if state is None:
            return None
        # Clearly on (watching TV, idle, paused...)
        if state.state not in (STATE_OFF, "unavailable", "unknown"):
            return True
        # media_player says "off" — but Art Mode may be active
        if state.state == STATE_OFF:
            return state.attributes.get("art_mode_status") == "on"
        return False

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:power" if self.is_on else "mdi:power-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the TV on — delegates to media_player.turn_on."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            _LOGGER.warning("Power switch: media_player entity not found for %s", self._device_name)
            return

        _LOGGER.debug("Power switch: delegating turn_on to %s", entity_id)
        await self.hass.services.async_call(
            "media_player",
            "turn_on",
            {"entity_id": entity_id},
            blocking=True,
        )
        # State will update automatically when media_player changes
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the TV off.

        Strategy:
        - SmartThings configured → Command.OFF (hardware-level, works regardless
          of TV state including Art Mode).
        - No SmartThings → media_player.turn_off, which handles Art Mode natively
          by sending KEY_POWER over WebSocket when artmode_status is On.
        """
        if self._device_id:
            # SmartThings path — bypasses HA state entirely
            try:
                st_client = await self._get_st_client()
                if st_client:
                    await st_client.execute_device_command(
                        self._device_id,
                        Capability.SWITCH,
                        Command.OFF,
                        COMPONENT_MAIN,
                    )
                    self._attr_is_on = False
                    self.async_write_ha_state()
                    _LOGGER.debug("Power switch: TV turned off via SmartThings")
                    return
                else:
                    _LOGGER.warning("Power switch: SmartThings client unavailable, falling back to WebSocket")
            except Exception as ex:
                _LOGGER.warning("Power switch: SmartThings turn_off failed (%s), falling back to WebSocket", ex)

        # WebSocket fallback (or SmartThings failed) —
        # media_player._turn_off() handles Art Mode via KEY_POWER natively
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            _LOGGER.error("Power switch: no media_player entity found for %s", self._device_name)
            return
        try:
            await self.hass.services.async_call(
                "media_player",
                "turn_off",
                {"entity_id": entity_id},
                blocking=True,
            )
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.debug("Power switch: TV turned off via media_player (WebSocket)")
        except Exception as ex:
            _LOGGER.error("Power switch: WebSocket turn_off failed: %s", ex)

    @callback
    def _handle_media_player_state_change(self, event) -> None:
        """React to media_player state changes and push update immediately."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to media_player state changes when added to HA."""
        entity_id = self._get_media_player_entity_id()
        if entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._handle_media_player_state_change,
                )
            )

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_ID,
    CONF_NAME,
    CONF_PORT,
    CONF_TOKEN,
    STATE_ON,
    STATE_OFF,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from pysmartthings import Capability, Command
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er

from .api.art import SamsungTVAsyncArt
from .const import (
    CONF_WS_NAME,
    DATA_ART_API,
    DATA_CFG,
    DEFAULT_PORT,
    DOMAIN,
    WS_PREFIX,
)
from . import async_get_samsungtv_api_key

_LOGGER = logging.getLogger(__name__)

COMPONENT_MAIN = "main"  # SmartThings component

# Time to wait for TV to be ready after WOL
TV_STARTUP_DELAY = 8  # seconds


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Samsung Frame Art Mode switch from config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]
    host = config[CONF_HOST]
    port = config.get(CONF_PORT, DEFAULT_PORT)
    token = config.get(CONF_TOKEN)
    ws_name = config.get(CONF_WS_NAME, "HomeAssistant")

    # Get device unique ID - must match entity.py logic for device grouping
    device_unique_id = config.get(CONF_ID, entry.entry_id)

    # Get device name from config or entry title, fallback to host
    device_name = config.get(CONF_NAME) or entry.title or host

    session = async_get_clientsession(hass)

    # SmartThings config (needed for power off via Command.OFF)
    from .const import CONF_API_KEY, CONF_DEVICE_ID, CONF_AUTH_METHOD, CONF_OAUTH_TOKEN, AUTH_METHOD_OAUTH
    api_key = config.get(CONF_API_KEY)
    device_id = config.get(CONF_DEVICE_ID)
    auth_method = config.get(CONF_AUTH_METHOD)
    if auth_method == AUTH_METHOD_OAUTH and not api_key:
        oauth_token = config.get(CONF_OAUTH_TOKEN)
        if oauth_token and isinstance(oauth_token, dict):
            api_key = oauth_token.get("access_token")

    entities = []

    # Create Power Switch if SmartThings is configured (needed for reliable turn_off)
    if api_key and device_id:
        entities.append(
            SamsungTVPowerSwitch(
                hass=hass,
                entry=entry,
                device_id=device_id,
                device_name=device_name,
                session=session,
                device_unique_id=device_unique_id,
            )
        )
        _LOGGER.debug("Power switch created for %s", device_name)
    else:
        _LOGGER.debug("SmartThings not configured, power switch not created for %s", device_name)
    
    # Check if art_api already exists (created by sensor platform)
    art_api = hass.data[DOMAIN][entry.entry_id].get(DATA_ART_API)
    
    if art_api is None:
        # Create the Art API instance if not already created
        art_api = SamsungTVAsyncArt(
            host=host,
            port=port,
            token=token,
            session=session,
            timeout=5,
            name=f"{WS_PREFIX} {ws_name} Art",
        )
        
        # Quick check if Frame TV is supported
        try:
            async with asyncio.timeout(5):
                is_supported = await art_api.supported()
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout checking Frame TV support for %s", host)
            is_supported = False
        except Exception as ex:
            _LOGGER.debug("Frame TV support check failed: %s", ex)
            is_supported = False
        
        if not is_supported:
            _LOGGER.info("Frame TV art mode not supported on %s - art mode switch not created", host)
        else:
            # Store for later use
            hass.data[DOMAIN][entry.entry_id][DATA_ART_API] = art_api
            # Add Art Mode switch
            entities.append(FrameArtModeSwitch(hass, entry, art_api, device_name, host, device_unique_id))
            _LOGGER.info("Frame Art Mode switch created for %s", device_name)
    else:
        # Art API exists, so Frame TV is supported
        entities.append(FrameArtModeSwitch(hass, entry, art_api, device_name, host, device_unique_id))
        _LOGGER.info("Frame Art Mode switch created for %s", device_name)
    
    # Create the switch entities
    if entities:
        async_add_entities(entities)


class FrameArtModeSwitch(SwitchEntity):
    """Switch to control Samsung Frame TV Art Mode."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True
    _attr_name = "Art Mode"
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        art_api: SamsungTVAsyncArt,
        device_name: str,
        host: str,
        device_unique_id: str,
    ) -> None:
        """Initialize the Art Mode switch."""
        self._hass = hass
        self._entry = entry
        self._art_api = art_api
        self._device_name = device_name
        self._host = host
        self._device_unique_id = device_unique_id
        self._attr_unique_id = f"{entry.entry_id}_art_mode_switch"
        self._attr_is_on = None
        self._available = True
        self._updating = False
        self._media_player_entity_id: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info to link this entity to the TV device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=self._device_name,
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def is_on(self) -> bool | None:
        """Return True if Art Mode is on."""
        return self._attr_is_on

    def _get_media_player_entity_id(self) -> str | None:
        """Get the media_player entity_id for this TV."""
        if self._media_player_entity_id:
            return self._media_player_entity_id
        
        # Find media_player entity for this config entry using the correct API
        entity_registry = er.async_get(self._hass)
        for entity in entity_registry.entities.values():
            if (
                entity.config_entry_id == self._entry.entry_id
                and entity.domain == "media_player"
            ):
                self._media_player_entity_id = entity.entity_id
                return entity.entity_id
        
        return None

    async def _is_tv_on(self) -> bool:
        """Check if TV is currently on."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            return False
        
        state = self._hass.states.get(entity_id)
        if state is None:
            return False
        
        # TV is "on" if state is not off/unavailable
        return state.state not in (STATE_OFF, "unavailable", "unknown")

    async def _turn_on_tv(self) -> bool:
        """Turn on the TV using media_player service."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            _LOGGER.warning("Could not find media_player entity for %s", self._device_name)
            return False
        
        _LOGGER.info("Turning on TV %s before activating Art Mode", entity_id)
        
        try:
            await self._hass.services.async_call(
                "media_player",
                "turn_on",
                {"entity_id": entity_id},
                blocking=True,
            )
            return True
        except Exception as ex:
            _LOGGER.error("Failed to turn on TV: %s", ex)
            return False

    async def _wait_for_tv_ready(self, max_wait: int = 15) -> bool:
        """Wait for TV to be ready after turning on."""
        _LOGGER.debug("Waiting for TV to be ready (max %ds)...", max_wait)
        
        for i in range(max_wait):
            await asyncio.sleep(1)
            
            # Try to connect to Art API
            try:
                async with asyncio.timeout(3):
                    is_supported = await self._art_api.supported()
                    if is_supported:
                        _LOGGER.debug("TV ready after %d seconds", i + 1)
                        return True
            except Exception:
                pass
            
            _LOGGER.debug("TV not ready yet, waiting... (%d/%d)", i + 1, max_wait)
        
        _LOGGER.warning("TV did not become ready within %d seconds", max_wait)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn Art Mode on."""
        _LOGGER.debug("Turning Art Mode ON for %s", self._device_name)
        
        # Check if TV is on
        tv_is_on = await self._is_tv_on()
        
        if not tv_is_on:
            _LOGGER.info("TV is off, turning it on first...")
            
            # Turn on TV
            if not await self._turn_on_tv():
                _LOGGER.error("Failed to turn on TV, cannot activate Art Mode")
                return
            
            # Wait for TV to be ready
            if not await self._wait_for_tv_ready(max_wait=20):
                _LOGGER.warning("TV may not be fully ready, attempting Art Mode anyway...")
            
            # Additional delay for TV to stabilize
            await asyncio.sleep(2)
        
        # Now activate Art Mode with retry
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(10):
                    _LOGGER.debug("Art Mode ON attempt %d/%d for %s", attempt + 1, max_retries, self._device_name)
                    result = await self._art_api.set_artmode(True)
                    if result:
                        # Set state immediately for responsive UI
                        self._attr_is_on = True
                        self._available = True
                        self.async_write_ha_state()
                        _LOGGER.info("Art Mode turned ON for %s", self._device_name)
                        
                        # Wait for TV to confirm, then refresh state
                        await asyncio.sleep(2)
                        await self.async_update()
                        return  # Success, exit
                    else:
                        _LOGGER.debug("Art Mode set_artmode returned None/False on attempt %d", attempt + 1)
                        if attempt < max_retries - 1:
                            _LOGGER.debug("Retrying in %d seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout on attempt %d/%d", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
            except Exception as ex:
                _LOGGER.debug("Error on attempt %d/%d: %s", attempt + 1, max_retries, ex)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        
        # All retries failed
        _LOGGER.warning("Failed to turn Art Mode ON for %s after %d attempts", self._device_name, max_retries)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn Art Mode off (switch to normal TV mode)."""
        _LOGGER.debug("Turning Art Mode OFF for %s", self._device_name)
        
        # Check if TV is on
        tv_is_on = await self._is_tv_on()
        
        if not tv_is_on:
            _LOGGER.debug("TV is already off, Art Mode is already off")
            self._attr_is_on = False
            self.async_write_ha_state()
            return
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                async with asyncio.timeout(10):
                    _LOGGER.debug("Art Mode OFF attempt %d/%d for %s", attempt + 1, max_retries, self._device_name)
                    result = await self._art_api.set_artmode(False)
                    if result:
                        # Set state immediately for responsive UI
                        self._attr_is_on = False
                        self._available = True
                        self.async_write_ha_state()
                        _LOGGER.info("Art Mode turned OFF for %s", self._device_name)
                        
                        # Wait for TV to confirm, then refresh state
                        await asyncio.sleep(2)
                        await self.async_update()
                        return  # Success, exit
                    else:
                        _LOGGER.debug("Art Mode set_artmode(False) returned None/False on attempt %d", attempt + 1)
                        if attempt < max_retries - 1:
                            _LOGGER.debug("Retrying in %d seconds...", retry_delay)
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                        
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout on attempt %d/%d", attempt + 1, max_retries)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
            except Exception as ex:
                _LOGGER.debug("Error on attempt %d/%d: %s", attempt + 1, max_retries, ex)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
        
        # All retries failed
        _LOGGER.warning("Failed to turn Art Mode OFF for %s after %d attempts", self._device_name, max_retries)
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Update the Art Mode state."""
        if self._updating:
            return
        
        self._updating = True
        try:
            # FIRST: Check if TV is powered off
            tv_is_on = await self._is_tv_on()
            
            if not tv_is_on:
                # TV is off, Art Mode must be off too
                _LOGGER.debug("TV is off, setting Art Mode to off")
                self._attr_is_on = False
                self._available = True
                return
            
            # TV is on, get actual Art Mode status
            async with asyncio.timeout(8):
                art_mode = await self._art_api.get_artmode()
                if art_mode is not None:
                    self._attr_is_on = art_mode == "on"
                    self._available = True
                    _LOGGER.debug("Art Mode state updated: %s", self._attr_is_on)
                else:
                    _LOGGER.debug("Could not get Art Mode state")
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout updating Art Mode state")
            # Don't mark as unavailable on timeout - TV might be off
        except Exception as ex:
            _LOGGER.debug("Error updating Art Mode state: %s", ex)
        finally:
            self._updating = False

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        # Schedule initial state update
        self.hass.async_create_background_task(
            self.async_update(),
            f"frame_art_switch_initial_update_{self._entry.entry_id}",
        )


class SamsungTVPowerSwitch(SwitchEntity):
    """Switch for turning Samsung TV on/off.

    Delegates all commands to the media_player entity so there is a single
    source of truth for the TV power state (WOL, WebSocket, SmartThings are
    all handled there).  This switch is a pure UI convenience wrapper.
    """

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_has_entity_name = True
    _attr_translation_key = "power"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        session,
        device_unique_id: str,
    ) -> None:
        """Initialize the power switch."""
        self.hass = hass
        self._entry = entry
        self._device_id = device_id
        self._session = session
        self._device_name = device_name
        self._device_unique_id = device_unique_id
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._media_player_entity_id: str | None = None

    async def _get_st_client(self):
        """Get SmartThings client with current (possibly refreshed) token."""
        from pysmartthings import SmartThings
        from .const import CONF_API_KEY, CONF_OAUTH_TOKEN, CONF_AUTH_METHOD, AUTH_METHOD_OAUTH

        api_key = await async_get_samsungtv_api_key(self.hass, self._entry)
        if not api_key:
            config = self.hass.data[DOMAIN][self._entry.entry_id][DATA_CFG]
            api_key = config.get(CONF_API_KEY)
            if not api_key:
                oauth_token = config.get(CONF_OAUTH_TOKEN)
                if oauth_token and isinstance(oauth_token, dict):
                    api_key = oauth_token.get("access_token")
        if not api_key:
            _LOGGER.warning("Power switch: no SmartThings API key available")
            return None
        st_client = SmartThings(session=self._session)
        st_client.authenticate(api_key)
        return st_client

    def _get_media_player_entity_id(self) -> str | None:
        """Get the media_player entity_id for this TV (cached after first lookup)."""
        if self._media_player_entity_id:
            return self._media_player_entity_id

        entity_registry = er.async_get(self.hass)
        for entity in entity_registry.entities.values():
            if (
                entity.config_entry_id == self._entry.entry_id
                and entity.domain == "media_player"
            ):
                self._media_player_entity_id = entity.entity_id
                return entity.entity_id

        return None

    def _get_media_player_state(self):
        """Return the current HA state object of the media_player, or None."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            return None
        return self.hass.states.get(entity_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=self._device_name,
        )

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return "Power"

    @property
    def available(self) -> bool:
        """Available unless the media_player is truly unreachable."""
        state = self._get_media_player_state()
        if state is None:
            return False
        return state.state != "unavailable"

    @property
    def is_on(self) -> bool | None:
        """TV is physically on if media_player is on OR Art Mode is active.

        A Frame TV in Art Mode reports media_player state as "off", but the
        screen is physically on.  We treat that as on so that automations
        reading this switch never send a spurious turn_on to an already-lit TV.
        """
        state = self._get_media_player_state()
        if state is None:
            return None
        # Clearly on (watching TV, idle, paused...)
        if state.state not in (STATE_OFF, "unavailable", "unknown"):
            return True
        # media_player says "off" — but Art Mode may be active
        if state.state == STATE_OFF:
            return state.attributes.get("art_mode_status") == "on"
        return False

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:power" if self.is_on else "mdi:power-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the TV on — delegates to media_player.turn_on."""
        entity_id = self._get_media_player_entity_id()
        if not entity_id:
            _LOGGER.warning("Power switch: media_player entity not found for %s", self._device_name)
            return

        _LOGGER.debug("Power switch: delegating turn_on to %s", entity_id)
        await self.hass.services.async_call(
            "media_player",
            "turn_on",
            {"entity_id": entity_id},
            blocking=True,
        )
        # State will update automatically when media_player changes
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the TV off via SmartThings Command.OFF.

        We use SmartThings directly here (not media_player.turn_off) because
        SmartThings sends a hardware-level power-off signal that works
        regardless of the TV current state — including when Art Mode is active
        and media_player reports state "off" (which would make a plain
        media_player.turn_off a no-op).
        """
        try:
            st_client = await self._get_st_client()
            if not st_client:
                _LOGGER.error("Power switch: cannot turn off — SmartThings client unavailable")
                return

            await st_client.execute_device_command(
                self._device_id,
                Capability.SWITCH,
                Command.OFF,
                COMPONENT_MAIN,
            )
            self._attr_is_on = False
            self.async_write_ha_state()
            _LOGGER.debug("Power switch: TV turned off via SmartThings")
        except Exception as ex:
            _LOGGER.error("Power switch: error turning off TV: %s", ex)

    @callback
    def _handle_media_player_state_change(self, event) -> None:
        """React to media_player state changes and push update immediately."""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Subscribe to media_player state changes when added to HA."""
        entity_id = self._get_media_player_entity_id()
        if entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [entity_id],
                    self._handle_media_player_state_change,
                )
            )
