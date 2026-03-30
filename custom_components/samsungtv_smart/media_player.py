"""Support for interface with an Samsung TV."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
import logging
import os
from socket import error as socketError
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from aiohttp import ClientConnectionError, ClientResponseError, ClientSession
import async_timeout
import voluptuous as vol
from wakeonlan import send_magic_packet
from websocket import WebSocketTimeoutException

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_ENQUEUE,
    MediaPlayerDeviceClass,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.browse_media import (
    async_process_play_media_url,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_API_KEY,
    CONF_BROADCAST_ADDRESS,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_PORT,
    CONF_SERVICE,
    CONF_SERVICE_DATA,
    CONF_TIMEOUT,
    CONF_TOKEN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import DOMAIN as HA_DOMAIN, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform, config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.service import CONF_SERVICE_ENTITY_ID, async_call_from_config
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.util import Throttle, dt as dt_util
from homeassistant.util.async_ import run_callback_threadsafe

from . import get_smartthings_api_key, async_get_samsungtv_api_key, get_oauth_refresh_lock, is_oauth_refresh_in_progress, set_oauth_refresh_in_progress
from .api.samsungcast import SamsungCastTube
from .api.samsungws import ArtModeStatus, SamsungTVAsyncRest, SamsungTVWS
from .api.smartthings import SmartThingsTV, STStatus
from .api.upnp import SamsungUPnP
from .api.art import SamsungTVAsyncArt
from .const import (
    ATTR_BRIGHTNESS,
    ATTR_CATEGORY_ID,
    ATTR_CONTENT_ID,
    ATTR_DURATION,
    ATTR_ENABLED,
    ATTR_FILE_PATH,
    ATTR_FILE_TYPE,
    ATTR_FILTER_ID,
    ATTR_MATTE_ID,
    ATTR_SHOW,
    ATTR_SHUFFLE,
    ATTR_STATUS,
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_PAT,
    AUTH_METHOD_ST_ENTRY,
    CONF_APP_LAUNCH_METHOD,
    CONF_APP_LIST,
    CONF_APP_LOAD_METHOD,
    CONF_AUTH_METHOD,
    CONF_CHANNEL_LIST,
    CONF_DUMP_APPS,
    CONF_EXT_POWER_ENTITY,
    CONF_LOGO_OPTION,
    CONF_OAUTH_TOKEN,
    CONF_PING_PORT,
    CONF_POWER_ON_METHOD,
    CONF_SHOW_CHANNEL_NR,
    CONF_SOURCE_LIST,
    CONF_ST_ENTRY_UNIQUE_ID,
    CONF_SYNC_TURN_OFF,
    CONF_SYNC_TURN_ON,
    CONF_TOGGLE_ART_MODE,
    CONF_USE_LOCAL_LOGO,
    CONF_USE_MUTE_CHECK,
    CONF_USE_ST_CHANNEL_INFO,
    CONF_USE_ST_STATUS_INFO,
    CONF_WOL_REPEAT,
    CONF_WS_NAME,
    DATA_ART_API,
    DATA_CFG,
    DATA_OPTIONS,
    DEFAULT_APP,
    DEFAULT_PORT,
    DEFAULT_SOURCE_LIST,
    DEFAULT_TIMEOUT,
    DOMAIN,
    LOCAL_LOGO_PATH,
    MAX_WOL_REPEAT,
    SERVICE_ART_AVAILABLE,
    SERVICE_ART_CHANGE_MATTE,
    SERVICE_ART_DELETE,
    SERVICE_ART_GET_ARTMODE,
    SERVICE_ART_GET_BRIGHTNESS,
    SERVICE_ART_GET_CURRENT,
    SERVICE_ART_GET_MATTE_LIST,
    SERVICE_ART_GET_PHOTO_FILTER_LIST,
    SERVICE_ART_GET_THUMBNAIL,
    SERVICE_ART_GET_THUMBNAILS_BATCH,
    SERVICE_ART_SELECT_IMAGE,
    SERVICE_ART_SET_ARTMODE,
    SERVICE_ART_SET_AUTO_ROTATION,
    SERVICE_ART_SET_BRIGHTNESS,
    SERVICE_ART_SET_FAVOURITE,
    SERVICE_ART_SET_PHOTO_FILTER,
    SERVICE_ART_SET_SLIDESHOW,
    SERVICE_ART_UPLOAD,
    SERVICE_SELECT_PICTURE_MODE,
    SIGNAL_CONFIG_ENTITY,
    STD_APP_LIST,
    WS_PREFIX,
    AppLaunchMethod,
    AppLoadMethod,
    PowerOnMethod,
)
from .entity import SamsungTVEntity
from .logo import LOGO_OPTION_DEFAULT, LocalImageUrl, Logo, LogoOption

ATTR_ART_MODE_STATUS = "art_mode_status"
ATTR_IP_ADDRESS = "ip_address"
ATTR_PICTURE_MODE = "picture_mode"
ATTR_PICTURE_MODE_LIST = "picture_mode_list"

CMD_OPEN_BROWSER = "open_browser"
CMD_RUN_APP = "run_app"
CMD_RUN_APP_REMOTE = "run_app_remote"
CMD_RUN_APP_REST = "run_app_rest"
CMD_SEND_KEY = "send_key"
CMD_SEND_TEXT = "send_text"

DELAYED_SOURCE_TIMEOUT = 80
KEYHOLD_MAX_DELAY = 5.0
KEYPRESS_DEFAULT_DELAY = 0.5
KEYPRESS_MAX_DELAY = 2.0
KEYPRESS_MIN_DELAY = 0.2
MAX_ST_ERROR_COUNT = 4
MEDIA_TYPE_BROWSER = "browser"
MEDIA_TYPE_KEY = "send_key"
MEDIA_TYPE_TEXT = "send_text"
POWER_OFF_DELAY = 20
ST_APP_SEPARATOR = "/"
ST_UPDATE_TIMEOUT = 5

YT_APP_IDS = ("111299001912", "9Ur5IzDKqV.TizenYouTube")
YT_VIDEO_QS = "v"
YT_SVIDEO = "/shorts/"

MAX_CONTROLLED_ENTITY = 4

SUPPORT_SAMSUNGTV_SMART = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.STOP
)

MIN_TIME_BETWEEN_ST_UPDATE = timedelta(seconds=5)
ST_API_KEY_UPDATE_INTERVAL = timedelta(minutes=30)
OAUTH_TOKEN_REFRESH_BUFFER = 300  # Refresh OAuth token 5 minutes before expiration
SCAN_INTERVAL = timedelta(seconds=15)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the Samsung TV from a config entry."""

    # session used by aiohttp
    session = async_get_clientsession(hass)
    local_logo_path = hass.data[DOMAIN].get(LOCAL_LOGO_PATH)
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]

    logo_file = hass.config.path(STORAGE_DIR, f"{DOMAIN}_logo_paths")

    def update_token_func(token: str, token_key: str) -> None:
        """Update config entry with the new token."""
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, token_key: token}
        )

    async_add_entities(
        [
            SamsungTVDevice(
                config,
                entry.entry_id,
                hass.data[DOMAIN][entry.entry_id],
                session,
                update_token_func,
                logo_file,
                local_logo_path,
            )
        ],
        True,
    )

    # register services
    platform = entity_platform.current_platform.get()
    platform.async_register_entity_service(
        SERVICE_SELECT_PICTURE_MODE,
        {vol.Required(ATTR_PICTURE_MODE): cv.string},
        "async_select_picture_mode",
    )

    # Frame Art Extended Services
    platform.async_register_entity_service(
        SERVICE_ART_GET_ARTMODE,
        {},
        "async_art_get_artmode",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SET_ARTMODE,
        {vol.Required(ATTR_ENABLED): cv.boolean},
        "async_art_set_artmode",
    )
    platform.async_register_entity_service(
        SERVICE_ART_AVAILABLE,
        {vol.Optional(ATTR_CATEGORY_ID): cv.string},
        "async_art_available",
    )
    platform.async_register_entity_service(
        SERVICE_ART_GET_CURRENT,
        {},
        "async_art_get_current",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SELECT_IMAGE,
        {
            vol.Required(ATTR_CONTENT_ID): cv.string,
            vol.Optional(ATTR_CATEGORY_ID): cv.string,
            vol.Optional(ATTR_SHOW, default=True): cv.boolean,
        },
        "async_art_select_image",
    )
    platform.async_register_entity_service(
        SERVICE_ART_UPLOAD,
        {
            vol.Required(ATTR_FILE_PATH): cv.string,
            vol.Optional(ATTR_MATTE_ID, default="shadowbox_polar"): cv.string,
            vol.Optional(ATTR_FILE_TYPE, default="jpg"): cv.string,
        },
        "async_art_upload",
    )
    platform.async_register_entity_service(
        SERVICE_ART_DELETE,
        {vol.Required(ATTR_CONTENT_ID): cv.string},
        "async_art_delete",
    )
    platform.async_register_entity_service(
        SERVICE_ART_GET_THUMBNAIL,
        {vol.Required(ATTR_CONTENT_ID): cv.string},
        "async_art_get_thumbnail",
    )
    platform.async_register_entity_service(
        SERVICE_ART_GET_THUMBNAILS_BATCH,
        {
            vol.Optional(ATTR_CATEGORY_ID): cv.string,
            vol.Optional("favorites_only", default=False): cv.boolean,
            vol.Optional("personal_only", default=False): cv.boolean,
            vol.Optional("force_download", default=False): cv.boolean,
            vol.Optional("cleanup_orphans", default=False): cv.boolean,
        },
        "async_art_get_thumbnails_batch",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SET_BRIGHTNESS,
        {vol.Required(ATTR_BRIGHTNESS): vol.All(vol.Coerce(int), vol.Range(0, 100))},
        "async_art_set_brightness",
    )
    platform.async_register_entity_service(
        SERVICE_ART_GET_BRIGHTNESS,
        {},
        "async_art_get_brightness",
    )
    platform.async_register_entity_service(
        SERVICE_ART_CHANGE_MATTE,
        {
            vol.Required(ATTR_CONTENT_ID): cv.string,
            vol.Required(ATTR_MATTE_ID): cv.string,
        },
        "async_art_change_matte",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SET_PHOTO_FILTER,
        {
            vol.Required(ATTR_CONTENT_ID): cv.string,
            vol.Required(ATTR_FILTER_ID): cv.string,
        },
        "async_art_set_photo_filter",
    )
    platform.async_register_entity_service(
        SERVICE_ART_GET_PHOTO_FILTER_LIST,
        {},
        "async_art_get_photo_filter_list",
    )
    platform.async_register_entity_service(
        SERVICE_ART_GET_MATTE_LIST,
        {},
        "async_art_get_matte_list",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SET_FAVOURITE,
        {
            vol.Required(ATTR_CONTENT_ID): cv.string,
            vol.Optional(ATTR_STATUS, default="on"): cv.string,
        },
        "async_art_set_favourite",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SET_SLIDESHOW,
        {
            vol.Required(ATTR_DURATION): vol.In(["3min", "15min", "1h", "12h", "1d", "7d"]),
            vol.Optional(ATTR_SHUFFLE, default=True): cv.boolean,
            vol.Optional(ATTR_CATEGORY_ID, default=2): vol.All(vol.Coerce(int), vol.Range(2, 8)),
        },
        "async_art_set_slideshow",
    )
    platform.async_register_entity_service(
        SERVICE_ART_SET_AUTO_ROTATION,
        {
            vol.Required(ATTR_DURATION): vol.In(["3min", "15min", "1h", "12h", "1d", "7d"]),
            vol.Optional(ATTR_SHUFFLE, default=True): cv.boolean,
            vol.Optional(ATTR_CATEGORY_ID, default=2): vol.All(vol.Coerce(int), vol.Range(2, 8)),
        },
        "async_art_set_auto_rotation",
    )


def _get_default_app_info(app_id):
    """Get information for default app."""
    if not app_id:
        return None, None, None

    if app_id in STD_APP_LIST:
        info = STD_APP_LIST[app_id]
        return app_id, info.get("st_app_id"), info.get("logo")

    for info in STD_APP_LIST.values():
        st_app_id = info.get("st_app_id", "")
        if st_app_id == app_id:
            return app_id, None, info.get("logo")
    return None, None, None


class ArtModeSupport(Enum):
    """Define ArtMode support lever."""

    UNSUPPORTED = 0
    PARTIAL = 1
    FULL = 2


class SamsungTVDevice(SamsungTVEntity, MediaPlayerEntity):
    """Representation of a Samsung TV."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_name = None

    def __init__(
        self,
        config: dict[str, Any],
        entry_id: str,
        entry_data: dict[str, Any] | None,
        session: ClientSession,
        update_token_func: Callable[[str, str], None],
        logo_file: str,
        local_logo_path: str | None,
    ) -> None:
        """Initialize the Samsung device."""

        super().__init__(config, entry_id)

        self._entry_data = entry_data
        self._entry_id = entry_id
        self._update_token_func = update_token_func
        self._host = config[CONF_HOST]

        # Set entity attributes
        self._attr_media_title = None
        self._attr_media_image_url = None
        self._attr_media_image_remotely_accessible = False

        # Assume that the TV is not muted and volume is 0
        self._attr_is_volume_muted = False
        self._attr_volume_level = 0.0

        # Device information from TV
        self._device_info: dict[str, Any] | None = None

        # Save a reference to the imported config
        self._broadcast = config.get(CONF_BROADCAST_ADDRESS)

        # Assume that the TV is in Play mode and state is off
        self._playing = True
        self._state = MediaPlayerState.OFF

        # Mark the end of a shutdown command (need to wait 15 seconds before
        # sending the next command to avoid turning the TV back ON).
        self._started_up = False
        self._end_of_power_off = None
        self._fake_on = None
        self._delayed_set_source = None
        self._delayed_set_source_time = None

        # generic for sources and apps
        self._source = None
        self._running_app = None
        self._yt_app_id = None

        # prepare TV lists options
        self._default_source_used = False
        self._source_list = None
        self._dump_apps = True
        self._app_list = None
        self._app_list_st = None
        self._channel_list = None

        # config options reloaded on change
        self._use_st_status: bool = True
        self._use_channel_info: bool = True
        self._use_mute_check: bool = False
        self._show_channel_number: bool = False

        # ws initialization
        ws_name = config.get(CONF_WS_NAME, self._name)
        self._ws = SamsungTVWS(
            host=self._host,
            token=config.get(CONF_TOKEN),
            port=config.get(CONF_PORT, DEFAULT_PORT),
            timeout=config.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
            key_press_delay=KEYPRESS_DEFAULT_DELAY,
            name=f"{WS_PREFIX} {ws_name}",  # this is the name shown in the TV external device.
        )

        def new_token_callback():
            """Update config entry with the new token."""
            run_callback_threadsafe(
                self.hass.loop, update_token_func, self._ws.token, CONF_TOKEN
            )

        self._ws.register_new_token_callback(new_token_callback)

        # rest api initialization
        self._rest_api = SamsungTVAsyncRest(
            host=self._host,
            session=session,
            timeout=DEFAULT_TIMEOUT,
        )

        # Frame Art API - use shared instance if available, otherwise create new one
        shared_art_api = entry_data.get(DATA_ART_API) if entry_data else None
        if shared_art_api:
            self._art_api = shared_art_api
            _LOGGER.debug("Using shared Frame Art API instance")
        else:
            self._art_api = SamsungTVAsyncArt(
                host=self._host,
                port=config.get(CONF_PORT, DEFAULT_PORT),
                token=config.get(CONF_TOKEN),
                session=session,
                timeout=DEFAULT_TIMEOUT,
                name=f"{WS_PREFIX} {ws_name} Art",
            )
        self._frame_tv_supported: bool | None = None
        self._frame_art_last_result: dict | None = None

        # upnp initialization
        self._upnp = SamsungUPnP(host=self._host, session=session)

        # smartthings initialization
        st_entry_uniqueid: str | None = config.get(CONF_ST_ENTRY_UNIQUE_ID)
        auth_method: str | None = config.get(CONF_AUTH_METHOD)
        
        # Store auth method for later use
        self._auth_method = auth_method

        def api_key_callback() -> str | None:
            """Get current api key - for OAuth, read from entry data after refresh."""
            if self._auth_method == AUTH_METHOD_OAUTH:
                # For OAuth, always read from entry data to get refreshed token
                entry = self.hass.config_entries.async_get_entry(self._entry_id)
                if entry:
                    oauth_token = entry.data.get(CONF_OAUTH_TOKEN)
                    if oauth_token and isinstance(oauth_token, dict):
                        new_token = oauth_token.get("access_token")
                        if new_token and new_token != self._st_api_key:
                            _LOGGER.debug("OAuth token updated from entry data")
                            self._st_api_key = new_token
                            return new_token
                return self._st_api_key
            return self._update_smartthing_token(st_entry_uniqueid, update_token_func)

        self._st = None
        self._st_api_key = config.get(CONF_API_KEY)
        device_id = config.get(CONF_DEVICE_ID)
        
        # For OAuth method, get token from oauth_token if api_key is not set
        if auth_method == AUTH_METHOD_OAUTH and not self._st_api_key:
            oauth_token = config.get(CONF_OAUTH_TOKEN)
            if oauth_token and isinstance(oauth_token, dict):
                self._st_api_key = oauth_token.get("access_token")
                _LOGGER.debug("Using OAuth access token for SmartThings API")
        
        if self._st_api_key and device_id:
            # Use callback for both ST_ENTRY and OAuth methods
            use_callbck: bool = (
                (auth_method == AUTH_METHOD_ST_ENTRY and st_entry_uniqueid is not None)
                or auth_method == AUTH_METHOD_OAUTH
            )
            self._st = SmartThingsTV(
                api_key=self._st_api_key,
                device_id=device_id,
                use_channel_info=True,
                session=session,
                api_key_callback=api_key_callback if use_callbck else None,
            )

        self._st_error_count = 0
        self._st_last_exc = None
        self._setvolumebyst = False

        # logo control initializzation
        self._local_image_url = LocalImageUrl(local_logo_path)
        self._logo_option = LOGO_OPTION_DEFAULT
        self._logo = Logo(
            logo_option=self._logo_option,
            logo_file_download=logo_file,
            session=session,
        )

        # YouTube cast
        self._cast_api = SamsungCastTube(self._host)

        # update config options for first time
        self._update_config_options(True)

    @Throttle(ST_API_KEY_UPDATE_INTERVAL)
    @callback
    def _update_smartthing_token(
        self, st_unique_id: str, update_token_func: Callable[[str, str], None]
    ) -> str | None:
        """Update the smartthing token when change on native integration.
        
        Note: For OAuth method, this function should not be called as the token
        is managed by Home Assistant's OAuth flow. The callback is disabled for OAuth.
        """
        # For OAuth, token refresh is handled elsewhere
        if self._auth_method == AUTH_METHOD_OAUTH:
            _LOGGER.debug("OAuth token refresh handled by HA OAuth flow")
            return self._st_api_key
            
        _LOGGER.debug("Trying to update smartthing access token")
        if not (new_token := get_smartthings_api_key(self.hass, st_unique_id)):
            _LOGGER.warning(
                "Failed to retrieve SmartThings integration access token,"
                " using last available"
            )
            return self._st_api_key

        if new_token != self._st_api_key:
            _LOGGER.info("SmartThings access token updated")
            update_token_func(new_token, CONF_API_KEY)
            self._st_api_key = new_token

        return self._st_api_key

    async def _async_refresh_oauth_token(self) -> bool:
        """Refresh OAuth token if needed.
        
        Returns True if token was refreshed or is still valid, False on error.
        """
        if self._auth_method != AUTH_METHOD_OAUTH:
            return True
        
        # Check if another refresh is already in progress (global check)
        if is_oauth_refresh_in_progress(self._entry_id):
            _LOGGER.debug("OAuth refresh already in progress (global), waiting for result")
            # Wait a bit and then check if token was refreshed
            await asyncio.sleep(0.5)
            # Re-read token from entry
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry:
                oauth_token = entry.data.get(CONF_OAUTH_TOKEN, {})
                new_token = oauth_token.get("access_token")
                if new_token and new_token != self._st_api_key:
                    self._st_api_key = new_token
                    if self._st:
                        self._st._api_key = new_token
                        self._st._st.authenticate(new_token)
                    return True
            return False
        
        # Acquire global lock
        lock = get_oauth_refresh_lock(self._entry_id)
        async with lock:
            # Double-check after acquiring lock - another entity might have refreshed
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry:
                oauth_token = entry.data.get(CONF_OAUTH_TOKEN, {})
                expires_at = oauth_token.get("expires_at", 0)
                if expires_at > time.time() + OAUTH_TOKEN_REFRESH_BUFFER:
                    # Token was refreshed by another entity
                    new_token = oauth_token.get("access_token")
                    if new_token and new_token != self._st_api_key:
                        _LOGGER.debug("Token was refreshed by another entity, using new token")
                        self._st_api_key = new_token
                        if self._st:
                            self._st._api_key = new_token
                            self._st._st.authenticate(new_token)
                    return True
            
            set_oauth_refresh_in_progress(self._entry_id, True)
            try:
                return await self._do_oauth_refresh()
            finally:
                set_oauth_refresh_in_progress(self._entry_id, False)
    
    async def _do_oauth_refresh(self) -> bool:
        """Perform the actual OAuth token refresh."""
        # Get current entry to check token expiration
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if not entry:
            _LOGGER.warning("Could not find config entry for OAuth refresh")
            return False
            
        oauth_token = entry.data.get(CONF_OAUTH_TOKEN)
        if not oauth_token or not isinstance(oauth_token, dict):
            _LOGGER.warning("No OAuth token found in config entry")
            return False
        
        # Check if refresh_token exists
        if "refresh_token" not in oauth_token:
            _LOGGER.warning(
                "OAuth token does not contain refresh_token - token cannot be refreshed. "
                "Please reconfigure the integration with OAuth."
            )
            return False
            
        expires_at = oauth_token.get("expires_at", 0)
        current_time = time.time()
        
        # Check if token needs refresh (within buffer period before expiration)
        if expires_at and current_time < (expires_at - OAUTH_TOKEN_REFRESH_BUFFER):
            # Token still valid, no refresh needed
            return True
        
        # Token is expiring or expired
        time_until_expiry = expires_at - current_time if expires_at else 0
        _LOGGER.warning(
            "OAuth token %s (expires in %.0f seconds), attempting refresh",
            "expired" if time_until_expiry <= 0 else "expiring soon",
            time_until_expiry
        )
        
        try:
            # Try to get implementation from entry
            implementation = None
            try:
                implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
                    self.hass, entry
                )
            except Exception as ex:
                _LOGGER.debug("Could not get implementation from entry: %s", ex)
            
            # If not found, try to get it directly from available implementations
            if not implementation:
                _LOGGER.debug("Attempting to get OAuth implementation directly")
                try:
                    implementations = await config_entry_oauth2_flow.async_get_implementations(
                        self.hass, DOMAIN
                    )
                    if implementations:
                        # Use the first available implementation
                        implementation = list(implementations.values())[0]
                        _LOGGER.debug("Found OAuth implementation: %s", type(implementation).__name__)
                except Exception as impl_ex:
                    _LOGGER.debug("Could not get implementations: %s", impl_ex)
            
            if not implementation:
                _LOGGER.error(
                    "Could not get OAuth implementation - Application Credentials may be missing. "
                    "Go to Settings > Devices & Services > Application Credentials "
                    "and add credentials for Samsung TV Smart, then reconfigure the integration."
                )
                return False
                
            new_token = await implementation.async_refresh_token(oauth_token)
            
            # Update config entry with new token and auth_implementation
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_OAUTH_TOKEN: new_token,
                    CONF_API_KEY: new_token["access_token"],
                    "auth_implementation": DOMAIN,
                },
            )
            
            # Update local api key
            self._st_api_key = new_token["access_token"]
            
            # Update SmartThingsTV directly (callback is disabled for OAuth)
            if self._st:
                self._st._api_key = self._st_api_key
                self._st._st.authenticate(self._st_api_key)
                _LOGGER.debug("Updated SmartThingsTV with new OAuth token")
                
            _LOGGER.info("OAuth token refreshed successfully, new expiration in %.0f seconds", 
                        new_token.get("expires_at", 0) - time.time())
            return True
            
        except Exception as ex:
            _LOGGER.error(
                "Failed to refresh OAuth token: %s. "
                "You may need to reconfigure the integration with OAuth.",
                ex
            )
            return False

    async def async_added_to_hass(self):
        """Set config parameter when add to hass."""
        await super().async_added_to_hass()

        # this will update config options when changed
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONFIG_ENTITY, self._update_config_options
            )
        )

        def update_status_callback():
            """Update current TV status."""
            run_callback_threadsafe(self.hass.loop, self._status_changed_callback)

        self._ws.register_status_callback(update_status_callback)
        await self.hass.async_add_executor_job(self._ws.start_poll)
        
        # Load SmartThings sources if configured
        if self._st:
            self._get_st_sources()

    async def async_will_remove_from_hass(self):
        """Run when entity will be removed from hass."""
        self._ws.unregister_status_callback()
        await self.hass.async_add_executor_job(self._ws.stop_poll)

    @staticmethod
    def _split_app_list(app_list: dict[str, str]) -> list[dict[str, str]]:
        """Split the application list for standard and SmartThings."""
        apps = {}
        apps_st = {}

        for app_name, app_ids in app_list.items():
            try:
                app_id_split = app_ids.split(ST_APP_SEPARATOR, 1)
            except (ValueError, AttributeError):
                _LOGGER.warning(
                    "Invalid ID [%s] for App [%s] will be ignored."
                    " Use integration options to correct the App ID",
                    app_ids,
                    app_name,
                )
                continue

            app_id = app_id_split[0]
            if len(app_id_split) == 1:
                _, st_app_id, _ = _get_default_app_info(app_id)
            else:
                st_app_id = app_id_split[1]

            apps[app_name] = app_id
            apps_st[app_name] = st_app_id or app_id

        return [apps, apps_st]

    def _load_tv_lists(self, first_load=False):
        """Load TV sources, apps and channels."""

        # load sources list
        default_source_used = False
        source_list = self._get_option(CONF_SOURCE_LIST, {})
        if not source_list:
            source_list = DEFAULT_SOURCE_LIST
            default_source_used = True
        self._source_list = source_list
        self._default_source_used = default_source_used

        # load apps list
        app_list = self._get_option(CONF_APP_LIST, {})
        if app_list:
            double_list = self._split_app_list(app_list)
            self._app_list = double_list[0]
            self._app_list_st = double_list[1]
        else:
            self._app_list = None if first_load else {}
            self._app_list_st = None if first_load else {}

        # load channels list
        self._channel_list = self._get_option(CONF_CHANNEL_LIST, {})

    @callback
    def _update_config_options(self, first_load=False):
        """Update config options."""
        self._load_tv_lists(first_load)
        self._use_st_status = self._get_option(CONF_USE_ST_STATUS_INFO, True)
        self._use_channel_info = self._get_option(CONF_USE_ST_CHANNEL_INFO, True)
        self._use_mute_check = self._get_option(CONF_USE_MUTE_CHECK, False)
        self._show_channel_number = self._get_option(CONF_SHOW_CHANNEL_NR, False)
        self._ws.update_app_list(self._app_list)
        self._ws.set_ping_port(self._get_option(CONF_PING_PORT, 0))

    @callback
    def _status_changed_callback(self):
        """Called when status changed."""
        _LOGGER.debug("status_changed_callback called")
        self.async_schedule_update_ha_state(True)

    def _get_option(self, param, default=None):
        """Get option from entity configuration."""
        if not self._entry_data:
            return default
        option = self._entry_data[DATA_OPTIONS].get(param)
        return default if option is None else option

    def _get_device_spec(self, key: str) -> Any | None:
        """Check if a flag exists in latest device info."""
        if not ((info := self._device_info) and (device := info.get("device"))):
            return None
        return device.get(key)

    def _power_off_in_progress(self):
        """Check if a power off request is in progress."""
        return (
            self._end_of_power_off is not None
            and self._end_of_power_off > dt_util.utcnow()
        )

    async def _update_volume_info(self):
        """Update the volume info."""
        if self._state == MediaPlayerState.ON:
            # if self._st and self._setvolumebyst:
            #     self._attr_volume_level = self._st.volume
            #     self._attr_is_volume_muted = self._st.muted
            #     return

            if (volume := await self._upnp.async_get_volume()) is not None:
                self._attr_volume_level = int(volume) / 100
            else:
                self._attr_volume_level = None
            self._attr_is_volume_muted = await self._upnp.async_get_mute()

    def _get_external_entity_status(self):
        """Get status from external binary sensor."""
        if not (ext_entity := self._get_option(CONF_EXT_POWER_ENTITY)):
            return True
        return not self.hass.states.is_state(ext_entity, STATE_OFF)

    async def _check_status(self):
        """Check TV status with WS and others method to check power status."""

        if self._get_device_spec("PowerState") is not None:
            _LOGGER.debug("Checking if TV %s is on using device info", self._host)
            # Ensure we get an updated value
            info = await self._async_load_device_info(force=True)
            return info is not None and info["device"]["PowerState"] == "on"

        result = self._ws.is_connected
        if result and self._st:
            if (
                self._st.state == STStatus.STATE_OFF
                and self._st.prev_state != STStatus.STATE_OFF
                and self._state == MediaPlayerState.ON
                and self._use_st_status
            ):
                result = False

        if result:
            result = self._get_external_entity_status()

        if result:
            if self._ws.artmode_status in (ArtModeStatus.On, ArtModeStatus.Unavailable):
                result = False

        return result

    @callback
    def _get_running_app(self):
        """Retrieve name of running apps."""

        st_running_app = None
        if self._app_list is not None:
            for app, app_id in self._app_list.items():
                if app_running := self._ws.is_app_running(app_id):
                    self._running_app = app
                    return
                if app_running is False:
                    continue
                if self._st and self._st.channel_name != "":
                    st_app_id = self._app_list_st.get(app, "")
                    if st_app_id == self._st.channel_name:
                        st_running_app = app

        self._running_app = st_running_app or DEFAULT_APP

    def _get_st_sources(self):
        """Get sources from SmartThings."""
        if not self._st:
            _LOGGER.debug(
                "SmartThings not configured, _get_st_sources not executed"
            )
            return

        st_source_list = {}
        source_list = self._st.source_list
        if source_list:

            def get_next_name(index):
                if index >= len(source_list):
                    return ""
                next_input = source_list[index]
                if not (
                    next_input.upper() in ["DIGITALTV", "TV"]
                    or next_input.startswith("HDMI")
                ):
                    return next_input
                return ""

            for i, _ in enumerate(source_list):
                try:
                    # SmartThings source list is an array that may contain the input
                    # or the assigned name, if we found a name that is not an input
                    # we use it as input name
                    input_name = source_list[i]
                    is_tv = input_name.upper() in ["DIGITALTV", "TV"]
                    is_hdmi = input_name.startswith("HDMI")
                    if is_tv or is_hdmi:
                        input_type = "ST_TV" if is_tv else "ST_" + input_name
                        if input_type in st_source_list.values():
                            continue

                        name = self._st.get_source_name(input_name)
                        if not name:
                            name = get_next_name(i + 1)
                        st_source_list[name or input_name] = input_type

                except Exception:  # pylint: disable=broad-except
                    pass

        if len(st_source_list) > 0:
            _LOGGER.info(
                "Samsung TV: loaded sources list from SmartThings: %s",
                str(st_source_list),
            )
            self._source_list = st_source_list
            self._default_source_used = False

    def _gen_installed_app_list(self):
        """Get apps installed on TV."""

        if self._dump_apps:
            self._dump_apps = self._get_option(CONF_DUMP_APPS, False)

        if not (self._app_list is None or self._dump_apps):
            return

        app_list = self._ws.installed_app
        if not app_list:
            return

        app_load_method = AppLoadMethod(
            self._get_option(CONF_APP_LOAD_METHOD, AppLoadMethod.All.value)
        )

        # app_list is a list of dict
        filtered_app_list = {}
        filtered_app_list_st = {}
        dump_app_list = {}
        for app in app_list.values():
            try:
                app_name = app.app_name
                app_id = app.app_id
                def_app_id, st_app_id, _ = _get_default_app_info(app_id)
                # app_list is automatically created only with apps in hard coded short
                # list (STD_APP_LIST). Other available apps are dumped in a file that
                # can be used to create a custom list.
                # This is to avoid unuseful long list that can impact performance
                if app_load_method != AppLoadMethod.NotLoad:
                    if def_app_id or app_load_method == AppLoadMethod.All:
                        filtered_app_list[app_name] = app_id
                        filtered_app_list_st[app_name] = st_app_id or app_id

                dump_app_list[app_name] = (
                    app_id + ST_APP_SEPARATOR + st_app_id if st_app_id else app_id
                )

            except Exception:  # pylint: disable=broad-except
                pass

        if self._app_list is None:
            self._app_list = filtered_app_list
            self._app_list_st = filtered_app_list_st

        if self._dump_apps:
            _LOGGER.info(
                "List of available apps for SamsungTV %s: %s",
                self._host,
                dump_app_list,
            )
            self._dump_apps = False

    def _get_source(self):
        """Return the current input source."""
        if self.state != MediaPlayerState.ON:
            self._source = None
            return self._source

        use_st: bool = self._st is not None and self._st.state == STStatus.STATE_ON
        if self._running_app != DEFAULT_APP or not use_st:
            self._source = self._running_app
            return self._source

        if self._st.source in ["digitalTv", "TV"]:
            cloud_key = "ST_TV"
        elif self._st.source:
            cloud_key = "ST_" + self._st.source
        else:
            cloud_key = None

        found_source = self._running_app
        for attr, value in self._source_list.items():
            if value == cloud_key:
                found_source = attr
                break

        self._source = found_source
        return self._source

    async def _smartthings_keys(self, source_key: str):
        """Manage the SmartThings key commands."""
        if not self._st:
            _LOGGER.error(
                "SmartThings not configured. Command not valid: %s", source_key
            )
            return False
        if self._st.state != STStatus.STATE_ON:
            _LOGGER.warning(
                "SmartThings not available. Command not sent: %s", source_key
            )
            return False

        if source_key.startswith("ST_HDMI"):
            await self._st.async_select_source(source_key.replace("ST_", ""))
        elif source_key == "ST_TV":
            await self._st.async_select_source("digitalTv")
        elif source_key.startswith("ST_VD:"):
            if cmd := source_key.replace("ST_VD:", ""):
                await self._st.async_select_vd_source(cmd)
        elif source_key == "ST_CHUP":
            await self._st.async_send_command("stepchannel", "up")
        elif source_key == "ST_CHDOWN":
            await self._st.async_send_command("stepchannel", "down")
        elif source_key.startswith("ST_CH"):
            ch_num = source_key.replace("ST_CH", "")
            if ch_num.isdigit():
                await self._st.async_send_command("selectchannel", ch_num)
        elif source_key in ["ST_MUTE", "ST_UNMUTE"]:
            await self._st.async_send_command(
                "audiomute", "off" if source_key == "ST_UNMUTE" else "on"
            )
        elif source_key == "ST_VOLUP":
            await self._st.async_send_command("stepvolume", "up")
        elif source_key == "ST_VOLDOWN":
            await self._st.async_send_command("stepvolume", "down")
        elif source_key.startswith("ST_VOL"):
            vol_lev = source_key.replace("ST_VOL", "")
            if vol_lev.isdigit():
                await self._st.async_send_command("setvolume", vol_lev)
        else:
            raise ValueError(f"Unsupported SmartThings command: {source_key}")

        return True

    def _log_st_error(self, st_error: bool):
        """Log start or end problem in ST communication"""
        if self._st_error_count == 0 and not st_error:
            return

        if st_error:
            if self._st_error_count == MAX_ST_ERROR_COUNT:
                return

            self._st_error_count += 1
            if self._st_error_count == MAX_ST_ERROR_COUNT:
                msg_chk = "Check connection status with TV on the phone App"
                if self._st_last_exc is not None:
                    _LOGGER.error(
                        "%s - Error refreshing from SmartThings. %s. Error: %s",
                        self.entity_id,
                        msg_chk,
                        self._st_last_exc,
                    )
                else:
                    _LOGGER.warning(
                        "%s - SmartThings report TV is off but status detected is on. %s",
                        self.entity_id,
                        msg_chk,
                    )
            return

        if self._st_error_count >= MAX_ST_ERROR_COUNT:
            _LOGGER.warning("%s - Connection to SmartThings restored", self.entity_id)
        self._st_error_count = 0

    async def _async_load_device_info(
        self, force: bool = False
    ) -> dict[str, Any] | None:
        """Try to gather infos of this TV."""
        if self._device_info is not None and not force:
            return self._device_info

        try:
            device_info: dict[str, Any] = await self._rest_api.async_rest_device_info()
            _LOGGER.debug("Device info on %s is: %s", self._host, device_info)
            self._device_info = device_info
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.debug("Error retrieving device info on %s: %s", self._host, ex)
            return None

        return self._device_info

    @Throttle(MIN_TIME_BETWEEN_ST_UPDATE)
    async def _async_st_update(self, **kwargs) -> bool | None:
        """Update SmartThings state of device."""
        try:
            async with async_timeout.timeout(ST_UPDATE_TIMEOUT):
                await self._st.async_device_update(self._use_channel_info)
        except (
            asyncio.TimeoutError,
            ClientConnectionError,
            ClientResponseError,
        ) as exc:
            _LOGGER.debug("%s - SmartThings error: [%s]", self.entity_id, exc)
            self._st_last_exc = exc
            return False

        self._st_last_exc = None
        return True

    async def async_update(self):
        """Update state of device."""

        # Refresh OAuth token if needed (before any SmartThings API call)
        if self._auth_method == AUTH_METHOD_OAUTH:
            await self._async_refresh_oauth_token()

        # Required to get source and media title
        st_error: bool | None = None
        if self._st:
            if (st_update := await self._async_st_update()) is not None:
                st_error = not st_update

        result = await self._check_status()
        if not self._started_up or not result:
            use_mute_check = False
            self._fake_on = None
        else:
            use_mute_check = self._use_mute_check

        if use_mute_check and self._state == MediaPlayerState.OFF:
            first_detect = self._fake_on is None
            if first_detect or self._fake_on is True:
                if (is_muted := await self._upnp.async_get_mute()) is None:
                    self._fake_on = True
                else:
                    self._fake_on = is_muted
                if self._fake_on:
                    if first_detect:
                        _LOGGER.debug(
                            "%s - Detected fake power on, status not updated",
                            self.entity_id,
                        )
                    result = False

        if st_error is not None:
            if result and not st_error:
                st_error = self._st.state != STStatus.STATE_ON
            self._log_st_error(st_error)

        self._state = MediaPlayerState.ON if result else MediaPlayerState.OFF
        self._started_up = True

        # NB: We are checking properties, not attribute!
        if self.state == MediaPlayerState.ON:
            if self._delayed_set_source:
                difference = (
                    datetime.utcnow() - self._delayed_set_source_time
                ).total_seconds()
                if difference > DELAYED_SOURCE_TIMEOUT:
                    self._delayed_set_source = None
                else:
                    await self._async_select_source_delayed(self._delayed_set_source)
            await self._async_load_device_info()
            await self._update_volume_info()
            self._get_running_app()
            await self._update_media()

        if self._state == MediaPlayerState.OFF:
            self._end_of_power_off = None

    def send_command(
        self,
        payload,
        command_type=CMD_SEND_KEY,
        key_press_delay: float = 0,
        press=False,
    ):
        """Send a key to the tv and handles exceptions."""
        if key_press_delay < 0:
            key_press_delay = None  # means "default" provided with constructor

        ret_val = False
        try:
            if command_type == CMD_RUN_APP:
                ret_val = self._ws.run_app(payload)
            elif command_type == CMD_RUN_APP_REMOTE:
                app_cmd = payload.split(",")
                app_id = app_cmd[0]
                action_type = ""
                meta_tag = ""
                if len(app_cmd) > 1:
                    action_type = app_cmd[1].strip()
                if len(app_cmd) > 2:
                    meta_tag = app_cmd[2].strip()
                ret_val = self._ws.run_app(
                    app_id, action_type, meta_tag, use_remote=True
                )
            elif command_type == CMD_RUN_APP_REST:
                result = self._ws.rest_app_run(payload)
                _LOGGER.debug("Rest API result launching app %s: %s", payload, result)
                ret_val = True
            elif command_type == CMD_OPEN_BROWSER:
                ret_val = self._ws.open_browser(payload)
            elif command_type == CMD_SEND_TEXT:
                ret_val = self._ws.send_text(payload)
            elif command_type == CMD_SEND_KEY:
                hold_delay = 0
                source_keys = payload.split(",")
                key_code = source_keys[0]
                if len(source_keys) > 1:

                    def get_hold_time():
                        hold_time = source_keys[1].replace(" ", "")
                        if not hold_time:
                            return 0
                        if not hold_time.isdigit():
                            return 0
                        hold_time = int(hold_time) / 1000
                        return min(hold_time, KEYHOLD_MAX_DELAY)

                    hold_delay = get_hold_time()

                if hold_delay > 0:
                    ret_val = self._ws.hold_key(key_code, hold_delay)
                else:
                    ret_val = self._ws.send_key(
                        key_code, key_press_delay, "Press" if press else "Click"
                    )
            else:
                _LOGGER.debug("Send command: invalid command type -> %s", command_type)

        except (ConnectionResetError, AttributeError, BrokenPipeError):
            _LOGGER.debug(
                "Error in send_command() -> ConnectionResetError/AttributeError/BrokenPipeError"
            )

        except WebSocketTimeoutException:
            _LOGGER.debug(
                "Failed sending payload %s command_type %s",
                payload,
                command_type,
                exc_info=True,
            )

        except OSError:
            _LOGGER.debug("Error in send_command() -> OSError")

        return ret_val

    async def async_send_command(
        self,
        payload,
        command_type=CMD_SEND_KEY,
        key_press_delay: float = 0,
        press=False,
    ):
        """Send a key to the tv in async mode."""
        return await self.hass.async_add_executor_job(
            self.send_command, payload, command_type, key_press_delay, press
        )

    async def _update_media(self):
        """Update media and logo status."""
        logo_option_changed = False
        new_media_title = self._get_new_media_title()

        if not new_media_title:
            self._attr_media_title = None
            self._attr_media_image_url = None
            self._attr_media_image_remotely_accessible = False
            return

        new_logo_option = LogoOption(
            self._get_option(CONF_LOGO_OPTION, self._logo_option.value)
        )
        if self._logo_option != new_logo_option:
            self._logo_option = new_logo_option
            self._logo.set_logo_color(new_logo_option)
            logo_option_changed = True

        if not logo_option_changed:
            logo_option_changed = self._logo.check_requested()

        if not logo_option_changed:
            if self._attr_media_title and new_media_title == self._attr_media_title:
                return

        _LOGGER.debug(
            "New media title is: %s, old media title is: %s, running app is: %s",
            new_media_title,
            self._attr_media_title or "<none>",
            self._running_app,
        )

        remote_access = False
        if (media_image_url := await self._local_media_image(new_media_title)) is None:
            media_image_url = await self._logo.async_find_match(new_media_title)
            remote_access = media_image_url is not None

        self._attr_media_title = new_media_title
        self._attr_media_image_url = media_image_url
        self._attr_media_image_remotely_accessible = remote_access

    def _get_new_media_title(self):
        """Get the current media title."""
        if self._state != MediaPlayerState.ON:
            return None

        if self._running_app == DEFAULT_APP:
            if self._st and self._st.state != STStatus.STATE_OFF:
                if self._st.source in ["digitalTv", "TV"]:
                    if self._st.channel_name and self._st.channel_name != "":
                        if self._show_channel_number and self._st.channel and self._st.channel != "":
                            return self._st.channel_name + " (" + self._st.channel + ")"
                        return self._st.channel_name
                    if self._st.channel and self._st.channel != "":
                        return self._st.channel
                    return None

                if (run_app := self._st.channel_name) and run_app != "":
                    # the channel name holds the running app ID
                    # regardless of the self._cloud_source value
                    # if the app ID is in the configured apps but is not running_app,
                    # means that this is not the real running app / media title
                    st_apps = self._app_list_st or {}
                    if run_app not in list(st_apps.values()):
                        return self._st.channel_name

        media_title = self._get_source()
        if media_title and media_title != DEFAULT_APP:
            return media_title
        return None

    async def _local_media_image(self, media_title):
        """Get local media image if available."""
        if not self._get_option(CONF_USE_LOCAL_LOGO, True):
            return None
        app_id = media_title
        if self._running_app != DEFAULT_APP:
            if run_app_id := self._app_list.get(self._running_app):
                app_id = run_app_id

        _, _, logo_file = _get_default_app_info(app_id)
        return await self.hass.async_add_executor_job(
            self._local_image_url.get_image_url, media_title, logo_file
        )

    @property
    def supported_features(self) -> int:
        """Flag media player features that are supported."""
        features = SUPPORT_SAMSUNGTV_SMART
        if self.state == MediaPlayerState.ON:
            features |= MediaPlayerEntityFeature.BROWSE_MEDIA
        if self._st:
            features |= MediaPlayerEntityFeature.SELECT_SOUND_MODE
        return features

    @property
    def extra_state_attributes(self):
        """Return the optional state attributes."""
        data = {ATTR_IP_ADDRESS: self._host}
        if self._ws.artmode_status != ArtModeStatus.Unsupported:
            status_on = self._ws.artmode_status == ArtModeStatus.On
            data.update({ATTR_ART_MODE_STATUS: STATE_ON if status_on else STATE_OFF})
        if self._st:
            picture_mode = self._st.picture_mode
            picture_mode_list = self._st.picture_mode_list
            if picture_mode:
                data[ATTR_PICTURE_MODE] = picture_mode
            if picture_mode_list:
                data[ATTR_PICTURE_MODE_LIST] = picture_mode_list

        # Add Frame Art last result if available
        if hasattr(self, "_frame_art_last_result") and self._frame_art_last_result:
            data["frame_art_last_result"] = self._frame_art_last_result

        return data

    @property
    def media_channel(self):
        """Channel currently playing."""
        if self._state == MediaPlayerState.ON:
            if self._st:
                if self._st.source in ["digitalTv", "TV"] and self._st.channel != "":
                    return self._st.channel
        return None

    @property
    def media_content_type(self):
        """Return the content type of current playing media."""
        if self._state == MediaPlayerState.ON:
            if self._running_app == DEFAULT_APP:
                if self.media_channel:
                    return MediaType.CHANNEL
                return MediaType.VIDEO
            return MediaType.APP
        return None

    @property
    def app_id(self):
        """ID of the current running app."""
        if self._state != MediaPlayerState.ON:
            return None

        if self._app_list_st and self._running_app != DEFAULT_APP:
            if app := self._app_list_st.get(self._running_app):
                return app

        if self._st:
            if not self._st.channel and self._st.channel_name:
                return self._st.channel_name
        return DEFAULT_APP

    @property
    def state(self):
        """Return the state of the device."""

        # Warning: we assume that after a sending a power off command, the command is successful
        # so for 20 seconds (defined in POWER_OFF_DELAY) the state will be off regardless of the
        # actual state. This is to have better feedback to the command in the UI, but the logic
        # might cause other issues in the future
        if self._power_off_in_progress():
            return MediaPlayerState.OFF

        return self._state

    @property
    def source_list(self):
        """List of available input sources."""
        # try to get source list from SmartThings if a custom source list is not defined
        if self._st and self._default_source_used:
            self._get_st_sources()

        self._gen_installed_app_list()

        source_list = []
        source_list.extend(list(self._source_list))
        if self._app_list:
            source_list.extend(list(self._app_list))
        if self._channel_list:
            source_list.extend(list(self._channel_list))
        return source_list

    @property
    def channel_list(self):
        """List of available channels."""
        if not self._channel_list:
            return None
        return list(self._channel_list)

    @property
    def source(self):
        """Return the current input source."""
        return self._get_source()

    @property
    def sound_mode(self):
        """Name of the current sound mode."""
        if self._st:
            return self._st.sound_mode
        return None

    @property
    def sound_mode_list(self):
        """List of available sound modes."""
        if self._st:
            return self._st.sound_mode_list or None
        return None

    @property
    def support_art_mode(self) -> ArtModeSupport:
        """Return if art mode is supported."""
        if self._ws.artmode_status != ArtModeStatus.Unsupported:
            return ArtModeSupport.FULL
        if self._get_device_spec("FrameTVSupport") == "true":
            return ArtModeSupport.PARTIAL
        return ArtModeSupport.UNSUPPORTED

    def _send_wol_packet(self, wol_repeat=None):
        """Send a WOL packet to turn on the TV."""
        if not self._mac:
            _LOGGER.error("MAC address not configured, impossible send WOL packet")
            return False

        if not wol_repeat:
            wol_repeat = self._get_option(CONF_WOL_REPEAT, 1)
        wol_repeat = max(1, min(wol_repeat, MAX_WOL_REPEAT))
        ip_address = self._broadcast or "255.255.255.255"
        send_success = False
        for i in range(wol_repeat):
            if i > 0:
                time.sleep(0.25)
            try:
                send_magic_packet(self._mac, ip_address=ip_address)
                send_success = True
            except socketError as exc:
                _LOGGER.warning(
                    "Failed tentative n.%s to send WOL packet: %s",
                    i,
                    exc,
                )
            except (TypeError, ValueError) as exc:
                _LOGGER.error("Error sending WOL packet: %s", exc)
                return False

        return send_success

    async def _async_power_on(self, set_art_mode=False):
        """Turn the media player on."""
        cmd_power_on = "KEY_POWER"
        cmd_power_art = "KEY_POWER"
        if set_art_mode:
            if self._ws.artmode_status == ArtModeStatus.Off:
                # art mode from on
                await self.async_send_command(cmd_power_art)
                self._state = MediaPlayerState.OFF
                return True

        if self._ws.artmode_status == ArtModeStatus.On:
            if set_art_mode:
                return False
            # power on from art mode
            await self.async_send_command(cmd_power_art)
            return True

        if self.state != MediaPlayerState.OFF:
            return False

        result = True
        if not await self.async_send_command(cmd_power_on):
            turn_on_method = PowerOnMethod(
                self._get_option(CONF_POWER_ON_METHOD, PowerOnMethod.WOL.value)
            )

            if turn_on_method == PowerOnMethod.SmartThings and self._st:
                await self._st.async_turn_on()
            else:
                result = await self.hass.async_add_executor_job(self._send_wol_packet)

        if result:
            self._state = MediaPlayerState.OFF
            self._end_of_power_off = None
            self._ws.set_power_on_request(set_art_mode)

        return result

    async def _async_turn_on(self, set_art_mode=False):
        """Turn the media player on."""
        self._delayed_set_source = None
        if not await self._async_power_on(set_art_mode):
            return False
        if self._state != MediaPlayerState.OFF:
            return True

        await self._async_switch_entity(not set_art_mode)

        return True

    async def async_turn_on(self):
        """Turn the media player on."""
        await self._async_turn_on()

    async def async_set_art_mode(self):
        """Turn the media player on setting in art mode."""
        if (
            self._state == MediaPlayerState.ON
            and self.support_art_mode == ArtModeSupport.PARTIAL
        ):
            await self.async_send_command("KEY_POWER")
        elif self.support_art_mode == ArtModeSupport.FULL:
            await self._async_turn_on(True)

    def _turn_off(self):
        """Turn off media player."""
        if self._power_off_in_progress():
            return False

        cmd_power_off = "KEY_POWER"
        cmd_power_art = "KEY_POWER"
        self._ws.set_power_off_request()
        if self._state == MediaPlayerState.ON:
            if self.support_art_mode == ArtModeSupport.UNSUPPORTED:
                self.send_command(cmd_power_off)
            else:
                self.send_command(f"{cmd_power_art},3000")
        elif self._ws.artmode_status == ArtModeStatus.On:
            self.send_command(f"{cmd_power_art},3000")
        else:
            return False

        self._end_of_power_off = dt_util.utcnow() + timedelta(seconds=POWER_OFF_DELAY)

        return True

    async def async_turn_off(self):
        """Turn the media player on."""
        result = await self.hass.async_add_executor_job(self._turn_off)
        if result:
            await self._async_switch_entity(False)

    async def async_toggle(self):
        """Toggle the power on the media player."""
        if (
            self.state == MediaPlayerState.ON
            and self.support_art_mode != ArtModeSupport.UNSUPPORTED
        ):
            if self._get_option(CONF_TOGGLE_ART_MODE, False):
                await self.async_set_art_mode()
                return
        await super().async_toggle()

    async def async_volume_up(self):
        """Volume up the media player."""
        if self._state != MediaPlayerState.ON:
            return
        await self.async_send_command("KEY_VOLUP")
        if self.volume_level is not None:
            self._attr_volume_level = min(1.0, self.volume_level + 0.01)

    async def async_volume_down(self):
        """Volume down media player."""
        if self._state != MediaPlayerState.ON:
            return
        await self.async_send_command("KEY_VOLDOWN")
        if self.volume_level is not None:
            self._attr_volume_level = max(0.0, self.volume_level - 0.01)

    async def async_mute_volume(self, mute):
        """Send mute command."""
        if self._state != MediaPlayerState.ON:
            return
        if self.is_volume_muted is not None and mute == self.is_volume_muted:
            return
        await self.async_send_command("KEY_MUTE")
        if self.is_volume_muted is not None:
            self._attr_is_volume_muted = mute

    async def async_set_volume_level(self, volume):
        """Set the volume level."""
        if self._state != MediaPlayerState.ON:
            return
        if self.volume_level is None:
            return
        if self._st and self._setvolumebyst:
            await self._st.async_send_command("setvolume", int(volume * 100))
        else:
            await self._upnp.async_set_volume(int(volume * 100))
        self._attr_volume_level = volume

    def media_play_pause(self):
        """Simulate play pause media player."""
        if self._playing:
            self.media_pause()
        else:
            self.media_play()

    def media_play(self):
        """Send play command."""
        self._playing = True
        self.send_command("KEY_PLAY")

    def media_pause(self):
        """Send media pause command to media player."""
        self._playing = False
        self.send_command("KEY_PAUSE")

    def media_stop(self):
        """Send media pause command to media player."""
        self._playing = False
        self.send_command("KEY_STOP")

    def media_next_track(self):
        """Send next track command."""
        if self.media_channel:
            self.send_command("KEY_CHUP")
        else:
            self.send_command("KEY_FF")

    def media_previous_track(self):
        """Send the previous track command."""
        if self.media_channel:
            self.send_command("KEY_CHDOWN")
        else:
            self.send_command("KEY_REWIND")

    async def _async_send_keys(self, source_key):
        """Send key / chained keys."""
        prev_wait = True

        if "+" in source_key:
            all_source_keys = source_key.split("+")
            for this_key in all_source_keys:
                if this_key.isdigit():
                    prev_wait = True
                    await asyncio.sleep(
                        min(
                            max((int(this_key) / 1000), KEYPRESS_MIN_DELAY),
                            KEYPRESS_MAX_DELAY,
                        )
                    )
                else:
                    # put a default delay between key if set explicit
                    if not prev_wait:
                        await asyncio.sleep(KEYPRESS_DEFAULT_DELAY)
                    prev_wait = False
                    if this_key.startswith("ST_"):
                        await self._smartthings_keys(this_key)
                    else:
                        await self.async_send_command(this_key)

            return True

        if source_key.startswith("ST_"):
            return await self._smartthings_keys(source_key)

        return await self.async_send_command(source_key)

    async def _async_set_channel_source(self, channel_source=None):
        """Select the source for a channel."""

        if not channel_source:
            if self._running_app == DEFAULT_APP:
                return True
            _LOGGER.error("Current source invalid for channel")
            return False

        if self._source == channel_source:
            return True

        if channel_source not in self._source_list:
            _LOGGER.error("Invalid channel source: %s", channel_source)
            return False

        await self.async_select_source(channel_source)
        if self._source != channel_source:
            _LOGGER.error("Error selecting channel source: %s", channel_source)
            return False
        await asyncio.sleep(3)

        return True

    async def _async_set_channel(self, channel):
        """Set a specific channel."""

        if channel.startswith("http"):
            await self.async_play_media(MediaType.URL, channel)
            return True

        channel_cmd = channel.split("@")
        channel_no = channel_cmd[0]
        channel_source = None
        if len(channel_cmd) > 1:
            channel_source = channel_cmd[1]

        try:
            cv.positive_int(channel_no)
        except vol.Invalid:
            _LOGGER.error("Channel must be positive integer")
            return False

        if not await self._async_set_channel_source(channel_source):
            return False

        if self._st:
            return await self._smartthings_keys(f"ST_CH{channel_no}")

        def send_digit():
            for digit in channel_no:
                self.send_command("KEY_" + digit)
                time.sleep(KEYPRESS_DEFAULT_DELAY)
            self.send_command("KEY_ENTER")

        await self.hass.async_add_executor_job(send_digit)
        return True

    async def _async_launch_app(self, app_data, meta_data=None):
        """Launch app with different methods."""

        method = ""
        app_cmd = app_data.split("@")
        app_id = app_cmd[0]
        if self._app_list:
            if app_id_from_list := self._app_list.get(app_id):
                app_id = app_id_from_list
        if meta_data:
            app_id += f",,{meta_data}"
            method = CMD_RUN_APP_REMOTE
        elif len(app_cmd) > 1:
            req_method = app_cmd[1].strip()
            if req_method in (CMD_RUN_APP, CMD_RUN_APP_REMOTE, CMD_RUN_APP_REST):
                method = req_method

        if not method:
            app_launch_method = AppLaunchMethod(
                self._get_option(CONF_APP_LAUNCH_METHOD, AppLaunchMethod.Standard.value)
            )

            if app_launch_method == AppLaunchMethod.Remote:
                method = CMD_RUN_APP_REMOTE
            elif app_launch_method == AppLaunchMethod.Rest:
                method = CMD_RUN_APP_REST
            else:
                method = CMD_RUN_APP

        await self.async_send_command(app_id, method)

    def _get_youtube_app_id(self):
        """Search youtube app id used to launch video."""
        if self._yt_app_id is not None:
            return len(self._yt_app_id) > 0
        if not self._app_list:
            return False
        self._yt_app_id = ""
        for app_name, app_id in self._app_list.items():
            if app_name.casefold().find("youtube") >= 0:
                if not self._yt_app_id:
                    self._yt_app_id = app_id
            if app_id in YT_APP_IDS:
                self._yt_app_id = app_id
                break

        _LOGGER.debug("YouTube App ID: %s", self._yt_app_id or "not found")
        return len(self._yt_app_id) > 0

    def _get_youtube_video_id(self, url):
        """Try to get youtube video id from url."""
        url_parsed = urlparse(url)
        url_host = str(url_parsed.hostname).casefold()
        url_path = url_parsed.path
        if url_host.find("youtube") < 0:
            _LOGGER.debug("URL not related to Youtube")
            return None

        video_id = None
        url_query = parse_qs(url_parsed.query)
        if YT_VIDEO_QS in url_query:
            video_id = url_query[YT_VIDEO_QS][0]
        elif url_path and str(url_path).casefold().startswith(YT_SVIDEO):
            video_id = url_path[len(YT_SVIDEO) :]

        if not video_id:
            _LOGGER.warning("Youtube video ID not found in url: %s", url)
            return None

        if not self._get_youtube_app_id():
            _LOGGER.warning("Youtube app ID not available, configure in apps list")
            return None

        _LOGGER.debug("Youtube video ID: %s", video_id)
        return video_id

    def _cast_youtube_video(self, video_id: str, enqueue: MediaPlayerEnqueue):
        """
        Cast a youtube video using samsungcast library.
        This method is sync and must run in job executor.
        """
        if enqueue == MediaPlayerEnqueue.PLAY:
            self._cast_api.play_video(video_id)
        elif enqueue == MediaPlayerEnqueue.NEXT:
            self._cast_api.play_next(video_id)
        elif enqueue == MediaPlayerEnqueue.ADD:
            self._cast_api.add_to_queue(video_id)
        elif enqueue == MediaPlayerEnqueue.REPLACE:
            self._cast_api.clear_queue()
            self._cast_api.play_video(video_id)

    async def _async_play_youtube_video(
        self, video_id: str, enqueue: MediaPlayerEnqueue
    ):
        """Play a YouTube video using YouTube app."""
        run_app_id = None
        if self._running_app != DEFAULT_APP:
            run_app_id = self._app_list.get(self._running_app)

        # launch youtube app if not running
        if run_app_id != self._yt_app_id:
            await self._async_launch_app(self._yt_app_id)
            await asyncio.sleep(3)  # we wait for YouTube app to start

        await self.hass.async_add_executor_job(
            self._cast_youtube_video, video_id, enqueue
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs
    ):
        """Support running different media type command."""
        enqueue: MediaPlayerEnqueue | None = kwargs.get(ATTR_MEDIA_ENQUEUE)

        if media_source.is_media_source_id(media_id):
            media_type = MediaType.URL
            play_item = await media_source.async_resolve_media(self.hass, media_id)
            media_id = play_item.url
        else:
            media_type = media_type.lower()

        if media_type in [MEDIA_TYPE_BROWSER, MediaType.URL]:
            media_id = async_process_play_media_url(self.hass, media_id)
            try:
                cv.url(media_id)
            except vol.Invalid:
                _LOGGER.error('Media ID must be a valid url (ex: "http://"')
                return

        # Type channel
        if media_type == MediaType.CHANNEL:
            await self._async_set_channel(media_id)

        # Launch an app
        elif media_type == MediaType.APP:
            await self._async_launch_app(media_id)

        # Send custom key
        elif media_type == MEDIA_TYPE_KEY:
            try:
                cv.string(media_id)
            except vol.Invalid:
                _LOGGER.error('Media ID must be a string (ex: "KEY_HOME"')
                return

            await self._async_send_keys(media_id)

        # Open url or youtube app
        elif media_type == MediaType.URL:
            if enqueue and (video_id := self._get_youtube_video_id(media_id)):
                await self._async_play_youtube_video(video_id, enqueue)
                return

            if await self._upnp.async_set_current_media(media_id):
                self._playing = True
                return

            await self.async_send_command(media_id, CMD_OPEN_BROWSER)

        # Open url in browser
        elif media_type == MEDIA_TYPE_BROWSER:
            await self.async_send_command(media_id, CMD_OPEN_BROWSER)

        # Trying to make stream component work on TV
        elif media_type == "application/vnd.apple.mpegurl":
            if await self._upnp.async_set_current_media(media_id):
                self._playing = True

        elif media_type == MEDIA_TYPE_TEXT:
            await self.async_send_command(media_id, CMD_SEND_TEXT)

        else:
            raise NotImplementedError(f"Unsupported media type: {media_type}")

    async def async_browse_media(self, media_content_type=None, media_content_id=None):
        """Implement the websocket media browsing helper."""
        return await media_source.async_browse_media(self.hass, media_content_id)

    async def async_select_source(self, source):
        """Select input source."""
        running_app = DEFAULT_APP
        self._delayed_set_source = None

        if self.state != MediaPlayerState.ON:
            if await self._async_turn_on():
                self._delayed_set_source = source
                self._delayed_set_source_time = datetime.utcnow()
            return

        if self._source_list and source in self._source_list:
            source_key = self._source_list[source]
            if not await self._async_send_keys(source_key):
                return
        elif self._app_list and source in self._app_list:
            app_id = self._app_list[source]
            running_app = source
            await self._async_launch_app(app_id)
            if self._st:
                self._st.set_application(self._app_list_st[source])
        elif self._channel_list and source in self._channel_list:
            source_key = self._channel_list[source]
            await self._async_set_channel(source_key)
            return
        else:
            _LOGGER.error("Unsupported source")
            return

        self._running_app = running_app
        self._source = source

    async def _async_select_source_delayed(self, source):
        """Select input source with delayed ST option."""
        if self._st:
            if self._st.state != STStatus.STATE_ON:
                # wait for smartthings available
                return

        await self.async_select_source(source)

    async def async_select_sound_mode(self, sound_mode):
        """Select sound mode."""
        if not self._st:
            raise NotImplementedError()
        await self._st.async_set_sound_mode(sound_mode)

    async def async_select_picture_mode(self, picture_mode):
        """Select picture mode."""
        if not self._st:
            raise NotImplementedError()
        await self._st.async_set_picture_mode(picture_mode)

    # ==========================================
    # Frame Art Extended Service Methods
    # ==========================================

    def _store_art_result(self, result: dict) -> None:
        """Store art service result and trigger state update.
        
        Important: Remove thumbnail_base64 from stored result to prevent
        entity attributes from becoming too large.
        """
        # Create a copy without the base64 data
        stored_result = result.copy()
        if "thumbnail_base64" in stored_result:
            # Replace with size info instead of full base64
            base64_size = len(stored_result["thumbnail_base64"])
            stored_result.pop("thumbnail_base64")
            stored_result["thumbnail_base64_size"] = base64_size
            stored_result["thumbnail_note"] = "Base64 data removed to save space"
        
        self._frame_art_last_result = stored_result
        self.async_write_ha_state()

    async def _ensure_frame_tv_check(self) -> bool:
        """Check if Frame TV is supported (cached)."""
        if self._frame_tv_supported is None:
            try:
                self._frame_tv_supported = await self._art_api.supported()
            except Exception as ex:
                _LOGGER.debug("Frame TV support check failed: %s", ex)
                self._frame_tv_supported = False
        return self._frame_tv_supported

    async def async_art_get_artmode(self) -> dict:
        """Get the current Art Mode status."""
        if not await self._ensure_frame_tv_check():
            result = {"error": "Frame TV not supported"}
            self._store_art_result(result)
            return result
        try:
            status = await self._art_api.get_artmode()
            result = {"service": "art_get_artmode", "status": status}
            self._store_art_result(result)
            return result
        except Exception as ex:
            result = {"service": "art_get_artmode", "error": str(ex)}
            self._store_art_result(result)
            return result

    async def async_art_set_artmode(self, enabled: bool) -> dict:
        """Enable or disable Art Mode."""
        if not await self._ensure_frame_tv_check():
            result = {"error": "Frame TV not supported"}
            self._store_art_result(result)
            return result
        try:
            await self._art_api.set_artmode(enabled)
            result = {"service": "art_set_artmode", "success": True, "enabled": enabled}
            self._store_art_result(result)
            return result
        except Exception as ex:
            result = {"service": "art_set_artmode", "error": str(ex)}
            self._store_art_result(result)
            return result

    async def async_art_available(self, category_id: str | None = None) -> dict:
        """Get list of available artwork on the TV."""
        if not await self._ensure_frame_tv_check():
            result = {"error": "Frame TV not supported"}
            self._store_art_result(result)
            return result
        try:
            artwork_list = await self._art_api.available(category_id)
            result = {
                "service": "art_available",
                "count": len(artwork_list),
                "artwork": artwork_list
            }
            self._store_art_result(result)
            return result
        except Exception as ex:
            result = {"service": "art_available", "error": str(ex)}
            self._store_art_result(result)
            return result

    async def async_art_get_current(self) -> dict:
        """Get information about the currently displayed artwork."""
        if not await self._ensure_frame_tv_check():
            result = {"error": "Frame TV not supported"}
            self._store_art_result(result)
            return result
        try:
            current = await self._art_api.get_current()
            result = {"service": "art_get_current", "current": current}
            self._store_art_result(result)
            return result
        except Exception as ex:
            result = {"service": "art_get_current", "error": str(ex)}
            self._store_art_result(result)
            return result

    async def _ensure_art_mode_ready(self) -> bool:
        """Ensure TV is on and in Art Mode. Turn it on and activate Art Mode if needed.
        
        Uses SmartThings as fallback if WebSocket connection fails.
        
        Returns:
            bool: True if TV is ready in Art Mode, False if failed
        """
        # Check if TV is off, turn it on if needed
        if self.state == MediaPlayerState.OFF:
            _LOGGER.info("Frame Art: TV is off, turning it on first...")
            
            try:
                # Try normal WebSocket turn on first
                await self.async_turn_on()
                
                # Wait for TV to power up and be ready
                _LOGGER.debug("Frame Art: Waiting for TV to be ready...")
                await asyncio.sleep(10)  # Wait for full TV startup
                
                _LOGGER.info("Frame Art: TV should now be on")
                
            except Exception as ex:
                # WebSocket failed, try SmartThings fallback
                if "1005" in str(ex) or "saturated" in str(ex).lower() or "closed" in str(ex).lower():
                    _LOGGER.warning(
                        "Frame Art: WebSocket connection failed (TV may be in sleep mode), "
                        "trying SmartThings fallback..."
                    )
                    
                    # Try SmartThings if available
                    if self._st:
                        try:
                            await self._st.async_turn_on()
                            _LOGGER.info("Frame Art: TV turned on via SmartThings")
                            
                            # Wait longer for TV to wake from sleep mode
                            _LOGGER.debug("Frame Art: Waiting for TV to wake up...")
                            await asyncio.sleep(15)
                            
                            _LOGGER.info("Frame Art: TV should now be on (via SmartThings)")
                            
                        except Exception as st_ex:
                            _LOGGER.error("Frame Art: SmartThings fallback also failed: %s", st_ex)
                            return False
                    else:
                        _LOGGER.error("Frame Art: SmartThings not configured, cannot use fallback")
                        return False
                else:
                    _LOGGER.error("Frame Art: Failed to turn on TV: %s", ex)
                    return False
        
        # TV is now on (or was already on), check if Art Mode is active
        _LOGGER.debug("Frame Art: TV is on, checking if Art Mode is active...")
        
        try:
            # Check current Art Mode status
            async with asyncio.timeout(8):
                art_mode_status = await self._art_api.get_artmode()
            
            if art_mode_status == "on":
                _LOGGER.debug("Frame Art: Art Mode already active")
                return True
            
            # Art Mode is not active, activate it
            _LOGGER.info("Frame Art: Art Mode is OFF, activating it...")
            async with asyncio.timeout(10):
                result = await self._art_api.set_artmode(True)
            
            if result:
                _LOGGER.info("Frame Art: Art Mode successfully activated")
                # Wait a bit for Art Mode to fully activate
                await asyncio.sleep(2)
                return True
            else:
                _LOGGER.error("Frame Art: Failed to activate Art Mode")
                return False
                
        except asyncio.TimeoutError:
            _LOGGER.error("Frame Art: Timeout checking/activating Art Mode")
            return False
        except Exception as ex:
            _LOGGER.error("Frame Art: Error ensuring Art Mode: %s", ex)
            return False

    async def _force_art_coordinator_refresh(self):
        """Force immediate refresh of Frame Art coordinator after artwork changes."""
        try:
            coordinator = self.hass.data[DOMAIN][self._entry_id].get("frame_art_coordinator")
            if coordinator:
                await coordinator.async_request_refresh()
                _LOGGER.debug("Forced Frame Art coordinator refresh")
        except Exception as ex:
            _LOGGER.debug("Could not force coordinator refresh: %s", ex)

    async def async_art_select_image(
        self,
        content_id: str,
        category_id: str | None = None,
        show: bool = True,
    ) -> dict:
        """Select and display a piece of artwork."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        
        # Ensure TV is on and in Art Mode
        if not await self._ensure_art_mode_ready():
            return {"error": "Failed to turn on TV"}
        
        # Select the artwork
        try:
            await self._art_api.select_image(content_id, category_id, show)
            
            # Force immediate update 🚀
            await self._force_art_coordinator_refresh()
            
            return {"success": True, "content_id": content_id}
        except Exception as ex:
            _LOGGER.error("Error selecting artwork: %s", ex)
            return {"error": str(ex)}

    async def async_art_upload(
        self,
        file_path: str,
        matte_id: str = "shadowbox_polar",
        file_type: str = "jpg",
    ) -> dict:
        """Upload an image to the TV as artwork."""
        _LOGGER.info("Frame Art: Starting upload of %s", file_path)
        
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        
        # Ensure TV is on and in Art Mode
        if not await self._ensure_art_mode_ready():
            return {"error": "Failed to turn on TV"}
        
        try:
            # Check if file exists
            file_exists = await self.hass.async_add_executor_job(
                lambda: __import__("os").path.exists(file_path)
            )
            if not file_exists:
                _LOGGER.error("Frame Art: File not found: %s", file_path)
                return {"error": f"File not found: {file_path}"}
            
            # Get file size for logging
            file_size = await self.hass.async_add_executor_job(
                lambda: __import__("os").path.getsize(file_path)
            )
            _LOGGER.info("Frame Art: Uploading file %s (%d bytes) with matte=%s", 
                        file_path, file_size, matte_id)
            
            content_id = await self._art_api.upload(
                file_path,
                matte=matte_id,
                file_type=file_type,
                hass=self.hass,
            )
            if content_id:
                _LOGGER.info("Frame Art: Upload successful, content_id=%s", content_id)
                
                # Force immediate update 🚀
                await self._force_art_coordinator_refresh()
                
                return {"success": True, "content_id": content_id}
            
            _LOGGER.error("Frame Art: Upload failed - no content_id returned")
            return {"error": "Upload failed - no content_id returned"}
        except Exception as ex:
            _LOGGER.error("Error uploading artwork: %s", ex)
            import traceback
            _LOGGER.debug("Frame Art: Upload traceback: %s", traceback.format_exc())
            return {"error": str(ex)}

    async def async_art_delete(self, content_id: str) -> dict:
        """Delete an uploaded piece of artwork."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        if not content_id.startswith("MY"):
            return {"error": "Can only delete user-uploaded content (MY-*)"}
        try:
            await self._art_api.delete(content_id)
            
            # Force immediate update 🚀
            await self._force_art_coordinator_refresh()
            
            return {"success": True}
        except Exception as ex:
            _LOGGER.error("Error deleting artwork: %s", ex)
            return {"error": str(ex)}

    async def async_art_get_thumbnail(self, content_id: str, save_to_file: bool = True, force_download: bool = False) -> dict:
        """Get thumbnail for a specific piece of artwork.
        
        If save_to_file is True, saves the thumbnail to:
        - /config/www/frame_art/personal/ for user-uploaded images (MY_F*)
        - /config/www/frame_art/store/ for Samsung Art Store images (SAM-*)
        - /config/www/frame_art/other/ for other content types
        
        If force_download is False, checks if file already exists before downloading.
        """
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            result = {"error": "Frame TV not supported"}
            self._store_art_result(result)
            return result
        
        try:
            import os
            
            # Determine subdirectory and file path based on content type
            if content_id.startswith("MY_F"):
                subdir = "personal"
            elif content_id.startswith("SAM-"):
                subdir = "store"
            else:
                subdir = "other"
            
            # Create directory path
            www_path = self.hass.config.path("www", "frame_art", subdir)
            file_name = f"{content_id.replace(':', '_')}.jpg"
            file_path = os.path.join(www_path, file_name)
            
            # Check if file already exists (unless force_download=True)
            if save_to_file and not force_download:
                def _check_file_exists():
                    return os.path.isfile(file_path)
                
                file_exists = await self.hass.async_add_executor_job(_check_file_exists)
                
                if file_exists:
                    _LOGGER.info("Thumbnail already exists for %s, skipping download", content_id)
                    result = {
                        "service": "art_get_thumbnail",
                        "content_id": content_id,
                        "thumbnail_url": f"/local/frame_art/{subdir}/{file_name}",
                        "thumbnail_path": file_path,
                        "subdirectory": subdir,
                        "cached": True,
                        "message": "File already exists"
                    }
                    self._store_art_result(result)
                    return result
            
            # Download thumbnail with improved retry logic
            max_retries = 3
            retry_delays = [0.5, 1.0, 2.0]  # Progressive delays
            thumbnail_data = None
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    _LOGGER.debug("Downloading thumbnail for %s (attempt %d/%d)", content_id, attempt + 1, max_retries)
                    thumbnail_data = await self._art_api.get_thumbnail(content_id)
                    
                    if thumbnail_data and len(thumbnail_data) > 0:
                        _LOGGER.debug("Successfully downloaded thumbnail for %s (%d bytes)", content_id, len(thumbnail_data))
                        break
                    else:
                        last_error = "No thumbnail data received"
                        _LOGGER.debug("No data for %s on attempt %d", content_id, attempt + 1)
                except Exception as retry_ex:
                    last_error = str(retry_ex)
                    _LOGGER.debug("Error downloading %s on attempt %d: %s", content_id, attempt + 1, retry_ex)
                
                # Wait before retry (except on last attempt)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt])
            
            if thumbnail_data and len(thumbnail_data) > 0:
                import base64
                encoded = base64.b64encode(thumbnail_data).decode("utf-8")
                result = {
                    "service": "art_get_thumbnail",
                    "content_id": content_id,
                    "thumbnail_base64": encoded,
                    "size": len(thumbnail_data),
                }
                
                # Save to file for Lovelace access
                if save_to_file:
                    try:
                        def _write_thumbnail():
                            os.makedirs(www_path, exist_ok=True)
                            with open(file_path, "wb") as f:
                                f.write(thumbnail_data)
                            return file_name, file_path, subdir
                        
                        # Run file I/O in executor to avoid blocking
                        file_name, file_path, subdir = await self.hass.async_add_executor_job(_write_thumbnail)
                        
                        # Add URL to result
                        result["thumbnail_url"] = f"/local/frame_art/{subdir}/{file_name}"
                        result["thumbnail_path"] = file_path
                        result["subdirectory"] = subdir
                        _LOGGER.debug("Saved thumbnail to %s", file_path)
                    except Exception as file_ex:
                        _LOGGER.warning("Could not save thumbnail to file: %s", file_ex)
                
                self._store_art_result(result)
                return result
            
            # All retries failed
            error_msg = f"Failed after {max_retries} attempts: {last_error}"
            _LOGGER.warning("Could not download thumbnail for %s: %s", content_id, error_msg)
            result = {"error": error_msg, "content_id": content_id}
            self._store_art_result(result)
            return result
            
        except Exception as ex:
            _LOGGER.error("Error getting thumbnail for %s: %s", content_id, ex)
            result = {"error": str(ex), "content_id": content_id}
            self._store_art_result(result)
            return result

    async def _cleanup_orphan_thumbnails(
        self,
        valid_content_ids: set,
        favorites_only: bool = False,
        personal_only: bool = False,
        category_id: str | None = None,
    ) -> list:
        """Remove local thumbnail files that are no longer in the artwork list.
        
        Args:
            valid_content_ids: Set of content IDs that should be kept
            favorites_only: If True, only clean store/ directory (favorites are SAM-* images)
            personal_only: If True, only clean personal/ directory
            category_id: If set, determine which directory to clean based on category
            
        Returns:
            List of removed file paths
        """
        removed_files = []
        
        # Determine which directories to clean
        dirs_to_clean = []
        base_path = self.hass.config.path("www", "frame_art")
        
        if favorites_only:
            # Favorites are typically SAM-* (store) images
            dirs_to_clean = [("store", os.path.join(base_path, "store"))]
        elif personal_only:
            # Personal photos are MY_F* images
            dirs_to_clean = [("personal", os.path.join(base_path, "personal"))]
        elif category_id:
            # Determine based on category
            if category_id == "MY-C0002":  # Personal photos
                dirs_to_clean = [("personal", os.path.join(base_path, "personal"))]
            elif category_id == "MY-C0004":  # Favorites (mostly store)
                dirs_to_clean = [("store", os.path.join(base_path, "store"))]
            else:
                # Clean all directories for other categories
                dirs_to_clean = [
                    ("personal", os.path.join(base_path, "personal")),
                    ("store", os.path.join(base_path, "store")),
                    ("other", os.path.join(base_path, "other")),
                ]
        else:
            # Clean all directories
            dirs_to_clean = [
                ("personal", os.path.join(base_path, "personal")),
                ("store", os.path.join(base_path, "store")),
                ("other", os.path.join(base_path, "other")),
            ]
        
        def _do_cleanup():
            """Synchronous cleanup function to run in executor."""
            removed = []
            for subdir_name, dir_path in dirs_to_clean:
                if not os.path.exists(dir_path):
                    continue
                    
                try:
                    for filename in os.listdir(dir_path):
                        if not filename.endswith(".jpg"):
                            continue
                        
                        # Extract content_id from filename (remove .jpg extension)
                        content_id = filename[:-4]
                        
                        # Check if this content_id is still valid
                        if content_id not in valid_content_ids:
                            file_path = os.path.join(dir_path, filename)
                            try:
                                os.remove(file_path)
                                removed.append({
                                    "content_id": content_id,
                                    "path": file_path,
                                    "subdirectory": subdir_name,
                                })
                                _LOGGER.info("Removed orphan thumbnail: %s", file_path)
                            except OSError as ex:
                                _LOGGER.warning("Failed to remove orphan thumbnail %s: %s", file_path, ex)
                except OSError as ex:
                    _LOGGER.warning("Error scanning directory %s: %s", dir_path, ex)
            
            return removed
        
        try:
            removed_files = await self.hass.async_add_executor_job(_do_cleanup)
            if removed_files:
                _LOGGER.info("Cleaned up %d orphan thumbnail(s)", len(removed_files))
        except Exception as ex:
            _LOGGER.error("Error during orphan thumbnail cleanup: %s", ex)
        
        return removed_files

    async def async_art_get_thumbnails_batch(
        self,
        category_id: str | None = None,
        favorites_only: bool = False,
        personal_only: bool = False,
        force_download: bool = False,
        cleanup_orphans: bool = False,
    ) -> dict:
        """Download thumbnails for multiple artworks.
        
        Downloads thumbnails for:
        - All favorites (if favorites_only=True)
        - All personal images (if personal_only=True)
        - All artworks in a specific category (if category_id provided)
        - All artworks (if no filters specified)
        
        Saves thumbnails to organized subdirectories:
        - /config/www/frame_art/personal/ for user-uploaded images (MY_F*)
        - /config/www/frame_art/store/ for Samsung Art Store images (SAM-*)
        - /config/www/frame_art/other/ for other content types
        
        If force_download=False, skips files that already exist.
        If cleanup_orphans=True, removes local files not in the current artwork list.
        """
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            result = {"error": "Frame TV not supported"}
            self._store_art_result(result)
            return result
            
        try:
            # Get artwork list based on filters
            if favorites_only:
                # Get favorites (category 4 = MY-C0004)
                artwork_list = await self._art_api.available("MY-C0004")
            elif personal_only:
                # Get personal photos (category 2 = MY-C0002)
                artwork_list = await self._art_api.available("MY-C0002")
            elif category_id:
                # Get specific category
                artwork_list = await self._art_api.available(category_id)
            else:
                # Get all artworks
                artwork_list = await self._art_api.available()
            
            if not artwork_list:
                result = {
                    "service": "art_get_thumbnails_batch",
                    "success": False,
                    "message": "No artworks found",
                    "downloaded": 0,
                    "skipped": 0,
                    "failed": 0,
                }
                self._store_art_result(result)
                return result
            
            # Build set of valid content IDs
            valid_content_ids = {artwork.get("content_id") for artwork in artwork_list if artwork.get("content_id")}
            
            # Cleanup orphans if requested
            removed_files = []
            if cleanup_orphans:
                removed_files = await self._cleanup_orphan_thumbnails(valid_content_ids, favorites_only, personal_only, category_id)
            
            # Download thumbnails with progress tracking
            downloaded = []
            skipped = []
            failed = []
            total = len(artwork_list)
            
            _LOGGER.info("Starting batch thumbnail download for %d artworks (force_download=%s, cleanup_orphans=%s)", total, force_download, cleanup_orphans)
            
            for idx, artwork in enumerate(artwork_list, 1):
                content_id = artwork.get("content_id")
                if not content_id:
                    continue
                
                try:
                    _LOGGER.debug("Processing thumbnail %d/%d: %s", idx, total, content_id)
                    
                    # Download with file existence check (unless force_download)
                    result = await self.async_art_get_thumbnail(
                        content_id, 
                        save_to_file=True, 
                        force_download=force_download
                    )
                    
                    if "error" in result:
                        failed.append({
                            "content_id": content_id,
                            "error": result.get("error")
                        })
                    elif result.get("cached"):
                        skipped.append({
                            "content_id": content_id,
                            "url": result.get("thumbnail_url"),
                            "path": result.get("thumbnail_path"),
                            "subdirectory": result.get("subdirectory"),
                            "reason": "Already exists"
                        })
                    else:
                        downloaded.append({
                            "content_id": content_id,
                            "url": result.get("thumbnail_url"),
                            "path": result.get("thumbnail_path"),
                            "subdirectory": result.get("subdirectory"),
                            "size": result.get("size")
                        })
                    
                    # Shorter delay between downloads
                    await asyncio.sleep(0.05)
                    
                except Exception as ex:
                    _LOGGER.warning("Failed to process thumbnail for %s: %s", content_id, ex)
                    failed.append({"content_id": content_id, "error": str(ex)})
            
            # Build summary with metadata
            result = {
                "service": "art_get_thumbnails_batch",
                "success": True,
                "total_artworks": total,
                "downloaded": len(downloaded),
                "skipped": len(skipped),
                "failed": len(failed),
                "removed": len(removed_files),
                "downloaded_list": downloaded,
                "skipped_list": skipped,
                "failed_list": failed,
                "removed_list": removed_files,
                "filters": {
                    "category_id": category_id,
                    "favorites_only": favorites_only,
                    "personal_only": personal_only,
                    "force_download": force_download,
                    "cleanup_orphans": cleanup_orphans,
                },
            }
            
            _LOGGER.info(
                "Batch thumbnail download complete: %d downloaded, %d skipped (already exist), %d failed, %d removed out of %d total",
                len(downloaded),
                len(skipped),
                len(failed),
                len(removed_files),
                total,
            )
            
            self._store_art_result(result)
            return result
            
        except Exception as ex:
            _LOGGER.error("Error in batch thumbnail download: %s", ex)
            result = {
                "service": "art_get_thumbnails_batch",
                "error": str(ex),
            }
            self._store_art_result(result)
            return result
            self._store_art_result(result)
            return result

    async def async_art_set_brightness(self, brightness: int) -> dict:
        """Set Art Mode brightness.
        
        Accepts brightness 0-100 from UI and converts to TV's 1-10 scale.
        """
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        
        # Ensure TV is on and in Art Mode
        if not await self._ensure_art_mode_ready():
            return {"error": "Failed to turn on TV"}
        
        try:
            # Convert 0-100 scale to 1-10 scale for the TV API
            # 0-10 -> 1, 11-20 -> 2, ..., 91-100 -> 10
            tv_brightness = max(1, min(10, (brightness // 10) + (1 if brightness % 10 > 0 or brightness == 0 else 0)))
            # Simpler: map 0->1, 10->1, 20->2, ..., 100->10
            if brightness == 0:
                tv_brightness = 0
            else:
                tv_brightness = max(1, min(10, round(brightness / 10)))
            
            _LOGGER.debug("Frame Art: Converting brightness %d -> %d (TV scale)", brightness, tv_brightness)
            await self._art_api.set_brightness(tv_brightness)
            return {"success": True, "brightness_ui": brightness, "brightness_tv": tv_brightness}
        except Exception as ex:
            _LOGGER.error("Error setting brightness: %s", ex)
            return {"error": str(ex)}

    async def async_art_get_brightness(self) -> dict:
        """Get Art Mode brightness.
        
        Returns brightness in both TV scale (1-10) and UI scale (0-100).
        """
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        try:
            result = await self._art_api.get_brightness()
            # Convert TV's 1-10 scale to 0-100 for UI
            ui_brightness = result * 10 if result else None
            return {"brightness_tv": result, "brightness_ui": ui_brightness}
        except Exception as ex:
            _LOGGER.error("Error getting brightness: %s", ex)
            return {"error": str(ex)}

    async def async_art_change_matte(
        self,
        content_id: str,
        matte_id: str,
    ) -> dict:
        """Change the matte/frame style for artwork."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        
        # Ensure TV is on and in Art Mode
        if not await self._ensure_art_mode_ready():
            return {"error": "Failed to turn on TV"}
        
        try:
            await self._art_api.change_matte(content_id, matte_id)
            return {"success": True}
        except Exception as ex:
            _LOGGER.error("Error changing matte: %s", ex)
            return {"error": str(ex)}

    async def async_art_set_photo_filter(
        self,
        content_id: str,
        filter_id: str,
    ) -> dict:
        """Apply a photo filter to artwork."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        try:
            await self._art_api.set_photo_filter(content_id, filter_id)
            return {"success": True}
        except Exception as ex:
            _LOGGER.error("Error setting photo filter: %s", ex)
            return {"error": str(ex)}

    async def async_art_get_photo_filter_list(self) -> dict:
        """Get list of available photo filters."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        try:
            filters = await self._art_api.get_photo_filter_list()
            _LOGGER.info("%s - Available photo filters: %s", self.entity_id, filters)
            return {"filters": filters}
        except Exception as ex:
            _LOGGER.error("Error getting photo filter list: %s", ex)
            return {"error": str(ex)}

    async def async_art_get_matte_list(self) -> dict:
        """Get list of available matte styles."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        try:
            matte_types, matte_colors = await self._art_api.get_matte_list(include_color=True)
            result = {"matte_types": matte_types, "matte_colors": matte_colors}
            _LOGGER.info(
                "%s - Available matte types: %s | Available matte colors: %s",
                self.entity_id,
                matte_types,
                matte_colors,
            )
            return result
        except Exception as ex:
            _LOGGER.error("Error getting matte list: %s", ex)
            return {"error": str(ex)}

    async def async_art_set_favourite(
        self,
        content_id: str,
        status: str = "on",
    ) -> dict:
        """Add or remove artwork from favourites."""
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        try:
            await self._art_api.set_favourite(content_id, status)
            return {"success": True}
        except Exception as ex:
            _LOGGER.error("Error setting favourite status: %s", ex)
            return {"error": str(ex)}

    async def async_art_set_slideshow(
        self,
        duration: str,
        shuffle: bool = True,
        category_id: int = 2,
    ) -> dict:
        """Configure slideshow settings.
        
        Duration accepts: '3min', '15min', '1h', '12h', '1d', '7d'
        """
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        
        # Convert string duration to minutes
        duration_map = {
            "3min": 3,
            "15min": 15,
            "1h": 60,
            "12h": 720,
            "1d": 1440,
            "7d": 10080,
        }
        
        duration_minutes = duration_map.get(duration)
        if duration_minutes is None:
            # Try to parse as integer for backwards compatibility
            try:
                duration_minutes = int(duration)
            except (ValueError, TypeError):
                return {"error": f"Invalid duration: {duration}. Valid values: 3min, 15min, 1h, 12h, 1d, 7d"}
        
        # Ensure TV is on and in Art Mode
        if not await self._ensure_art_mode_ready():
            return {"error": "Failed to turn on TV"}
        
        try:
            _LOGGER.debug("Frame Art: Setting slideshow duration=%s (%d min), shuffle=%s, category=%d",
                         duration, duration_minutes, shuffle, category_id)
            await self._art_api.set_slideshow_status(duration_minutes, shuffle, category_id)
            return {"success": True, "duration": duration, "duration_minutes": duration_minutes}
        except Exception as ex:
            _LOGGER.error("Error setting slideshow: %s", ex)
            return {"error": str(ex)}

    async def async_art_set_auto_rotation(
        self,
        duration: str,
        shuffle: bool = True,
        category_id: int = 2,
    ) -> dict:
        """Configure auto rotation settings.
        
        Duration accepts: '3min', '15min', '1h', '12h', '1d', '7d'
        """
        if not await self._ensure_frame_tv_check():
            _LOGGER.warning("Frame TV art mode is not supported on this device")
            return {"error": "Frame TV not supported"}
        
        # Convert string duration to minutes
        duration_map = {
            "3min": 3,
            "15min": 15,
            "1h": 60,
            "12h": 720,
            "1d": 1440,
            "7d": 10080,
        }
        
        duration_minutes = duration_map.get(duration)
        if duration_minutes is None:
            try:
                duration_minutes = int(duration)
            except (ValueError, TypeError):
                return {"error": f"Invalid duration: {duration}. Valid values: 3min, 15min, h, 12h, 1d, 7d"}
        
        # Ensure TV is on and in Art Mode
        if not await self._ensure_art_mode_ready():
            return {"error": "Failed to turn on TV"}
        
        try:
            _LOGGER.debug("Frame Art: Setting auto rotation duration=%s (%d min), shuffle=%s, category=%d",
                         duration, duration_minutes, shuffle, category_id)
            await self._art_api.set_auto_rotation_status(duration_minutes, shuffle, category_id)
            return {"success": True, "duration": duration, "duration_minutes": duration_minutes}
        except Exception as ex:
            _LOGGER.error("Error setting auto rotation: %s", ex)
            return {"error": str(ex)}

    async def _async_switch_entity(self, power_on: bool):
        """Switch on/off related configure HA entity."""

        if power_on:
            service_name = f"{HA_DOMAIN}.{SERVICE_TURN_ON}"
            conf_entity = CONF_SYNC_TURN_ON
        else:
            service_name = f"{HA_DOMAIN}.{SERVICE_TURN_OFF}"
            conf_entity = CONF_SYNC_TURN_OFF

        entity_list = self._get_option(conf_entity)
        if not entity_list:
            return

        for index, entity in enumerate(entity_list):
            if index >= MAX_CONTROLLED_ENTITY:
                _LOGGER.warning(
                    "SamsungTV Smart - Maximum %s entities can be controlled",
                    MAX_CONTROLLED_ENTITY,
                )
                break
            if entity:
                await _async_call_service(self.hass, service_name, entity)

        return


async def _async_call_service(
    hass,
    service_name,
    entity_id,
    variable_data=None,
):
    """Call a HA service."""
    service_data = {
        CONF_SERVICE: service_name,
        CONF_SERVICE_ENTITY_ID: entity_id,
    }

    if variable_data:
        service_data[CONF_SERVICE_DATA] = variable_data

    try:
        await async_call_from_config(
            hass,
            service_data,
            blocking=False,
            validate_config=True,
        )
    except HomeAssistantError as ex:
        _LOGGER.error("SamsungTV Smart - error %s", ex)

    return
