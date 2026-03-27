"""The samsungtv_smart integration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import time

from aiohttp import ClientConnectionError, ClientResponseError, ClientSession
import async_timeout
import voluptuous as vol
from websocket import WebSocketException

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_DEVICE_ID,
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_BROADCAST_ADDRESS,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_ID,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TIMEOUT,
    CONF_TOKEN,
    MAJOR_VERSION,
    MINOR_VERSION,
    Platform,
    __version__,
)
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.helpers.typing import ConfigType

from .api.samsungws import ConnectionFailure, SamsungTVWS
from .api.smartthings import SmartThingsTV
from .const import (
    ATTR_DEVICE_MAC,
    ATTR_DEVICE_MODEL,
    ATTR_DEVICE_NAME,
    ATTR_DEVICE_OS,
    CONF_APP_LIST,
    CONF_AUTH_METHOD,
    CONF_CHANNEL_LIST,
    CONF_DEVICE_NAME,
    CONF_LOAD_ALL_APPS,
    CONF_OAUTH_TOKEN,
    CONF_SCAN_APP_HTTP,
    CONF_SHOW_CHANNEL_NR,
    CONF_SOURCE_LIST,
    CONF_ST_ENTRY_UNIQUE_ID,
    CONF_SYNC_TURN_OFF,
    CONF_SYNC_TURN_ON,
    CONF_UPDATE_CUSTOM_PING_URL,
    CONF_UPDATE_METHOD,
    CONF_USE_ST_INT_API_KEY,
    CONF_WS_NAME,
    DATA_CFG,
    DATA_CFG_YAML,
    DATA_OPTIONS,
    DEFAULT_PORT,
    DEFAULT_SOURCE_LIST,
    DEFAULT_TIMEOUT,
    DOMAIN,
    LOCAL_LOGO_PATH,
    MIN_HA_MAJ_VER,
    MIN_HA_MIN_VER,
    RESULT_NOT_SUCCESSFUL,
    RESULT_ST_DEVICE_NOT_FOUND,
    RESULT_SUCCESS,
    RESULT_WRONG_APIKEY,
    SIGNAL_CONFIG_ENTITY,
    WS_PREFIX,
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_PAT,
    AUTH_METHOD_ST_ENTRY,
    __min_ha_version__,
)
from .logo import CUSTOM_IMAGE_BASE_URL, STATIC_IMAGE_BASE_URL

# workaroud for failing import native domain when custom integration is present
try:
    from homeassistant.components.smartthings.const import DOMAIN as ST_DOMAIN
except ImportError:
    ST_DOMAIN = "smartthings"

DEVICE_INFO = {
    ATTR_DEVICE_ID: "id",
    ATTR_DEVICE_MAC: "wifiMac",
    ATTR_DEVICE_NAME: "name",
    ATTR_DEVICE_MODEL: "modelName",
    ATTR_DEVICE_OS: "OS",
}

SAMSMART_PLATFORM = [Platform.SENSOR, Platform.MEDIA_PLAYER, Platform.REMOTE, Platform.SWITCH, Platform.SELECT]

SAMSMART_SCHEMA = {
    vol.Optional(CONF_SOURCE_LIST, default=DEFAULT_SOURCE_LIST): cv.string,
    vol.Optional(CONF_APP_LIST): cv.string,
    vol.Optional(CONF_CHANNEL_LIST): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
    vol.Optional(CONF_MAC): cv.string,
    vol.Optional(CONF_BROADCAST_ADDRESS): cv.string,
}


def ensure_unique_hosts(value):
    """Validate that all configs have a unique host."""
    vol.Schema(vol.Unique("duplicate host entries found"))(
        [socket.gethostbyname(entry[CONF_HOST]) for entry in value]
    )
    return value


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [
                cv.deprecated(CONF_LOAD_ALL_APPS),
                cv.deprecated(CONF_PORT),
                cv.deprecated(CONF_UPDATE_METHOD),
                cv.deprecated(CONF_UPDATE_CUSTOM_PING_URL),
                cv.deprecated(CONF_SCAN_APP_HTTP),
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): cv.string,
                        vol.Optional(CONF_NAME): cv.string,
                        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                        vol.Optional(CONF_API_KEY): cv.string,
                        vol.Optional(CONF_DEVICE_NAME): cv.string,
                        vol.Optional(CONF_DEVICE_ID): cv.string,
                        vol.Optional(CONF_LOAD_ALL_APPS, default=True): cv.boolean,
                        vol.Optional(CONF_UPDATE_METHOD): cv.string,
                        vol.Optional(CONF_UPDATE_CUSTOM_PING_URL): cv.string,
                        vol.Optional(CONF_SCAN_APP_HTTP, default=True): cv.boolean,
                        vol.Optional(CONF_SHOW_CHANNEL_NR, default=False): cv.boolean,
                        vol.Optional(CONF_WS_NAME): cv.string,
                    }
                ).extend(SAMSMART_SCHEMA),
            ],
            ensure_unique_hosts,
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)

# Global lock dictionary to prevent concurrent OAuth refresh per entry
# This is shared across all entities (media_player, switch, sensor)
_OAUTH_REFRESH_LOCKS: dict[str, asyncio.Lock] = {}
_OAUTH_REFRESH_IN_PROGRESS: dict[str, bool] = {}


def get_oauth_refresh_lock(entry_id: str) -> asyncio.Lock:
    """Get or create a lock for OAuth refresh for a specific entry."""
    if entry_id not in _OAUTH_REFRESH_LOCKS:
        _OAUTH_REFRESH_LOCKS[entry_id] = asyncio.Lock()
    return _OAUTH_REFRESH_LOCKS[entry_id]


def is_oauth_refresh_in_progress(entry_id: str) -> bool:
    """Check if OAuth refresh is already in progress for an entry."""
    return _OAUTH_REFRESH_IN_PROGRESS.get(entry_id, False)


def set_oauth_refresh_in_progress(entry_id: str, in_progress: bool) -> None:
    """Set OAuth refresh in progress state for an entry."""
    _OAUTH_REFRESH_IN_PROGRESS[entry_id] = in_progress


def tv_url(host: str, address: str = "") -> str:
    """Return url to the TV."""
    return f"http://{host}:8001/api/v2/{address}"


def is_min_ha_version(min_ha_major_ver: int, min_ha_minor_ver: int) -> bool:
    """Check if HA version at least a specific version."""
    return MAJOR_VERSION > min_ha_major_ver or (
        MAJOR_VERSION == min_ha_major_ver and MINOR_VERSION >= min_ha_minor_ver
    )


def is_valid_ha_version() -> bool:
    """Check if HA version is valid for this integration."""
    return is_min_ha_version(MIN_HA_MAJ_VER, MIN_HA_MIN_VER)


def _notify_message(
    hass: HomeAssistant, notification_id: str, title: str, message: str
) -> None:
    """Notify user with persistent notification."""
    hass.async_create_task(
        hass.services.async_call(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}.{notification_id}",
            },
        )
    )


def _load_option_list(src_list):
    """Load list parameters in JSON from configuration.yaml."""

    if src_list is None:
        return None
    if isinstance(src_list, dict):
        return src_list

    result = {}
    try:
        result = json.loads(src_list)
    except TypeError:
        _LOGGER.error("Invalid format parameter: %s", str(src_list))
    return result


def token_file_name(hostname: str) -> str:
    """Return token file name."""
    return f"{DOMAIN}_{hostname}_token"


def _remove_token_file(hass, hostname, token_file=None):
    """Try to remove token file."""
    if not token_file:
        token_file = hass.config.path(STORAGE_DIR, token_file_name(hostname))

    if os.path.isfile(token_file):
        try:
            os.remove(token_file)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.error(
                "Samsung TV - Error deleting token file %s: %s", token_file, str(exc)
            )


def _migrate_token(hass: HomeAssistant, entry: ConfigEntry, hostname: str) -> None:
    """Migrate token from old file to registry entry."""
    token_file = hass.config.path(STORAGE_DIR, token_file_name(hostname))
    if not os.path.isfile(token_file):
        token_file = (
            os.path.dirname(os.path.realpath(__file__)) + f"/token-{hostname}.txt"
        )
        if not os.path.isfile(token_file):
            return

    try:
        with open(token_file, "r", encoding="utf-8") as os_token_file:
            token = os_token_file.readline()
    except Exception as exc:  # pylint: disable=broad-except
        _LOGGER.error("Error reading token file %s: %s", token_file, str(exc))
        return

    if not token:
        _LOGGER.warning("No token found inside token file %s", token_file)
        return

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKEN: token}
    )
    _remove_token_file(hass, hostname, token_file)


@callback
def _migrate_options_format(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate options to new format."""
    opt_migrated = False
    new_options = {}

    for key, option in entry.options.items():
        if key in [CONF_SYNC_TURN_OFF, CONF_SYNC_TURN_ON]:
            if isinstance(option, str):
                new_options[key] = option.split(",")
                opt_migrated = True
                continue
        new_options[key] = option

    # load the option lists in entry option
    yaml_opt = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get(DATA_CFG_YAML, {})
    for key in [CONF_APP_LIST, CONF_CHANNEL_LIST, CONF_SOURCE_LIST]:
        if key not in new_options:  # import will occurs only on first restart
            if option := _load_option_list(yaml_opt.get(key, {})):
                message = (
                    f"Configuration key '{key}' has been in imported in integration options,"
                    " you can now remove from configuration.yaml"
                )
                _notify_message(
                    hass, f"config-import-{key}", "SamsungTV Smart", message
                )
                _LOGGER.warning(message)
            new_options[key] = option
            opt_migrated = True

    if opt_migrated:
        hass.config_entries.async_update_entry(entry, options=new_options)


@callback
def _migrate_entry_unique_id(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate unique_is to new format."""
    if CONF_ID in entry.data:
        new_unique_id = entry.data[CONF_ID]
    elif CONF_MAC in entry.data:
        new_unique_id = entry.data[CONF_MAC]
    else:
        new_unique_id = entry.data[CONF_HOST]

    if entry.unique_id == new_unique_id:
        return

    entries_list = hass.config_entries.async_entries(DOMAIN)
    for other_entry in entries_list:
        if other_entry.unique_id == new_unique_id:
            _LOGGER.warning(
                "Found duplicated entries %s and %s that refer to the same device."
                " Please remove unused entry",
                entry.data[CONF_HOST],
                other_entry.data[CONF_HOST],
            )
            return

    _LOGGER.info(
        "Migrated entry unique id from %s to %s", entry.unique_id, new_unique_id
    )
    hass.config_entries.async_update_entry(entry, unique_id=new_unique_id)


@callback
def _migrate_smartthings_config(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate smartthings entry usage configuration."""
    if CONF_USE_ST_INT_API_KEY not in entry.data:
        return

    new_data = entry.data.copy()
    use_st = new_data.pop(CONF_USE_ST_INT_API_KEY)
    if use_st:
        if entries_list := hass.config_entries.async_entries(ST_DOMAIN, False, False):
            new_data[CONF_ST_ENTRY_UNIQUE_ID] = entries_list[0].unique_id

    hass.config_entries.async_update_entry(entry, data=new_data)


@callback
def get_smartthings_entries(hass: HomeAssistant) -> dict[str, str] | None:
    """Get the smartthing integration configured entries.
    
    Returns entries that have either:
    - CONF_TOKEN (PAT or OAuth in token dict)
    - CONF_ACCESS_TOKEN (direct OAuth token)
    """
    entries_list = hass.config_entries.async_entries(ST_DOMAIN, False, False)
    if not entries_list:
        return None

    result = {}
    for entry in entries_list:
        # Include entries with token (PAT or OAuth dict)
        # OR direct access_token (OAuth alternative structure)
        if CONF_TOKEN in entry.data or CONF_ACCESS_TOKEN in entry.data:
            result[entry.unique_id] = entry.title
    
    return result if result else None


@callback
def get_smartthings_api_key(hass: HomeAssistant, st_unique_id: str) -> str | None:
    """Get the smartthing integration configured API key.
    
    Supports both:
    - Legacy PAT (Personal Access Token) - stored as string
    - OAuth tokens - stored as dict with access_token
    """
    entries_list = hass.config_entries.async_entries(ST_DOMAIN, False, False)
    if not entries_list:
        return None

    for entry in entries_list:
        if entry.unique_id == st_unique_id:
            config_data = entry.data
            
            # Try OAuth token structure first (new method)
            # OAuth tokens are in entry.data['token'] as dict
            if CONF_TOKEN in config_data:
                token_data = config_data[CONF_TOKEN]
                
                # OAuth: token is a dict with access_token key
                if isinstance(token_data, dict):
                    if CONF_ACCESS_TOKEN in token_data:
                        _LOGGER.debug(
                            "SmartThings: Found OAuth access_token for %s", 
                            st_unique_id
                        )
                        return token_data[CONF_ACCESS_TOKEN]
                
                # Legacy PAT: token is a string directly
                elif isinstance(token_data, str):
                    _LOGGER.debug(
                        "SmartThings: Found legacy PAT token for %s", 
                        st_unique_id
                    )
                    return token_data
            
            # Also try direct access_token key (alternative OAuth structure)
            if CONF_ACCESS_TOKEN in config_data:
                _LOGGER.debug(
                    "SmartThings: Found direct access_token for %s", 
                    st_unique_id
                )
                return config_data[CONF_ACCESS_TOKEN]
            
            _LOGGER.warning(
                "SmartThings: No valid token found for %s in entry data keys: %s",
                st_unique_id,
                list(config_data.keys())
            )
            return None

    return None


async def async_get_samsungtv_api_key(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Get API key based on authentication method configured for this entry.
    
    This function handles all three auth methods:
    - OAuth2: Uses own OAuth token with auto-refresh
    - PAT: Uses Personal Access Token from entry data
    - ST_ENTRY: Gets token from SmartThings integration
    
    Returns:
        API key/access token string if available, None otherwise
    """
    auth_method = entry.data.get(CONF_AUTH_METHOD)
    
    # Method 1: OAuth2 - own token with refresh
    if auth_method == AUTH_METHOD_OAUTH:
        oauth_token = entry.data.get(CONF_OAUTH_TOKEN)
        if oauth_token and isinstance(oauth_token, dict):
            access_token = oauth_token.get("access_token")
            if access_token:
                # Check if token needs refresh (5 minutes before expiration)
                expires_at = oauth_token.get("expires_at", 0)
                current_time = time.time()
                
                if expires_at and current_time > (expires_at - 300):
                    # Check if refresh_token exists
                    if "refresh_token" not in oauth_token:
                        _LOGGER.warning(
                            "OAuth token expired and no refresh_token available. "
                            "Please reconfigure the integration with OAuth."
                        )
                        return access_token  # Try with expired token anyway
                    
                    # Check if another refresh is already in progress
                    if is_oauth_refresh_in_progress(entry.entry_id):
                        _LOGGER.debug("OAuth refresh already in progress, using current token")
                        # Re-read from entry in case it was just refreshed
                        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
                        if updated_entry:
                            updated_token = updated_entry.data.get(CONF_OAUTH_TOKEN, {})
                            return updated_token.get("access_token", access_token)
                        return access_token
                    
                    # Acquire lock to prevent concurrent refresh
                    lock = get_oauth_refresh_lock(entry.entry_id)
                    async with lock:
                        # Double-check after acquiring lock - token might have been refreshed
                        updated_entry = hass.config_entries.async_get_entry(entry.entry_id)
                        if updated_entry:
                            updated_token = updated_entry.data.get(CONF_OAUTH_TOKEN, {})
                            updated_expires = updated_token.get("expires_at", 0)
                            if updated_expires > current_time + 300:
                                _LOGGER.debug("Token was refreshed by another entity, using new token")
                                return updated_token.get("access_token")
                        
                        set_oauth_refresh_in_progress(entry.entry_id, True)
                        try:
                            _LOGGER.warning(
                                "OAuth token %s, attempting refresh",
                                "expired" if current_time > expires_at else "expiring soon"
                            )
                            
                            # Try to get implementation from entry
                            implementation = None
                            try:
                                implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
                                    hass, entry
                                )
                            except Exception as ex:
                                _LOGGER.debug("Could not get implementation from entry: %s", ex)
                            
                            # If not found, try to create it directly from application credentials
                            if not implementation:
                                _LOGGER.debug("Attempting to create OAuth implementation directly")
                                try:
                                    implementations = await config_entry_oauth2_flow.async_get_implementations(
                                        hass, DOMAIN
                                    )
                                    if implementations:
                                        # Use the first available implementation
                                        implementation = list(implementations.values())[0]
                                        _LOGGER.debug("Found OAuth implementation: %s", type(implementation).__name__)
                                        
                                        # Update entry with auth_implementation for future refreshes
                                        if "auth_implementation" not in entry.data:
                                            hass.config_entries.async_update_entry(
                                                entry,
                                                data={**entry.data, "auth_implementation": DOMAIN},
                                            )
                                except Exception as impl_ex:
                                    _LOGGER.debug("Could not get implementations: %s", impl_ex)
                            
                            if implementation:
                                new_token = await implementation.async_refresh_token(oauth_token)
                                # Update entry with new token
                                hass.config_entries.async_update_entry(
                                    entry,
                                    data={
                                        **entry.data,
                                        CONF_OAUTH_TOKEN: new_token,
                                        CONF_API_KEY: new_token["access_token"],
                                        "auth_implementation": DOMAIN,
                                    },
                                )
                                _LOGGER.info("OAuth token refreshed successfully")
                                return new_token["access_token"]
                            else:
                                _LOGGER.error(
                                    "Could not get OAuth implementation - Application Credentials missing. "
                                    "Go to Settings > Devices & Services > Application Credentials "
                                    "and add credentials for Samsung TV Smart."
                                )
                        except Exception as ex:
                            _LOGGER.error("Failed to refresh OAuth token: %s", ex)
                            # Try to use existing token anyway
                        finally:
                            set_oauth_refresh_in_progress(entry.entry_id, False)
                
                _LOGGER.debug("Using OAuth access token")
                return access_token
        
        _LOGGER.warning("OAuth method configured but no valid token found")
        return entry.data.get(CONF_API_KEY)
    
    # Method 2: SmartThings Integration token
    if auth_method == AUTH_METHOD_ST_ENTRY:
        st_unique_id = entry.data.get(CONF_ST_ENTRY_UNIQUE_ID)
        if st_unique_id:
            api_key = get_smartthings_api_key(hass, st_unique_id)
            if api_key:
                _LOGGER.debug("Using SmartThings integration token")
                return api_key
            _LOGGER.warning("Failed to retrieve SmartThings integration access token, using last available")
        return entry.data.get(CONF_API_KEY)
    
    # Method 3: PAT (default/legacy) - also handles old configs without auth_method
    api_key = entry.data.get(CONF_API_KEY)
    
    # Fallback for old configs using ST entry without CONF_AUTH_METHOD set
    if not api_key and CONF_ST_ENTRY_UNIQUE_ID in entry.data:
        st_unique_id = entry.data.get(CONF_ST_ENTRY_UNIQUE_ID)
        if st_unique_id:
            api_key = get_smartthings_api_key(hass, st_unique_id)
            if api_key:
                _LOGGER.debug("Using SmartThings integration token (legacy config)")
                return api_key
            _LOGGER.warning("Failed to retrieve SmartThings integration access token, using last available")
        return entry.data.get(CONF_API_KEY)
    
    if api_key:
        _LOGGER.debug("Using PAT token")
    return api_key


async def _register_logo_paths(hass: HomeAssistant) -> str | None:
    """Register paths for local logos."""

    static_logo_path = Path(__file__).parent / "static"
    static_paths = [
        StaticPathConfig(
            STATIC_IMAGE_BASE_URL, str(static_logo_path), cache_headers=False
        )
    ]

    local_logo_path = Path(hass.config.path("www", f"{DOMAIN}_logos"))
    url_logo_path = str(local_logo_path)
    if not local_logo_path.exists():
        try:
            local_logo_path.mkdir(parents=True)
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.warning(
                "Error registering custom logo folder %s: %s", str(local_logo_path), exc
            )
            url_logo_path = None

    if url_logo_path is not None:
        static_paths.append(
            StaticPathConfig(CUSTOM_IMAGE_BASE_URL, url_logo_path, cache_headers=False)
        )

    await hass.http.async_register_static_paths(static_paths)
    return url_logo_path


async def get_device_info(hostname: str, session: ClientSession) -> dict:
    """Try retrieve device information"""
    try:
        async with async_timeout.timeout(2):
            async with session.get(
                tv_url(host=hostname), raise_for_status=True
            ) as resp:
                info = await resp.json()
    except (asyncio.TimeoutError, ClientConnectionError):
        _LOGGER.warning("Error getting HTTP device info for TV: %s", hostname)
        return {}

    device = info.get("device")
    if not device:
        _LOGGER.warning("Error getting HTTP device info for TV: %s", hostname)
        return {}

    result = {
        key: device[value] for key, value in DEVICE_INFO.items() if value in device
    }

    if ATTR_DEVICE_ID in result:
        device_id = result[ATTR_DEVICE_ID]
        if device_id.startswith("uuid:"):
            result[ATTR_DEVICE_ID] = device_id[len("uuid:") :]

    return result


class SamsungTVInfo:
    """Class to connect and collect TV information."""

    def __init__(self, hass, hostname, ws_name):
        """Initialize the object."""
        self._hass = hass
        self._hostname = hostname
        self._ws_name = ws_name
        self._ws_port = 0
        self._ws_token = None
        self._ping_port = None

    @property
    def ws_port(self):
        """Return used WebSocket port."""
        return self._ws_port

    @property
    def ws_token(self):
        """Return WebSocket token."""
        return self._ws_token

    @property
    def ping_port(self):
        """Return the port used to ping the TV."""
        return self._ping_port

    def _try_connect_ws(self):
        """Try to connect to device using web sockets on port 8001 and 8002"""

        self._ping_port = SamsungTVWS.ping_probe(self._hostname)
        if self._ping_port is None:
            _LOGGER.error(
                "Connection to SamsungTV %s failed. Check that TV is on", self._hostname
            )
            return RESULT_NOT_SUCCESSFUL

        if self._ws_port and self._ws_token:
            port_list = tuple([self._ws_port, 8001, 8002])
        else:
            port_list = (8001, 8002)

        for index, port in enumerate(port_list):

            timeout = 45  # We need this high timeout because waiting for TV auth popup
            token = None
            if len(port_list) > 2 and index == 0:
                timeout = DEFAULT_TIMEOUT
                token = self._ws_token

            try:
                _LOGGER.info(
                    "Try to configure SamsungTV %s using port %s%s",
                    self._hostname,
                    str(port),
                    " with existing token" if token else "",
                )
                with SamsungTVWS(
                    name=f"{WS_PREFIX} {self._ws_name}",  # this is the name shown in the TV
                    host=self._hostname,
                    port=port,
                    token=token,
                    timeout=timeout,
                ) as remote:
                    remote.open()
                    self._ws_token = remote.token
                _LOGGER.info("Found working configuration using port %s", str(port))
                self._ws_port = port
                return RESULT_SUCCESS
            except (OSError, ConnectionFailure, WebSocketException) as err:
                _LOGGER.info(
                    "Configuration failed using port %s, error: %s", str(port), err
                )

        _LOGGER.error("Web socket connection to SamsungTV %s failed", self._hostname)
        return RESULT_NOT_SUCCESSFUL

    @staticmethod
    async def _try_connect_st(api_key, device_id, session: ClientSession):
        """Try to connect to ST device"""

        try:
            async with async_timeout.timeout(10):
                _LOGGER.info("Try connection to SmartThings TV with id [%s]", device_id)
                st_tv = SmartThingsTV(
                    api_key=api_key,
                    device_id=device_id,
                    session=session,
                )
                result = await st_tv.async_device_health()
                if result:
                    _LOGGER.info("Connection completed successfully.")
                    return RESULT_SUCCESS
                _LOGGER.error("Connection to SmartThings TV not available.")
                return RESULT_ST_DEVICE_NOT_FOUND
        except ClientResponseError as err:
            _LOGGER.error("Failed connecting to SmartThings TV, error: %s", err)
            if err.status == 400:  # Bad request, means that token is valid
                return RESULT_ST_DEVICE_NOT_FOUND
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Failed connecting with SmartThings, error: %s", err)

        return RESULT_WRONG_APIKEY

    @staticmethod
    async def get_st_devices(api_key, session: ClientSession, st_device_label=""):
        """Get list of available ST devices"""

        try:
            async with async_timeout.timeout(4):
                devices = await SmartThingsTV.get_devices_list(
                    api_key, session, st_device_label
                )
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Failed connecting with SmartThings, error: %s", err)
            return None

        return devices

    async def try_connect(
        self,
        session: ClientSession,
        api_key=None,
        st_device_id=None,
        *,
        ws_port=None,
        ws_token=None,
    ):
        """Try connect device"""
        if session is None:
            return RESULT_NOT_SUCCESSFUL

        if ws_port and ws_token:
            self._ws_port = ws_port
            self._ws_token = ws_token

        result = await self._hass.async_add_executor_job(self._try_connect_ws)
        if result == RESULT_SUCCESS:
            if api_key and st_device_id:
                result = await self._try_connect_st(api_key, st_device_id, session)

        return result


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Samsung TV integration."""
    if not is_valid_ha_version():
        msg = (
            "This integration require at least HomeAssistant version"
            f" {__min_ha_version__}, you are running version {__version__}."
            " Please upgrade HomeAssistant to continue use this integration."
        )
        _notify_message(hass, "inv_ha_version", "SamsungTV Smart", msg)
        _LOGGER.warning(msg)
        return True

    if DOMAIN in config:
        entries_list = hass.config_entries.async_entries(DOMAIN)
        for entry_config in config[DOMAIN]:
            # get ip address
            ip_address = entry_config[CONF_HOST]

            # check if already configured
            valid_entries = [
                entry.entry_id
                for entry in entries_list
                if entry.data[CONF_HOST] == ip_address
            ]
            if not valid_entries:
                _LOGGER.warning(
                    "Found yaml configuration for not configured device %s."
                    " Please use UI to configure",
                    ip_address,
                )
                continue

            data_yaml = {
                key: value
                for key, value in entry_config.items()
                if key in SAMSMART_SCHEMA and value
            }
            if data_yaml:
                if DOMAIN not in hass.data:
                    hass.data[DOMAIN] = {}
                hass.data[DOMAIN][valid_entries[0]] = {DATA_CFG_YAML: data_yaml}

    # Register path for local logo
    if local_logo_path := await _register_logo_paths(hass):
        hass.data.setdefault(DOMAIN, {})[LOCAL_LOGO_PATH] = local_logo_path

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Samsung TV platform."""
    if not is_valid_ha_version():
        return False

    # migrate unique id to a accepted format
    _migrate_entry_unique_id(hass, entry)

    # migrate smartthings entry usage configuration
    _migrate_smartthings_config(hass, entry)

    # migrate old token file to registry entry if required
    if CONF_TOKEN not in entry.data:
        await hass.async_add_executor_job(
            _migrate_token, hass, entry, entry.data[CONF_HOST]
        )

    # migrate options to new format if required
    _migrate_options_format(hass, entry)

    # setup entry
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    add_conf = None
    config = entry.data.copy()
    if entry.entry_id in hass.data[DOMAIN]:
        add_conf = hass.data[DOMAIN][entry.entry_id].get(DATA_CFG_YAML, {})
        for attr, value in add_conf.items():
            if value:
                config[attr] = value

    # setup entry
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CFG: config,
        DATA_OPTIONS: entry.options.copy(),
    }
    if add_conf:
        hass.data[DOMAIN][entry.entry_id][DATA_CFG_YAML] = add_conf
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, SAMSMART_PLATFORM)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, SAMSMART_PLATFORM
    ):
        hass.data[DOMAIN][entry.entry_id].pop(DATA_CFG)
        hass.data[DOMAIN][entry.entry_id].pop(DATA_OPTIONS)
        if not hass.data[DOMAIN][entry.entry_id]:
            hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a config entry."""
    await hass.async_add_executor_job(_remove_token_file, hass, entry.data[CONF_HOST])
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update when config_entry options update."""
    hass.data[DOMAIN][entry.entry_id][DATA_OPTIONS] = entry.options.copy()
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTITY)
