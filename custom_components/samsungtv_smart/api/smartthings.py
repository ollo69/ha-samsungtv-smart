"""SmartThings TV integration using pysmartthings library (v6.0)."""

from __future__ import annotations

from asyncio import TimeoutError as AsyncTimeoutError
from collections.abc import Callable
from datetime import timedelta
from enum import Enum
import logging

from aiohttp import ClientSession
from pysmartthings import SmartThings
from pysmartthings.command import Command

# Capability names as strings (pysmartthings v6.0+ compatibility)
# In older versions these were CAP_SWITCH, CAP_AUDIO_VOLUME, etc.
CAP_SWITCH = "switch"
CAP_AUDIO_VOLUME = "audioVolume"
CAP_AUDIO_MUTE = "audioMute"
CAP_TV_CHANNEL = "tvChannel"
CAP_MEDIA_INPUT_SOURCE = "mediaInputSource"

from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

# Device types
DEVICE_TYPE_OCF = "OCF"
DEVICE_TYPE_NAME_TV = "Samsung OCF TV"
DEVICE_TYPE_NAMES = ["Samsung OCF TV", "x.com.st.d.monitor"]


# Component name
COMPONENT_MAIN = "main"


class STStatus(Enum):
    """SmartThings status values."""

    STATE_ON = "on"
    STATE_OFF = "off"
    STATE_UNKNOWN = "unknown"


class SmartThingsTV:
    """Class to read status for TV registered in SmartThings cloud using pysmartthings."""

    def __init__(
        self,
        api_key: str,
        device_id: str,
        use_channel_info: bool = True,
        session: ClientSession | None = None,
        api_key_callback: Callable[[], str | None] | None = None,
    ):
        """Initialize SmartThingsTV with pysmartthings."""
        self._api_key = api_key
        self._device_id = device_id
        self._use_channel_info = use_channel_info
        self._api_key_callback = api_key_callback

        # Initialize pysmartthings
        self._st = SmartThings(session=session)
        self._st.authenticate(api_key)

        # State tracking
        self._device_name = None
        self._state = STStatus.STATE_UNKNOWN
        self._prev_state = STStatus.STATE_UNKNOWN
        self._muted = False
        self._volume = 10
        self._source_list = None
        self._source_list_map = None
        self._source = ""
        self._channel = ""
        self._channel_name = ""
        self._sound_mode = None
        self._sound_mode_list = None
        self._picture_mode = None
        self._picture_mode_list = None

        self._is_forced_val = False
        self._forced_count = 0

    def _get_api_key(self) -> str:
        """Get API key used to connect to SmartThings."""
        if self._api_key_callback is not None:
            if api_key := self._api_key_callback():
                self._api_key = api_key
                self._st.authenticate(api_key)
        return self._api_key

    # Properties
    @property
    def api_key(self) -> str:
        """Return current api_key."""
        return self._api_key

    @property
    def device_id(self) -> str:
        """Return current device_id."""
        return self._device_id

    @property
    def device_name(self) -> str | None:
        """Return device name."""
        return self._device_name

    @property
    def state(self) -> STStatus:
        """Return current state."""
        return self._state

    @property
    def prev_state(self) -> STStatus:
        """Return previous state."""
        return self._prev_state

    @property
    def muted(self) -> bool:
        """Return mute state."""
        return self._muted

    @property
    def volume(self) -> int:
        """Return volume level."""
        return self._volume

    @property
    def source(self) -> str:
        """Return current source."""
        return self._source

    @property
    def source_list(self) -> dict | None:
        """Return source list."""
        return self._source_list

    @property
    def channel(self) -> str:
        """Return current channel."""
        return self._channel

    @property
    def channel_name(self) -> str:
        """Return current channel name."""
        return self._channel_name

    @property
    def sound_mode(self) -> str | None:
        """Return current sound mode."""
        return self._sound_mode

    @property
    def sound_mode_list(self) -> list | None:
        """Return sound mode list."""
        return self._sound_mode_list

    @property
    def picture_mode(self) -> str | None:
        """Return current picture mode."""
        return self._picture_mode

    @property
    def picture_mode_list(self) -> list | None:
        """Return picture mode list."""
        return self._picture_mode_list

    def get_source_name(self, source_key: str) -> str:
        """Get source name from key."""
        if not self._source_list_map or source_key not in self._source_list_map:
            return source_key
        return self._source_list_map[source_key]

    # Helper methods
    def _set_source(self, source: str):
        """Set source value."""
        if self._state != STStatus.STATE_OFF:
            if source != self._source:
                self._source = source
                self._channel = ""
                self._channel_name = ""
                self._is_forced_val = True
                self._forced_count = 0

    def set_application(self, app_id: str):
        """Set running application info."""
        if self._use_channel_info:
            self._channel = ""
            self._channel_name = app_id
            self._is_forced_val = True
            self._forced_count = 0

    def _get_source_list_from_map(self) -> list:
        """Return source list from source map."""
        if not self._source_list_map:
            return []
        source_list = []
        for source_id in self._source_list_map:
            source_list.append(source_id)
        return source_list

    @staticmethod
    async def get_devices_list(api_key: str, session: ClientSession, device_label: str = "") -> dict:
        """Get list of available SmartThings devices using pysmartthings."""
        result = {}
        
        try:
            st = SmartThings(session=session)
            st.authenticate(api_key)
            devices = await st.get_devices()
            
            for dev in devices:
                if dev.type != DEVICE_TYPE_OCF:
                    continue
                
                if device_label and dev.label != device_label:
                    continue
                elif not device_label and dev.device_type_name not in DEVICE_TYPE_NAMES:
                    continue
                
                result[dev.device_id] = {
                    "name": dev.name or f"TV ID {dev.device_id}",
                    "label": dev.label or "",
                }
            
            _LOGGER.info("SmartThings discovered TV devices: %s", str(result))
            
        except Exception as err:
            _LOGGER.error("Error getting devices list: %s", err)
        
        return result

    @Throttle(timedelta(seconds=1))
    async def async_device_update(self, use_channel_info: bool = True):
        """Update device status using pysmartthings."""
        self._get_api_key()
        
        try:
            # Get device status using pysmartthings
            # Note: get_device_status() returns .components directly (dict, not DeviceStatus object)
            components = await self._st.get_device_status(self._device_id)
            
            if COMPONENT_MAIN not in components:
                _LOGGER.warning("Main component not found in device status")
                return

            main_comp = components[COMPONENT_MAIN]

            # Update device name
            if not self._device_name:
                try:
                    device = await self._st.get_device(self._device_id)
                    self._device_name = device.label or device.name
                except Exception as err:
                    _LOGGER.debug("Could not get device name: %s", err)

            # Update state - pysmartthings returns Status objects with .value attribute
            self._prev_state = self._state
            if "switch" in main_comp and "switch" in main_comp["switch"]:
                switch_value = main_comp["switch"]["switch"].value
                if switch_value == "on":
                    self._state = STStatus.STATE_ON
                elif switch_value == "off":
                    self._state = STStatus.STATE_OFF
                else:
                    self._state = STStatus.STATE_UNKNOWN
            else:
                self._state = STStatus.STATE_UNKNOWN

            # Update volume and mute
            if "audioVolume" in main_comp and "volume" in main_comp["audioVolume"]:
                self._volume = main_comp["audioVolume"]["volume"].value

            if "audioMute" in main_comp and "mute" in main_comp["audioMute"]:
                self._muted = main_comp["audioMute"]["mute"].value == "muted"

            # Update source
            if "mediaInputSource" in main_comp and "inputSource" in main_comp["mediaInputSource"]:
                self._source = main_comp["mediaInputSource"]["inputSource"].value

            # Update channel info if enabled
            if use_channel_info and self._state == STStatus.STATE_ON:
                if "tvChannel" in main_comp:
                    tv_channel = main_comp["tvChannel"]
                    if "tvChannel" in tv_channel:
                        self._channel = tv_channel["tvChannel"].value
                    if "tvChannelName" in tv_channel:
                        self._channel_name = tv_channel["tvChannelName"].value

            # Update source list
            if "mediaInputSource" in main_comp and "supportedInputSources" in main_comp["mediaInputSource"]:
                supported_inputs = main_comp["mediaInputSource"]["supportedInputSources"].value
                if supported_inputs:
                    self._source_list = {}
                    self._source_list_map = {}
                    for source in supported_inputs:
                        source_id = source.get("id", "")
                        source_name = source.get("name", source_id)
                        if source_id:
                            self._source_list[source_id] = source_name
                            self._source_list_map[source_id] = source_name

            # Update sound mode
            if "custom.soundmode" in main_comp:
                sound_mode_cap = main_comp["custom.soundmode"]
                if "soundMode" in sound_mode_cap:
                    self._sound_mode = sound_mode_cap["soundMode"].value
                if "supportedSoundModes" in sound_mode_cap:
                    self._sound_mode_list = sound_mode_cap["supportedSoundModes"].value

            # Update picture mode
            if "custom.picturemode" in main_comp:
                picture_mode_cap = main_comp["custom.picturemode"]
                if "pictureMode" in picture_mode_cap:
                    self._picture_mode = picture_mode_cap["pictureMode"].value
                if "supportedPictureModes" in picture_mode_cap:
                    self._picture_mode_list = picture_mode_cap["supportedPictureModes"].value

        except Exception as err:
            _LOGGER.error("Error updating SmartThings status: %s", err)
            raise

    async def async_device_health(self) -> str:
        """Get device health status using pysmartthings."""
        self._get_api_key()
        
        try:
            health = await self._st.get_device_health(self._device_id)
            return health.state
        except Exception as err:
            _LOGGER.error("Error getting device health: %s", err)
            return "UNKNOWN"

    async def async_turn_on(self):
        """Turn device on using pysmartthings."""
        self._get_api_key()
        try:
            cmd = Command(component_id=COMPONENT_MAIN, capability=CAP_SWITCH, command="on")
            await self._st.execute_device_command(self._device_id, [cmd])
            self._state = STStatus.STATE_ON
        except Exception as err:
            _LOGGER.error("Error turning on device: %s", err)
            raise

    async def async_turn_off(self):
        """Turn device off using pysmartthings."""
        self._get_api_key()
        try:
            cmd = Command(component_id=COMPONENT_MAIN, capability=CAP_SWITCH, command="off")
            await self._st.execute_device_command(self._device_id, [cmd])
            self._state = STStatus.STATE_OFF
        except Exception as err:
            _LOGGER.error("Error turning off device: %s", err)
            raise

    async def async_send_command(self, cmd_type: str, command: str = ""):
        """Send a command to the device using pysmartthings."""
        self._get_api_key()
        
        try:
            if cmd_type == "setvolume":
                cmd = Command(
                    component_id=COMPONENT_MAIN,
                    capability=CAP_AUDIO_VOLUME,
                    command="setVolume",
                    arguments=[int(command)]
                )
            elif cmd_type == "stepvolume":
                cmd_name = "volumeUp" if command == "up" else "volumeDown"
                cmd = Command(
                    component_id=COMPONENT_MAIN,
                    capability=CAP_AUDIO_VOLUME,
                    command=cmd_name
                )
            elif cmd_type == "audiomute":
                cmd_name = "mute" if command == "on" else "unmute"
                cmd = Command(
                    component_id=COMPONENT_MAIN,
                    capability=CAP_AUDIO_MUTE,
                    command=cmd_name
                )
            elif cmd_type == "selectchannel":
                cmd = Command(
                    component_id=COMPONENT_MAIN,
                    capability=CAP_TV_CHANNEL,
                    command="setTvChannel",
                    arguments=[command]
                )
            elif cmd_type == "stepchannel":
                cmd_name = "channelUp" if command == "up" else "channelDown"
                cmd = Command(
                    component_id=COMPONENT_MAIN,
                    capability=CAP_TV_CHANNEL,
                    command=cmd_name
                )
            else:
                _LOGGER.warning("Unknown command type: %s", cmd_type)
                return

            await self._st.execute_device_command(self._device_id, [cmd])
            
        except Exception as err:
            _LOGGER.error("Error sending command %s: %s", cmd_type, err)
            raise

    async def async_select_source(self, source: str):
        """Select source using pysmartthings."""
        self._get_api_key()
        try:
            cmd = Command(
                component_id=COMPONENT_MAIN,
                capability=CAP_MEDIA_INPUT_SOURCE,
                command="setInputSource",
                arguments=[source]
            )
            await self._st.execute_device_command(self._device_id, [cmd])
            self._set_source(source)
        except Exception as err:
            _LOGGER.error("Error selecting source: %s", err)
            raise

    async def async_select_vd_source(self, source: str):
        """Select VD source using pysmartthings."""
        self._get_api_key()
        try:
            cmd = Command(
                component_id=COMPONENT_MAIN,
                capability="samsungvd.mediaInputSource",
                command="setInputSource",
                arguments=[source]
            )
            await self._st.execute_device_command(self._device_id, [cmd])
        except Exception as err:
            _LOGGER.error("Error selecting VD source: %s", err)
            raise

    async def async_set_sound_mode(self, mode: str):
        """Select sound mode using pysmartthings."""
        if self._state != STStatus.STATE_ON:
            return
        if self._sound_mode_list and mode not in self._sound_mode_list:
            raise InvalidSmartThingsSoundMode()
        
        self._get_api_key()
        try:
            cmd = Command(
                component_id=COMPONENT_MAIN,
                capability="custom.soundmode",
                command="setSoundMode",
                arguments=[mode]
            )
            await self._st.execute_device_command(self._device_id, [cmd])
            self._sound_mode = mode
        except Exception as err:
            _LOGGER.error("Error setting sound mode: %s", err)
            raise

    async def async_set_picture_mode(self, mode: str):
        """Select picture mode using pysmartthings."""
        if self._state != STStatus.STATE_ON:
            return
        if self._picture_mode_list and mode not in self._picture_mode_list:
            raise InvalidSmartThingsPictureMode()
        
        self._get_api_key()
        try:
            cmd = Command(
                component_id=COMPONENT_MAIN,
                capability="custom.picturemode",
                command="setPictureMode",
                arguments=[mode]
            )
            await self._st.execute_device_command(self._device_id, [cmd])
            self._picture_mode = mode
        except Exception as err:
            _LOGGER.error("Error setting picture mode: %s", err)
            raise


class InvalidSmartThingsSoundMode(RuntimeError):
    """Selected sound mode is invalid."""


class InvalidSmartThingsPictureMode(RuntimeError):
    """Selected picture mode is invalid."""
