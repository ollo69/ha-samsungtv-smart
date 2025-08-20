"""Config flow for Samsung TV."""

from __future__ import annotations

import logging
from numbers import Number
import socket
from typing import Any, Dict

import voluptuous as vol

from homeassistant.components.binary_sensor import DOMAIN as BS_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_DEVICE_ID,
    CONF_API_KEY,
    CONF_BASE,
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_ID,
    CONF_MAC,
    CONF_NAME,
    CONF_PORT,
    CONF_TOKEN,
    SERVICE_TURN_ON,
    __version__,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import (
    SamsungTVInfo,
    get_device_info,
    get_smartthing_api_key,
    is_valid_ha_version,
)
from .const import (
    ATTR_DEVICE_MAC,
    ATTR_DEVICE_MODEL,
    ATTR_DEVICE_NAME,
    ATTR_DEVICE_OS,
    CONF_APP_LAUNCH_METHOD,
    CONF_APP_LIST,
    CONF_APP_LOAD_METHOD,
    CONF_CHANNEL_LIST,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_DEVICE_OS,
    CONF_DUMP_APPS,
    CONF_EXT_POWER_ENTITY,
    CONF_LOGO_OPTION,
    CONF_PING_PORT,
    CONF_POWER_ON_METHOD,
    CONF_SHOW_CHANNEL_NR,
    CONF_SOURCE_LIST,
    CONF_SYNC_TURN_OFF,
    CONF_SYNC_TURN_ON,
    CONF_TOGGLE_ART_MODE,
    CONF_USE_LOCAL_LOGO,
    CONF_USE_MUTE_CHECK,
    CONF_USE_ST_CHANNEL_INFO,
    CONF_USE_ST_INT_API_KEY,
    CONF_USE_ST_STATUS_INFO,
    CONF_WOL_REPEAT,
    CONF_WS_NAME,
    DOMAIN,
    MAX_WOL_REPEAT,
    RESULT_ST_DEVICE_NOT_FOUND,
    RESULT_ST_DEVICE_USED,
    RESULT_SUCCESS,
    RESULT_WRONG_APIKEY,
    AppLaunchMethod,
    AppLoadMethod,
    PowerOnMethod,
    __min_ha_version__,
)
from .logo import LOGO_OPTION_DEFAULT, LogoOption

APP_LAUNCH_METHODS = {
    AppLaunchMethod.Standard.value: "Control Web Socket Channel",
    AppLaunchMethod.Remote.value: "Remote Web Socket Channel",
    AppLaunchMethod.Rest.value: "Rest API Call",
}

APP_LOAD_METHODS = {
    AppLoadMethod.All.value: "All Apps",
    AppLoadMethod.Default.value: "Default Apps",
    AppLoadMethod.NotLoad.value: "Not Load",
}

LOGO_OPTIONS = {
    LogoOption.Disabled.value: "Disabled",
    LogoOption.WhiteColor.value: "White background, Color logo",
    LogoOption.BlueColor.value: "Blue background, Color logo",
    LogoOption.BlueWhite.value: "Blue background, White logo",
    LogoOption.DarkWhite.value: "Dark background, White logo",
    LogoOption.TransparentColor.value: "Transparent background, Color logo",
    LogoOption.TransparentWhite.value: "Transparent background, White logo",
}

POWER_ON_METHODS = {
    PowerOnMethod.WOL.value: "WOL Packet (better for wired connection)",
    PowerOnMethod.SmartThings.value: "SmartThings (better for wireless connection)",
}

CONF_SHOW_ADV_OPT = "show_adv_opt"
CONF_ST_DEVICE = "st_devices"
CONF_USE_HA_NAME = "use_ha_name_for_ws"

ADVANCED_OPTIONS = [
    CONF_APP_LAUNCH_METHOD,
    CONF_DUMP_APPS,
    CONF_EXT_POWER_ENTITY,
    CONF_PING_PORT,
    CONF_WOL_REPEAT,
    CONF_TOGGLE_ART_MODE,
    CONF_USE_MUTE_CHECK,
]

ENUM_OPTIONS = [
    CONF_APP_LOAD_METHOD,
    CONF_APP_LAUNCH_METHOD,
    CONF_LOGO_OPTION,
    CONF_POWER_ON_METHOD,
]

_LOGGER = logging.getLogger(__name__)


def _get_ip(host):
    if host is None:
        return None
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None


class SamsungTVConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Samsung TV config flow."""

    VERSION = 1

    # pylint: disable=no-member # https://github.com/PyCQA/pylint/issues/3167

    def __init__(self) -> None:
        """Initialize flow."""
        self._user_data = None
        self._st_devices_schema = None

        self._tv_info: SamsungTVInfo | None = None
        self._host = None
        self._api_key = None
        self._st_api_key = None
        self._use_st_api_key = False
        self._device_id = None
        self._name = None
        self._ws_name = None
        self._logo_option = None
        self._device_info = {}
        self._token = None
        self._ping_port = None
        self._error: str | None = None

    def _stdev_already_used(self, devices_id) -> bool:
        """Check if a device_id is in HA config."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_DEVICE_ID, "") == devices_id:
                return True
        return False

    def _remove_stdev_used(self, devices_list: Dict[str, Any]) -> Dict[str, Any]:
        """Remove entry already used"""
        res_dev_list = devices_list.copy()

        for dev_id in devices_list.keys():
            if self._stdev_already_used(dev_id):
                res_dev_list.pop(dev_id)
        return res_dev_list

    @staticmethod
    def _extract_dev_name(device) -> str:
        """Extract device neme from SmartThings Info"""
        name = device["name"]
        label = device.get("label", "")
        if label:
            name += f" ({label})"
        return name

    def _prepare_dev_schema(self, devices_list) -> vol.Schema:
        """Prepare the schema for select correct ST device"""
        validate = {}
        for dev_id, infos in devices_list.items():
            device_name = self._extract_dev_name(infos)
            validate[dev_id] = device_name
        return vol.Schema({vol.Required(CONF_ST_DEVICE): vol.In(validate)})

    async def _get_st_deviceid(self, st_device_label="") -> str:
        """Try to detect SmartThings device id."""
        session = async_get_clientsession(self.hass)
        devices_list = await SamsungTVInfo.get_st_devices(
            self._api_key, session, st_device_label
        )
        if devices_list is None:
            return RESULT_WRONG_APIKEY

        devices_list = self._remove_stdev_used(devices_list)
        if devices_list:
            if len(devices_list) > 1:
                self._st_devices_schema = self._prepare_dev_schema(devices_list)
            else:
                self._device_id = list(devices_list.keys())[0]

        return RESULT_SUCCESS

    async def _try_connect(self) -> str:
        """Try to connect and check auth."""
        self._tv_info = SamsungTVInfo(self.hass, self._host, self._ws_name)

        session = async_get_clientsession(self.hass)
        result = await self._tv_info.try_connect(
            session, self._api_key, self._device_id
        )
        if result == RESULT_SUCCESS:
            self._token = self._tv_info.ws_token
            self._ping_port = self._tv_info.ping_port
            self._device_info = await get_device_info(self._host, session)

        return result

    @callback
    def _get_api_key(self) -> str | None:
        """Get api key in configured entries if available."""
        for entry in self._async_current_entries():
            if CONF_API_KEY in entry.data:
                if not entry.data.get(CONF_USE_ST_INT_API_KEY):
                    return entry.data[CONF_API_KEY]
        return None

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""

        if not is_valid_ha_version():
            return self.async_abort(
                reason="unsupported_version",
                description_placeholders={
                    "req_ver": __min_ha_version__,
                    "run_ver": __version__,
                },
            )

        if not self._user_data:
            if api_key := self._get_api_key():
                self._user_data = {CONF_API_KEY: api_key}
            self._st_api_key = get_smartthing_api_key(self.hass)

        if user_input is None:
            return self._show_form()

        self._user_data = user_input
        ip_address = await self.hass.async_add_executor_job(
            _get_ip, user_input[CONF_HOST]
        )
        if not ip_address:
            return self._show_form(errors="invalid_host")

        self._async_abort_entries_match({CONF_HOST: ip_address})

        self._host = ip_address
        self._name = user_input[CONF_NAME]
        self._api_key = user_input.get(CONF_API_KEY)
        self._use_st_api_key = user_input.get(CONF_USE_ST_INT_API_KEY)
        if self._use_st_api_key:
            self._api_key = self._st_api_key

        use_ha_name = user_input.get(CONF_USE_HA_NAME, False)
        if use_ha_name:
            ha_conf = self.hass.config
            if hasattr(ha_conf, "location_name"):
                self._ws_name = ha_conf.location_name
        if not self._ws_name:
            self._ws_name = self._name

        result = RESULT_SUCCESS
        if self._api_key:
            result = await self._get_st_deviceid()

            if result == RESULT_SUCCESS and not self._device_id:
                if self._st_devices_schema:
                    return await self.async_step_stdevice()
                return await self.async_step_stdeviceid()

        if result == RESULT_SUCCESS:
            result = await self._try_connect()

        return await self._manage_result(result, True)

    async def async_step_stdevice(self, user_input=None) -> ConfigFlowResult:
        """Handle a flow to select ST device."""
        if user_input is None:
            return self._show_form(step_id="stdevice")

        self._device_id = user_input.get(CONF_ST_DEVICE)

        result = await self._try_connect()
        return await self._manage_result(result)

    async def async_step_stdeviceid(self, user_input=None) -> ConfigFlowResult:
        """Handle a flow to manual input a ST device."""
        if user_input is None:
            return self._show_form(step_id="stdeviceid")

        device_id = user_input.get(CONF_DEVICE_ID)
        if self._stdev_already_used(device_id):
            return self._show_form(errors=RESULT_ST_DEVICE_USED, step_id="stdeviceid")

        self._device_id = device_id

        result = await self._try_connect()
        if result == RESULT_ST_DEVICE_NOT_FOUND:
            return self._show_form(errors=result, step_id="stdeviceid")
        return await self._manage_result(result)

    async def _manage_result(self, result: str, is_user_step=False) -> ConfigFlowResult:
        """Manage the previous result."""

        if result != RESULT_SUCCESS:
            self._error = result
            if result == RESULT_ST_DEVICE_NOT_FOUND:
                return await self.async_step_stdeviceid()
            if is_user_step:
                return self._show_form()
            return await self.async_step_user()

        updates = {}
        if mac := self._device_info.get(ATTR_DEVICE_MAC):
            updates[CONF_MAC] = mac

        if ATTR_DEVICE_ID in self._device_info:
            unique_id = self._device_info[ATTR_DEVICE_ID]
        else:
            unique_id = mac or self._host

        if unique_id != self._host:
            updates[CONF_HOST] = self._host

        if entry := await self.async_set_unique_id(unique_id):
            if CONF_API_KEY in entry.data:
                if self._api_key and not self._use_st_api_key:
                    updates[CONF_API_KEY] = self._api_key
                if CONF_USE_ST_INT_API_KEY in self.data or self._use_st_api_key:
                    updates[CONF_USE_ST_INT_API_KEY] = self._use_st_api_key

        self._abort_if_unique_id_configured(updates or None)

        return self._save_entry()

    @callback
    def _save_entry(self) -> ConfigFlowResult:
        """Generate new entry."""
        data = {
            CONF_HOST: self._host,
            CONF_NAME: self._name,
            CONF_PORT: self._tv_info.ws_port,
            CONF_WS_NAME: self._ws_name,
        }
        if self._token:
            data[CONF_TOKEN] = self._token

        for key, attr in {
            CONF_ID: ATTR_DEVICE_ID,
            CONF_DEVICE_NAME: ATTR_DEVICE_NAME,
            CONF_DEVICE_MODEL: ATTR_DEVICE_MODEL,
            CONF_DEVICE_OS: ATTR_DEVICE_OS,
            CONF_MAC: ATTR_DEVICE_MAC,
        }.items():
            if attr in self._device_info:
                data[key] = self._device_info[attr]

        title = self._name
        if self._api_key and self._device_id:
            data[CONF_API_KEY] = self._api_key
            data[CONF_DEVICE_ID] = self._device_id
            if self._use_st_api_key:
                data[CONF_USE_ST_INT_API_KEY] = True
            title += " (SmartThings)"

        options = None
        if self._ping_port:
            options = {CONF_PING_PORT: self._ping_port}

        _LOGGER.info("Configured new entity %s with host %s", title, self._host)
        return self.async_create_entry(title=title, data=data, options=options)

    def _get_init_schema(self) -> vol.Schema:
        data = self._user_data or {}
        init_schema = {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required(CONF_NAME, default=data.get(CONF_NAME, "")): str,
            vol.Optional(
                CONF_USE_HA_NAME, default=data.get(CONF_USE_HA_NAME, False)
            ): bool,
            vol.Optional(
                CONF_API_KEY,
                description={"suggested_value": data.get(CONF_API_KEY, "")},
            ): str,
        }

        if self._st_api_key:
            init_schema.update(
                {
                    vol.Optional(
                        CONF_USE_ST_INT_API_KEY,
                        default=data.get(CONF_USE_ST_INT_API_KEY, False),
                    ): bool,
                }
            )

        return vol.Schema(init_schema)

    @callback
    def _show_form(self, errors: str | None = None, step_id="user") -> ConfigFlowResult:
        """Show the form to the user."""
        base_err = errors or self._error
        self._error = None

        if step_id == "stdevice":
            data_schema = self._st_devices_schema
        elif step_id == "stdeviceid":
            data_schema = vol.Schema({vol.Required(CONF_DEVICE_ID): str})
        else:
            data_schema = self._get_init_schema()

        return self.async_show_form(
            step_id=step_id,
            data_schema=data_schema,
            errors={CONF_BASE: base_err} if base_err else None,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    """Handle an option flow for Samsung TV Smart."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry_id = config_entry.entry_id
        self._adv_chk = False
        self._std_options = config_entry.options.copy()
        self._adv_options = {
            key: values
            for key, values in config_entry.options.items()
            if key in ADVANCED_OPTIONS
        }
        self._sync_ent_opt = {
            key: values
            for key, values in config_entry.options.items()
            if key in [CONF_SYNC_TURN_OFF, CONF_SYNC_TURN_ON]
        }
        self._app_list = self._std_options.get(CONF_APP_LIST)
        self._channel_list = self._std_options.get(CONF_CHANNEL_LIST)
        self._source_list = self._std_options.get(CONF_SOURCE_LIST)
        api_key = config_entry.data.get(CONF_API_KEY)
        st_dev = config_entry.data.get(CONF_DEVICE_ID)
        self._use_st = api_key and st_dev

    @callback
    def _save_entry(self, data) -> ConfigFlowResult:
        """Save configuration options"""
        data.update(self._adv_options)
        data.update(self._sync_ent_opt)
        entry_data = {k: v for k, v in data.items() if v is not None}
        for key, value in entry_data.items():
            if key in ENUM_OPTIONS:
                entry_data[key] = int(value)
        entry_data[CONF_APP_LIST] = self._app_list or {}
        entry_data[CONF_CHANNEL_LIST] = self._channel_list or {}
        entry_data[CONF_SOURCE_LIST] = self._source_list or {}

        return self.async_create_entry(title="", data=entry_data)

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Handle initial options flow."""
        if user_input is not None:
            if self._adv_chk or user_input.pop(CONF_SHOW_ADV_OPT, False):
                self._adv_chk = True
                self._std_options = user_input
                return await self.async_step_menu()
            return self._save_entry(data=user_input)
        return self._async_option_form()

    @callback
    def _async_option_form(self):
        """Return configuration form for options."""
        options = _validate_options(self._std_options)

        opt_schema = {
            vol.Required(
                CONF_LOGO_OPTION,
                default=options.get(CONF_LOGO_OPTION, str(LOGO_OPTION_DEFAULT.value)),
            ): SelectSelector(_dict_to_select(LOGO_OPTIONS)),
            vol.Required(
                CONF_USE_LOCAL_LOGO,
                default=options.get(CONF_USE_LOCAL_LOGO, True),
            ): bool,
        }

        if not self._app_list:
            opt_schema.update(
                {
                    vol.Required(
                        CONF_APP_LOAD_METHOD,
                        default=options.get(
                            CONF_APP_LOAD_METHOD, str(AppLoadMethod.All.value)
                        ),
                    ): SelectSelector(_dict_to_select(APP_LOAD_METHODS)),
                }
            )

        if self._use_st:
            data_schema = vol.Schema(
                {
                    vol.Required(
                        CONF_USE_ST_STATUS_INFO,
                        default=options.get(CONF_USE_ST_STATUS_INFO, True),
                    ): bool,
                    vol.Required(
                        CONF_USE_ST_CHANNEL_INFO,
                        default=options.get(CONF_USE_ST_CHANNEL_INFO, True),
                    ): bool,
                    vol.Required(
                        CONF_SHOW_CHANNEL_NR,
                        default=options.get(CONF_SHOW_CHANNEL_NR, False),
                    ): bool,
                }
            ).extend(opt_schema)
            data_schema = data_schema.extend(
                {
                    vol.Required(
                        CONF_POWER_ON_METHOD,
                        default=options.get(
                            CONF_POWER_ON_METHOD, str(PowerOnMethod.WOL.value)
                        ),
                    ): SelectSelector(_dict_to_select(POWER_ON_METHODS)),
                }
            )
        else:
            data_schema = vol.Schema(opt_schema)

        if not self._adv_chk:
            data_schema = data_schema.extend(
                {vol.Required(CONF_SHOW_ADV_OPT, default=False): bool}
            )

        return self.async_show_form(step_id="init", data_schema=data_schema)

    async def async_step_menu(self, _=None):
        """Handle advanced options menu."""
        return self.async_show_menu(
            step_id="menu",
            menu_options=[
                "source_list",
                "app_list",
                "channel_list",
                "sync_ent",
                "init",
                "adv_opt",
                "save_exit",
            ],
        )

    async def async_step_save_exit(self, _) -> ConfigFlowResult:
        """Handle save and exit flow."""
        return self._save_entry(data=self._std_options)

    async def async_step_source_list(self, user_input=None):
        """Handle sources list flow."""
        errors: dict[str, str] | None = None
        if user_input is not None:
            valid_list = _validate_tv_list(user_input[CONF_SOURCE_LIST])
            if valid_list is not None:
                self._source_list = valid_list
                return await self.async_step_menu()
            errors = {CONF_BASE: "invalid_tv_list"}

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SOURCE_LIST, default=self._source_list
                ): ObjectSelector()
            }
        )
        return self.async_show_form(
            step_id="source_list", data_schema=data_schema, errors=errors
        )

    async def async_step_app_list(self, user_input=None) -> ConfigFlowResult:
        """Handle apps list flow."""
        errors: dict[str, str] | None = None
        if user_input is not None:
            valid_list = _validate_tv_list(user_input[CONF_APP_LIST])
            if valid_list is not None:
                self._app_list = valid_list
                return await self.async_step_menu()
            errors = {CONF_BASE: "invalid_tv_list"}

        data_schema = vol.Schema(
            {vol.Optional(CONF_APP_LIST, default=self._app_list): ObjectSelector()}
        )
        return self.async_show_form(
            step_id="app_list", data_schema=data_schema, errors=errors
        )

    async def async_step_channel_list(self, user_input=None) -> ConfigFlowResult:
        """Handle channels list flow."""
        errors: dict[str, str] | None = None
        if user_input is not None:
            valid_list = _validate_tv_list(user_input[CONF_CHANNEL_LIST])
            if valid_list is not None:
                self._channel_list = valid_list
                return await self.async_step_menu()
            errors = {CONF_BASE: "invalid_tv_list"}

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CHANNEL_LIST, default=self._channel_list
                ): ObjectSelector()
            }
        )
        return self.async_show_form(
            step_id="channel_list", data_schema=data_schema, errors=errors
        )

    async def async_step_sync_ent(self, user_input=None) -> ConfigFlowResult:
        """Handle syncronized entity flow."""
        if user_input is not None:
            self._sync_ent_opt = user_input
            return await self.async_step_menu()
        return self._async_sync_ent_form()

    @callback
    def _async_sync_ent_form(self) -> ConfigFlowResult:
        """Return configuration form for syncronized entity."""
        select_entities = EntitySelectorConfig(
            domain=_async_get_domains_service(self.hass, SERVICE_TURN_ON),
            exclude_entities=_async_get_entry_entities(self.hass, self._entry_id),
            multiple=True,
        )
        options = _validate_options(self._sync_ent_opt)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SYNC_TURN_OFF,
                    description={
                        "suggested_value": options.get(CONF_SYNC_TURN_OFF, [])
                    },
                ): EntitySelector(select_entities),
                vol.Optional(
                    CONF_SYNC_TURN_ON,
                    description={"suggested_value": options.get(CONF_SYNC_TURN_ON, [])},
                ): EntitySelector(select_entities),
            }
        )
        return self.async_show_form(step_id="sync_ent", data_schema=data_schema)

    async def async_step_adv_opt(self, user_input=None) -> ConfigFlowResult:
        """Handle advanced options flow."""
        if user_input is not None:
            self._adv_options = user_input
            return await self.async_step_menu()
        return self._async_adv_opt_form()

    @callback
    def _async_adv_opt_form(self) -> ConfigFlowResult:
        """Return configuration form for advanced options."""
        select_entities = EntitySelectorConfig(domain=BS_DOMAIN)
        options = _validate_options(self._adv_options)

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_APP_LAUNCH_METHOD,
                    default=options.get(
                        CONF_APP_LAUNCH_METHOD, str(AppLaunchMethod.Standard.value)
                    ),
                ): SelectSelector(_dict_to_select(APP_LAUNCH_METHODS)),
                vol.Required(
                    CONF_WOL_REPEAT,
                    default=min(options.get(CONF_WOL_REPEAT, 1), MAX_WOL_REPEAT),
                ): vol.All(vol.Coerce(int), vol.Clamp(min=1, max=MAX_WOL_REPEAT)),
                vol.Required(
                    CONF_PING_PORT, default=options.get(CONF_PING_PORT, 0)
                ): vol.All(vol.Coerce(int), vol.Clamp(min=0, max=65535)),
                vol.Optional(
                    CONF_EXT_POWER_ENTITY,
                    description={
                        "suggested_value": options.get(CONF_EXT_POWER_ENTITY, "")
                    },
                ): EntitySelector(select_entities),
                vol.Required(
                    CONF_USE_MUTE_CHECK,
                    default=options.get(CONF_USE_MUTE_CHECK, False),
                ): bool,
                vol.Required(
                    CONF_DUMP_APPS,
                    default=options.get(CONF_DUMP_APPS, False),
                ): bool,
                vol.Required(
                    CONF_TOGGLE_ART_MODE,
                    default=options.get(CONF_TOGGLE_ART_MODE, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="adv_opt", data_schema=data_schema)


def _validate_options(options: dict) -> dict:
    """Validate options format"""
    valid_options = {}
    for opt_key, opt_val in options.items():
        if opt_key in [CONF_SYNC_TURN_OFF, CONF_SYNC_TURN_ON]:
            if not isinstance(opt_val, list):
                continue
        if opt_key in ENUM_OPTIONS:
            valid_options[opt_key] = str(opt_val)
        else:
            valid_options[opt_key] = opt_val
    return valid_options


def _validate_tv_list(input_list: dict[str, Any]) -> dict[str, str] | None:
    """Validate TV list from object selector."""
    valid_list = {}
    for name_val, id_val in input_list.items():
        if not id_val:
            continue
        if isinstance(id_val, Number):
            id_val = str(id_val)
        if not isinstance(id_val, str):
            return None
        valid_list[name_val] = id_val
    return valid_list


def _dict_to_select(opt_dict: dict) -> SelectSelectorConfig:
    """Covert a dict to a SelectSelectorConfig."""
    return SelectSelectorConfig(
        options=[SelectOptionDict(value=str(k), label=v) for k, v in opt_dict.items()],
        mode=SelectSelectorMode.DROPDOWN,
    )


def _async_get_domains_service(hass: HomeAssistant, service_name: str) -> list[str]:
    """Fetch list of domain that provide a specific service."""
    return [
        domain
        for domain, service in hass.services.async_services().items()
        if service_name in service
    ]


def _async_get_entry_entities(hass: HomeAssistant, entry_id: str) -> list[str]:
    """Get the entities related to current entry"""
    return [
        entry.entity_id
        for entry in (er.async_entries_for_config_entry(er.async_get(hass), entry_id))
    ]
