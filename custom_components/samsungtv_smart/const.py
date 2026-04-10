"""Constants for the samsungtv_smart integration."""

from enum import Enum


class AppLoadMethod(Enum):
    """Valid application load methods."""

    All = 1
    Default = 2
    NotLoad = 3


class AppLaunchMethod(Enum):
    """Valid application launch methods."""

    Standard = 1
    Remote = 2
    Rest = 3


class PowerOnMethod(Enum):
    """Valid power on methods."""

    WOL = 1
    SmartThings = 2


DOMAIN = "samsungtv_smart"

MIN_HA_MAJ_VER = 2025
MIN_HA_MIN_VER = 6
__min_ha_version__ = f"{MIN_HA_MAJ_VER}.{MIN_HA_MIN_VER}.0"

DATA_CFG = "cfg"
DATA_CFG_YAML = "cfg_yaml"
DATA_OPTIONS = "options"
LOCAL_LOGO_PATH = "local_logo_path"
WS_PREFIX = "[Home Assistant]"

ATTR_DEVICE_MAC = "device_mac"
ATTR_DEVICE_MODEL = "device_model"
ATTR_DEVICE_NAME = "device_name"
ATTR_DEVICE_OS = "device_os"

CONF_APP_LAUNCH_METHOD = "app_launch_method"
CONF_APP_LIST = "app_list"
CONF_APP_LOAD_METHOD = "app_load_method"
CONF_CHANNEL_LIST = "channel_list"
CONF_DEVICE_MODEL = "device_model"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_OS = "device_os"
CONF_DUMP_APPS = "dump_apps"
CONF_EXT_POWER_ENTITY = "ext_power_entity"
CONF_LOAD_ALL_APPS = "load_all_apps"
CONF_LOGO_OPTION = "logo_option"
CONF_PING_PORT = "ping_port"
CONF_POWER_ON_METHOD = "power_on_method"
CONF_SHOW_CHANNEL_NR = "show_channel_number"
CONF_SOURCE_LIST = "source_list"
CONF_SYNC_TURN_OFF = "sync_turn_off"
CONF_SYNC_TURN_ON = "sync_turn_on"
CONF_TOGGLE_ART_MODE = "toggle_art_mode"
CONF_USE_LOCAL_LOGO = "use_local_logo"
CONF_USE_MUTE_CHECK = "use_mute_check"
CONF_USE_ST_CHANNEL_INFO = "use_st_channel_info"
CONF_USE_ST_STATUS_INFO = "use_st_status_info"
CONF_WOL_REPEAT = "wol_repeat"
CONF_WS_NAME = "ws_name"

# for SmartThings integration api key usage
CONF_ST_ENTRY_UNIQUE_ID = "st_entry_unique_id"
CONF_USE_ST_INT_API_KEY = "use_st_int_api_key"  # obsolete used for migration

# obsolete
CONF_UPDATE_METHOD = "update_method"
CONF_UPDATE_CUSTOM_PING_URL = "update_custom_ping_url"
CONF_SCAN_APP_HTTP = "scan_app_http"

DEFAULT_APP = "TV/HDMI"
DEFAULT_PORT = 8001
DEFAULT_SOURCE_LIST = {"TV": "KEY_TV", "HDMI": "KEY_HDMI"}
DEFAULT_TIMEOUT = 6

MAX_WOL_REPEAT = 5

RESULT_NOT_SUCCESSFUL = "not_successful"
RESULT_NOT_SUPPORTED = "not_supported"
RESULT_ST_DEVICE_USED = "st_device_used"
RESULT_ST_DEVICE_NOT_FOUND = "st_device_not_found"
RESULT_ST_MULTI_DEVICES = "st_multiple_device"
RESULT_SUCCESS = "success"
RESULT_WRONG_APIKEY = "wrong_api_key"

SERVICE_SELECT_PICTURE_MODE = "select_picture_mode"
SERVICE_SET_ART_MODE = "set_art_mode"

SIGNAL_CONFIG_ENTITY = f"{DOMAIN}_config"

STD_APP_LIST = {
    "org.tizen.browser": {
        "st_app_id": "",
        "logo": "tizenbrowser.png",
    },  # Internet
    "11101200001": {
        "st_app_id": "RN1MCdNq8t.Netflix",
        "logo": "netflix.png",
    },  # Netflix
    "3201907018807": {
        "st_app_id": "org.tizen.netflix-app",
        "logo": "netflix.png",
    },  # Netflix (New)
    "111299001912": {
        "st_app_id": "9Ur5IzDKqV.TizenYouTube",
        "logo": "youtube.png",
    },  # YouTube
    "3201512006785": {
        "st_app_id": "org.tizen.ignition",
        "logo": "primevideo.png",
    },  # Prime Video
    # "3201512006785": {
    #     "st_app_id": "evKhCgZelL.AmazonIgnitionLauncher2",
    #     "logo": "",
    # },  # Prime Video
    "3201910019365": {
        "st_app_id": "org.tizen.primevideo",
        "logo": "primevideo.png",
    },  # Prime Video (New)
    "3201901017640": {
        "st_app_id": "MCmYXNxgcu.DisneyPlus",
        "logo": "disneyplus.png",
    },  # Disney+
    "3202110025305": {
        "st_app_id": "rJyOSqC6Up.PPlusIntl",
        "logo": "paramountplus.png",
    },  # Paramount+
    "11091000000": {
        "st_app_id": "4ovn894vo9.Facebook",
        "logo": "facebook.png",
    },  # Facebook
    "3201806016390": {
        "st_app_id": "yu1NM3vHsU.DAZN",
        "logo": "dazn.png",
    },  # Dazn
    "3201601007250": {
        "st_app_id": "QizQxC7CUf.PlayMovies",
        "logo": "",
    },  # Google Play
    "3201606009684": {
        "st_app_id": "rJeHak5zRg.Spotify",
        "logo": "spotify.png",
    },  # Spotify
    "3201512006963": {
        "st_app_id": "kIciSQlYEM.plex",
        "logo": "",
    },  # Plex
}
