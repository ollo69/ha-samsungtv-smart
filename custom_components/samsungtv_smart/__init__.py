"""The samsungtv_smart integration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import socket

from aiohttp import ClientConnectionError, ClientResponseError, ClientSession
import async_timeout
import voluptuous as vol
from websocket import WebSocketException

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.smartthings.const import DOMAIN as ST_DOMAIN
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
    CONF_CHANNEL_LIST,
    CONF_DEVICE_NAME,
    CONF_LOAD_ALL_APPS,
    CONF_SCAN_APP_HTTP,
    CONF_SHOW_CHANNEL_NR,
    CONF_SOURCE_LIST,
    CONF_SYNC_TURN_OFF,
    CONF_SYNC_TURN_ON,
    CONF_UPDATE_CUSTOM_PING_URL,
    CONF_UPDATE_METHOD,
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
    __min_ha_version__,
)
from .logo import CUSTOM_IMAGE_BASE_URL, STATIC_IMAGE_BASE_URL

DEVICE_INFO = {
    ATTR_DEVICE_ID: "id",
    ATTR_DEVICE_MAC: "wifiMac",
    ATTR_DEVICE_NAME: "name",
    ATTR_DEVICE_MODEL: "modelName",
    ATTR_DEVICE_OS: "OS",
}

SAMSMART_PLATFORM = [Platform.MEDIA_PLAYER, Platform.REMOTE]

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
def get_smartthing_api_key(hass: HomeAssistant) -> str | None:
    """Get the smartthing integration configured API key."""
    entries_list = hass.config_entries.async_entries(ST_DOMAIN, False, False)
    if not entries_list:
        return None

    config_data = entries_list[0].data
    if CONF_TOKEN not in config_data:
        return None
    return config_data[CONF_TOKEN].get(CONF_ACCESS_TOKEN)


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

        for port in (8001, 8002):
            try:
                _LOGGER.info(
                    "Try to configure SamsungTV %s using port %s",
                    self._hostname,
                    str(port),
                )
                with SamsungTVWS(
                    name=f"{WS_PREFIX} {self._ws_name}",  # this is the name shown in the TV
                    host=self._hostname,
                    port=port,
                    timeout=45,  # We need this high timeout because waiting for TV auth popup
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
                with SmartThingsTV(
                    api_key=api_key,
                    device_id=device_id,
                    session=session,
                ) as st_tv:
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
        self, session: ClientSession, api_key=None, st_device_id=None
    ):
        """Try connect device"""
        if session is None:
            return RESULT_NOT_SUCCESSFUL

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
