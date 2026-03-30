"""Config flow for Samsung TV Smart with OAuth2 support."""

from __future__ import annotations

import logging
from numbers import Number
import socket
from typing import Any, Dict

import voluptuous as vol

from homeassistant.components.binary_sensor import DOMAIN as BS_DOMAIN
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_REAUTH,
    SOURCE_USER,
    ConfigEntry,
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
from homeassistant.helpers import config_entry_oauth2_flow, entity_registry as er
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
    get_smartthings_api_key,
    get_smartthings_entries,
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
    CONF_AUTH_METHOD,
    CONF_CHANNEL_LIST,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_DEVICE_OS,
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
    DOMAIN,
    MAX_WOL_REPEAT,
    RESULT_ST_DEVICE_NOT_FOUND,
    RESULT_ST_DEVICE_USED,
    RESULT_SUCCESS,
    RESULT_WRONG_APIKEY,
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_PAT,
    AUTH_METHOD_ST_ENTRY,
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
CONF_AUTH_METHOD_SELECT = "auth_method"

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


class SamsungTVSmartOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Handle Samsung TV Smart config flow with OAuth2 support."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""
        super().__init__()
        self._user_data = None
        self._st_devices_schema = None
        self._tv_info: SamsungTVInfo | None = None
        self._host = None
        self._api_key = None
        self._st_entry_unique_id = None
        self._device_id = None
        self._name = None
        self._ws_name = None
        self._logo_option = None
        self._device_info = {}
        self._token = None
        self._ping_port = None
        self._error: str | None = None
        self._auth_method = AUTH_METHOD_PAT
        self._oauth_data: dict | None = None
        self._reauth_entry: ConfigEntry | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data to include in the authorize URL."""
        # SmartThings requires these scopes
        return {"scope": "r:devices:* x:devices:*"}

    def _stdev_already_used(self, devices_id) -> bool:
        """Check if a device_id is in HA config."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_DEVICE_ID, "") == devices_id:
                return True
        return False

    def _remove_stdev_used(self, devices_list: Dict[str, Any]) -> Dict[str, Any]:
        """Remove entry already used."""
        res_dev_list = devices_list.copy()
        for dev_id in devices_list.keys():
            if self._stdev_already_used(dev_id):
                res_dev_list.pop(dev_id)
        return res_dev_list

    @staticmethod
    def _extract_dev_name(device) -> str:
        """Extract device name from SmartThings Info."""
        name = device["name"]
        label = device.get("label", "")
        if label:
            name += f" ({label})"
        return name

    def _prepare_dev_schema(self, devices_list) -> vol.Schema:
        """Prepare the schema for select correct ST device."""
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

    async def _try_connect(self, *, port=None, token=None, skip_info=False) -> str:
        """Try to connect and check auth."""
        self._tv_info = SamsungTVInfo(self.hass, self._host, self._ws_name)
        session = async_get_clientsession(self.hass)
        result = await self._tv_info.try_connect(
            session, self._api_key, self._device_id, ws_port=port, ws_token=token
        )
        if result == RESULT_SUCCESS:
            self._token = self._tv_info.ws_token
            self._ping_port = self._tv_info.ping_port
            if not skip_info:
                self._device_info = await get_device_info(self._host, session)
        return result

    async def _validate_smartthings_token(self, api_key: str) -> bool:
        """Validate SmartThings PAT token by making a test API call."""
        if not api_key:
            return True
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                "https://api.smartthings.com/v1/devices",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            ) as resp:
                if resp.status == 200:
                    return True
                _LOGGER.warning(
                    "SmartThings token validation failed with status %s", resp.status
                )
                return False
        except Exception as ex:
            _LOGGER.warning("SmartThings token validation error: %s", ex)
            return False

    @callback
    def _get_api_key(self) -> str | None:
        """Get api key in configured entries if available."""
        for entry in self._async_current_entries():
            if CONF_API_KEY in entry.data:
                if not entry.data.get(CONF_ST_ENTRY_UNIQUE_ID):
                    return entry.data[CONF_API_KEY]
        return None

    async def _async_oauth_available(self) -> bool:
        """Check if OAuth credentials are configured."""
        try:
            implementations = await config_entry_oauth2_flow.async_get_implementations(
                self.hass, DOMAIN
            )
            return bool(implementations)
        except Exception:
            return False

    # =========================================================================
    # Main flow steps
    # =========================================================================

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if not is_valid_ha_version():
            return self.async_abort(
                reason="unsupported_version",
                description_placeholders={
                    "req_ver": __min_ha_version__,
                    "run_ver": __version__,
                },
            )

        oauth_available = await self._async_oauth_available()
        st_entries = get_smartthings_entries(self.hass)

        if user_input is not None:
            self._auth_method = user_input.get(CONF_AUTH_METHOD_SELECT, AUTH_METHOD_PAT)

            if self._auth_method == AUTH_METHOD_OAUTH:
                if not oauth_available:
                    return self.async_abort(reason="oauth_not_configured")
                # Start OAuth flow
                return await self.async_step_pick_implementation()

            elif self._auth_method == AUTH_METHOD_ST_ENTRY:
                if not st_entries:
                    return self.async_abort(reason="no_smartthings_integration")
                return await self.async_step_st_integration()

            else:  # PAT
                return await self.async_step_manual()

        # Build auth method options
        auth_options = {}
        if oauth_available:
            auth_options[AUTH_METHOD_OAUTH] = "🔐 OAuth2 (Recommended)"
        auth_options[AUTH_METHOD_PAT] = "🔑 Personal Access Token (PAT)"
        if st_entries:
            auth_options[AUTH_METHOD_ST_ENTRY] = "🔗 Use SmartThings Integration"

        # Default to OAuth if available, otherwise PAT
        default_method = AUTH_METHOD_OAUTH if oauth_available else AUTH_METHOD_PAT

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_AUTH_METHOD_SELECT, default=default_method
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=k, label=v)
                            for k, v in auth_options.items()
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }),
            description_placeholders={
                "oauth_status": "✓ Configured" if oauth_available else "✗ Not configured - Add credentials in Settings → Application Credentials",
            },
        )

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create entry from OAuth2 flow completion."""
        # OAuth completed successfully, store token and proceed to host config
        self._oauth_data = data
        self._api_key = data["token"]["access_token"]
        self._auth_method = AUTH_METHOD_OAUTH
        _LOGGER.info("OAuth authentication successful")

        # If this is a reauth, update the entry
        if self._reauth_entry:
            return await self._async_finish_reauth()

        # Otherwise, proceed to host configuration
        return await self.async_step_host()

    async def async_step_host(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure TV host after OAuth."""
        errors = {}

        if user_input is not None:
            ip_address = await self.hass.async_add_executor_job(
                _get_ip, user_input[CONF_HOST]
            )
            if not ip_address:
                errors["base"] = "invalid_host"
            else:
                self._async_abort_entries_match({CONF_HOST: ip_address})
                self._host = ip_address
                self._name = user_input[CONF_NAME]

                use_ha_name = user_input.get(CONF_USE_HA_NAME, False)
                if use_ha_name:
                    ha_conf = self.hass.config
                    if hasattr(ha_conf, "location_name"):
                        self._ws_name = ha_conf.location_name
                if not self._ws_name:
                    self._ws_name = self._name

                # Try to find SmartThings device
                result = await self._get_st_deviceid()
                if result == RESULT_SUCCESS:
                    if not self._device_id:
                        if self._st_devices_schema:
                            return await self.async_step_stdevice()
                        return await self.async_step_stdeviceid()

                    # Connect to TV
                    result = await self._try_connect()
                    return await self._manage_result(result, True)
                else:
                    errors["base"] = result

        return self.async_show_form(
            step_id="host",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_NAME): str,
                vol.Optional(CONF_USE_HA_NAME, default=False): bool,
            }),
            errors=errors if errors else None,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual configuration with PAT."""
        if not self._user_data:
            if api_key := self._get_api_key():
                self._user_data = {CONF_API_KEY: api_key}

        if user_input is None:
            return self._show_manual_form()

        self._user_data = user_input
        ip_address = await self.hass.async_add_executor_job(
            _get_ip, user_input[CONF_HOST]
        )
        if not ip_address:
            return self._show_manual_form(errors="invalid_host")

        self._async_abort_entries_match({CONF_HOST: ip_address})

        self._host = ip_address
        self._name = user_input[CONF_NAME]
        api_key = user_input.get(CONF_API_KEY)
        st_entry_unique_id = user_input.get(CONF_ST_ENTRY_UNIQUE_ID)
        
        if api_key and st_entry_unique_id:
            return self._show_manual_form(errors="only_key_or_st")

        self._st_entry_unique_id = None
        if st_entry_unique_id:
            if not (api_key := get_smartthings_api_key(self.hass, st_entry_unique_id)):
                return self._show_manual_form(errors="st_api_key_fail")
            self._st_entry_unique_id = st_entry_unique_id

        self._api_key = api_key
        self._auth_method = AUTH_METHOD_PAT

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

    async def async_step_st_integration(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuration using SmartThings integration token."""
        st_entries = get_smartthings_entries(self.hass)

        if not st_entries:
            return self.async_abort(reason="no_smartthings_integration")

        if user_input is not None:
            st_entry_unique_id = user_input.get("st_entry")
            ip_address = await self.hass.async_add_executor_job(
                _get_ip, user_input[CONF_HOST]
            )
            
            if not ip_address:
                return self.async_show_form(
                    step_id="st_integration",
                    data_schema=self._get_st_integration_schema(st_entries),
                    errors={"base": "invalid_host"},
                )

            self._async_abort_entries_match({CONF_HOST: ip_address})

            api_key = get_smartthings_api_key(self.hass, st_entry_unique_id)
            if not api_key:
                return self.async_show_form(
                    step_id="st_integration",
                    data_schema=self._get_st_integration_schema(st_entries),
                    errors={"base": "st_api_key_fail"},
                )

            self._host = ip_address
            self._name = user_input[CONF_NAME]
            self._api_key = api_key
            self._st_entry_unique_id = st_entry_unique_id
            self._auth_method = AUTH_METHOD_ST_ENTRY
            self._ws_name = self._name

            result = await self._get_st_deviceid()
            if result == RESULT_SUCCESS:
                if not self._device_id:
                    if self._st_devices_schema:
                        return await self.async_step_stdevice()
                    return await self.async_step_stdeviceid()
                result = await self._try_connect()
                return await self._manage_result(result, True)
            else:
                return self.async_show_form(
                    step_id="st_integration",
                    data_schema=self._get_st_integration_schema(st_entries),
                    errors={"base": result},
                )

        return self.async_show_form(
            step_id="st_integration",
            data_schema=self._get_st_integration_schema(st_entries),
        )

    def _get_st_integration_schema(self, st_entries: dict) -> vol.Schema:
        """Return schema for ST integration selection."""
        return vol.Schema({
            vol.Required("st_entry"): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=k, label=v)
                        for k, v in st_entries.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_NAME): str,
        })

    async def async_step_stdevice(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow to select ST device."""
        if user_input is None:
            return self.async_show_form(
                step_id="stdevice",
                data_schema=self._st_devices_schema,
            )

        self._device_id = user_input.get(CONF_ST_DEVICE)
        result = await self._try_connect()
        return await self._manage_result(result)

    async def async_step_stdeviceid(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow to manual input a ST device."""
        if user_input is None:
            return self.async_show_form(
                step_id="stdeviceid",
                data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): str}),
            )

        device_id = user_input.get(CONF_DEVICE_ID)
        if self._stdev_already_used(device_id):
            return self.async_show_form(
                step_id="stdeviceid",
                data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): str}),
                errors={"base": RESULT_ST_DEVICE_USED},
            )

        self._device_id = device_id
        result = await self._try_connect()
        if result == RESULT_ST_DEVICE_NOT_FOUND:
            return self.async_show_form(
                step_id="stdeviceid",
                data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): str}),
                errors={"base": result},
            )
        return await self._manage_result(result)

    # =========================================================================
    # Reconfigure and Reauth
    # =========================================================================

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the integration."""
        entry = self._get_reconfigure_entry()
        if entry.unique_id == entry.data[CONF_HOST]:
            return self.async_abort(reason="host_unique_id")

        if not self._ws_name:
            self._ws_name = entry.data[CONF_WS_NAME]
            if CONF_API_KEY in entry.data:
                self._device_id = entry.data.get(CONF_DEVICE_ID)

        if user_input is None:
            return self._show_reconfigure_form()

        ip_address = await self.hass.async_add_executor_job(
            _get_ip, user_input[CONF_HOST]
        )
        if not ip_address:
            return self._show_reconfigure_form(errors="invalid_host")

        self._async_abort_entries_match({CONF_HOST: ip_address})

        # Check if user wants to (re-)authenticate with OAuth
        if user_input.get("reauth_oauth"):
            self._reauth_entry = entry
            oauth_available = await self._async_oauth_available()
            if not oauth_available:
                return self.async_abort(reason="oauth_not_configured")
            return await self.async_step_pick_implementation()

        api_key = user_input.get(CONF_API_KEY)
        st_entry_unique_id = user_input.get(CONF_ST_ENTRY_UNIQUE_ID)
        if api_key and st_entry_unique_id:
            return self._show_reconfigure_form(errors="only_key_or_st")

        self._st_entry_unique_id = None
        if st_entry_unique_id:
            if not (api_key := get_smartthings_api_key(self.hass, st_entry_unique_id)):
                return self._show_reconfigure_form(errors="st_api_key_fail")
            self._st_entry_unique_id = st_entry_unique_id
        else:
            api_key = api_key or entry.data.get(CONF_API_KEY)

        self._host = ip_address
        self._api_key = api_key

        # Validate SmartThings token if provided
        if self._api_key:
            if not await self._validate_smartthings_token(self._api_key):
                return self._show_reconfigure_form(errors=RESULT_WRONG_APIKEY)

        result = await self._try_connect(
            port=entry.data.get(CONF_PORT),
            token=entry.data.get(CONF_TOKEN),
            skip_info=True,
        )
        return self._manage_reconfigure(result)

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication."""
        if user_input is not None:
            auth_method = self._reauth_entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_PAT)
            if auth_method == AUTH_METHOD_OAUTH:
                return await self.async_step_pick_implementation()
            else:
                return await self.async_step_manual()

        return self.async_show_form(step_id="reauth_confirm")

    async def _async_finish_reauth(self) -> ConfigFlowResult:
        """Finish reauth flow."""
        if not self._reauth_entry:
            return self.async_abort(reason="reauth_failed")

        self.hass.config_entries.async_update_entry(
            self._reauth_entry,
            data={
                **self._reauth_entry.data,
                CONF_API_KEY: self._oauth_data["token"]["access_token"],
                CONF_OAUTH_TOKEN: self._oauth_data["token"],
                CONF_AUTH_METHOD: AUTH_METHOD_OAUTH,
                # Store auth_implementation to enable token refresh
                "auth_implementation": DOMAIN,
            },
        )
        await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    # =========================================================================
    # Result management
    # =========================================================================

    async def _manage_result(self, result: str, is_user_step=False) -> ConfigFlowResult:
        """Manage the previous result."""
        if result != RESULT_SUCCESS:
            self._error = result
            if result == RESULT_ST_DEVICE_NOT_FOUND:
                return await self.async_step_stdeviceid()
            if is_user_step:
                if self._auth_method == AUTH_METHOD_OAUTH:
                    return await self.async_step_host()
                return self._show_manual_form()
            return await self.async_step_user()

        if ATTR_DEVICE_ID in self._device_info:
            unique_id = self._device_info[ATTR_DEVICE_ID]
        else:
            mac = self._device_info.get(ATTR_DEVICE_MAC)
            unique_id = mac or self._host

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self._save_entry()

    @callback
    def _manage_reconfigure(self, result: str) -> ConfigFlowResult:
        """Manage the reconfigure result."""
        if result != RESULT_SUCCESS:
            self._error = result
            return self._show_reconfigure_form()

        entry = self._get_reconfigure_entry()
        updates = {
            CONF_HOST: self._host,
            CONF_PORT: self._tv_info.ws_port,
        }
        if self._token:
            updates[CONF_TOKEN] = self._token

        if self._api_key:
            updates[CONF_API_KEY] = self._api_key
            if CONF_ST_ENTRY_UNIQUE_ID in entry.data or self._st_entry_unique_id:
                updates[CONF_ST_ENTRY_UNIQUE_ID] = self._st_entry_unique_id

        return self.async_update_reload_and_abort(
            entry, data_updates=updates, reload_even_if_entry_is_unchanged=False
        )

    @callback
    def _save_entry(self) -> ConfigFlowResult:
        """Generate new entry."""
        data = {
            CONF_HOST: self._host,
            CONF_NAME: self._name,
            CONF_PORT: self._tv_info.ws_port,
            CONF_WS_NAME: self._ws_name,
            CONF_AUTH_METHOD: self._auth_method,
        }
        if self._token:
            data[CONF_TOKEN] = self._token

        # Store OAuth token data if using OAuth
        if self._auth_method == AUTH_METHOD_OAUTH and self._oauth_data:
            data[CONF_OAUTH_TOKEN] = self._oauth_data["token"]
            # Store auth_implementation to enable token refresh
            # This is required for async_get_config_entry_implementation to work
            data["auth_implementation"] = DOMAIN

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
            if self._st_entry_unique_id:
                data[CONF_ST_ENTRY_UNIQUE_ID] = self._st_entry_unique_id
            if self._auth_method == AUTH_METHOD_OAUTH:
                title += " (OAuth)"
            else:
                title += " (SmartThings)"

        options = None
        if self._ping_port:
            options = {CONF_PING_PORT: self._ping_port}

        _LOGGER.info("Configured new entity %s with host %s", title, self._host)
        return self.async_create_entry(title=title, data=data, options=options)

    # =========================================================================
    # Form helpers
    # =========================================================================

    @callback
    def _show_manual_form(self, errors: str | None = None) -> ConfigFlowResult:
        """Show the manual configuration form."""
        base_err = errors or self._error
        self._error = None

        data = self._user_data or {}
        st_entries = get_smartthings_entries(self.hass)

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

        if st_entries:
            st_unique_id = data.get(CONF_ST_ENTRY_UNIQUE_ID)
            sugg_val = st_unique_id if st_unique_id in st_entries else None
            init_schema.update({
                vol.Optional(
                    CONF_ST_ENTRY_UNIQUE_ID,
                    description={"suggested_value": sugg_val},
                ): SelectSelector(_dict_to_select(st_entries)),
            })

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(init_schema),
            errors={CONF_BASE: base_err} if base_err else None,
        )

    @callback
    def _show_reconfigure_form(self, errors: str | None = None) -> ConfigFlowResult:
        """Show the reconfiguration form."""
        base_err = errors or self._error
        self._error = None

        entry = self._get_reconfigure_entry()
        data = entry.data
        st_entries = get_smartthings_entries(self.hass)

        current_auth = data.get(CONF_AUTH_METHOD, AUTH_METHOD_PAT)
        auth_label = {
            AUTH_METHOD_OAUTH: "OAuth2",
            AUTH_METHOD_PAT: "PAT",
            AUTH_METHOD_ST_ENTRY: "SmartThings Integration",
        }.get(current_auth, "Unknown")

        init_schema = {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
        }

        # Always show OAuth option - for switching to OAuth or re-authenticating
        # This allows users to get a fresh token even if already using OAuth
        init_schema[vol.Optional("reauth_oauth", default=False)] = bool

        # Show API key field (hidden if using OAuth, but kept for switching back)
        st_unique_id = data.get(CONF_ST_ENTRY_UNIQUE_ID)
        use_st_key = st_entries is not None and st_unique_id in st_entries
        # Don't show API key field if using OAuth
        if current_auth != AUTH_METHOD_OAUTH:
            sugg_val = data.get(CONF_API_KEY, "") if not use_st_key else ""
            init_schema[vol.Optional(
                CONF_API_KEY, description={"suggested_value": sugg_val}
            )] = str

            if st_entries:
                sugg_val = st_unique_id if use_st_key else None
                init_schema[vol.Optional(
                    CONF_ST_ENTRY_UNIQUE_ID,
                    description={"suggested_value": sugg_val},
                )] = SelectSelector(_dict_to_select(st_entries))

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(init_schema),
            errors={CONF_BASE: base_err} if base_err else None,
            description_placeholders={"current_auth": auth_label},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


# Alias for backward compatibility
SamsungTVConfigFlow = SamsungTVSmartOAuth2FlowHandler


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
        """Save configuration options."""
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
            opt_schema.update({
                vol.Required(
                    CONF_APP_LOAD_METHOD,
                    default=options.get(
                        CONF_APP_LOAD_METHOD, str(AppLoadMethod.All.value)
                    ),
                ): SelectSelector(_dict_to_select(APP_LOAD_METHODS)),
            })

        if self._use_st:
            data_schema = vol.Schema({
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
            }).extend(opt_schema)
            data_schema = data_schema.extend({
                vol.Required(
                    CONF_POWER_ON_METHOD,
                    default=options.get(
                        CONF_POWER_ON_METHOD, str(PowerOnMethod.WOL.value)
                    ),
                ): SelectSelector(_dict_to_select(POWER_ON_METHODS)),
            })
        else:
            data_schema = vol.Schema(opt_schema)

        if not self._adv_chk:
            data_schema = data_schema.extend({
                vol.Required(CONF_SHOW_ADV_OPT, default=False): bool
            })

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

        data_schema = vol.Schema({
            vol.Optional(
                CONF_SOURCE_LIST, default=self._source_list
            ): ObjectSelector()
        })
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

        data_schema = vol.Schema({
            vol.Optional(CONF_APP_LIST, default=self._app_list): ObjectSelector()
        })
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

        data_schema = vol.Schema({
            vol.Optional(
                CONF_CHANNEL_LIST, default=self._channel_list
            ): ObjectSelector()
        })
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

        data_schema = vol.Schema({
            vol.Optional(
                CONF_SYNC_TURN_OFF,
                description={"suggested_value": options.get(CONF_SYNC_TURN_OFF, [])},
            ): EntitySelector(select_entities),
            vol.Optional(
                CONF_SYNC_TURN_ON,
                description={"suggested_value": options.get(CONF_SYNC_TURN_ON, [])},
            ): EntitySelector(select_entities),
        })
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

        data_schema = vol.Schema({
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
                description={"suggested_value": options.get(CONF_EXT_POWER_ENTITY, "")},
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
        })
        return self.async_show_form(step_id="adv_opt", data_schema=data_schema)


# =========================================================================
# Helper functions
# =========================================================================

def _validate_options(options: dict) -> dict:
    """Validate options format."""
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
    """Convert a dict to a SelectSelectorConfig."""
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
    """Get the entities related to current entry."""
    return [
        entry.entity_id
        for entry in (er.async_entries_for_config_entry(er.async_get(hass), entry_id))
    ]
