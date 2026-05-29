[![](https://img.shields.io/github/release/ollo69/ha-samsungtv-smart/all.svg?style=for-the-badge)](https://github.com/ollo69/ha-samsungtv-smart/releases)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
[![](https://img.shields.io/github/license/ollo69/ha-samsungtv-smart?style=for-the-badge)](LICENSE)
[![](https://img.shields.io/badge/MAINTAINER-%40ollo69-red?style=for-the-badge)](https://github.com/ollo69)
[![](https://img.shields.io/badge/COMMUNITY-FORUM-success?style=for-the-badge)](https://community.home-assistant.io)

# HomeAssistant - SamsungTV Smart Component

This is a custom component to allow control of SamsungTV devices in [HomeAssistant](https://home-assistant.io).
Is a modified version of the built-in [samsungtv](https://www.home-assistant.io/integrations/samsungtv/) with some extra
 features.<br/>
**This plugin is only for 2016+ TVs model!** (maybe all tizen family)

This project is a fork of the component [SamsungTV Tizen](https://github.com/jaruba/ha-samsungtv-tizen). I added some
feature like the possibility to configure it using the HA user interface, simplifing the configuration process.
I also added some code optimizition in the comunication layer using async aiohttp instead of request.
**Part of the code and documentation available here come from the original project.**<br/>

# Additional Features:

* Ability to send keys using a native Home Assistant service
* Ability to send chained key commands using a native Home Assistant service
* Supports Assistant commands (Google Home, should work with Alexa too, but untested)
* Extended volume control
* Ability to customize source list at media player dropdown list
* Cast video URLs to Samsung TV
* Connect to SmartThings Cloud API for additional features: see TV channel names, see which HDMI source is selected, more key codes to change input source
* Display logos of TV channels (requires Smartthings enabled) and apps

![N|Solid](https://i.imgur.com/8mCGZoO.png)
![N|Solid](https://i.imgur.com/t3e4bJB.png)

# Installation

### 1. Easy Mode

Install via HACS.

### 2. Manual

Install it as you would do with any homeassistant custom component:

1. Download `custom_components` folder.
1. Copy the `samsungtv_smart` directory within the `custom_components` directory of your homeassistant installation. The `custom_components` directory resides within your homeassistant configuration directory.
**Note**: if the custom_components directory does not exist, you need to create it.
After a correct installation, your configuration directory should look like the following.
    ```
    └── ...
    └── configuration.yaml
    └── custom_components
        └── samsungtv_smart
            └── __init__.py
            └── media_player.py
            └── websockets.py
            └── shortcuts.py
            └── smartthings.py
            └── upnp.py
            └── exceptions.py
            └── ...
    ```

# Configuration

Once the component has been installed, you need to configure it in order to make it work.
There are two ways of doing so:
- Using the web interface (Lovelace) [**recommended**]
- Manually editing the `configuration.yaml` file

**Important**: To complete the configuration procedure properly, you must be sure that your **TV is turned on and
connected to the LAN (wired or wireless)**. Stay near to your TV during configuration because probably you will need
to accept the access request that will prompt on your TV screen.

**Subnet/VLAN**
Samsung SmartTV does not allow WebSocket connections across different subnets or VLANs. If your TV is not on the same subnet as Home Assistant this will fail. It may be possible to bypass this issue by using IP ***Masqueradin***g or a ***Proxy***.

**Note**: To configure the component for using **SmartThings (strongly suggested)** you need to generate an access
token as explained in [this guide](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md).
Also make sure your **TV is logged into your SmartThings account** and **registered in SmartThings phone app** before
starting configuration.

### Option A: Configuration using the web UI [**recommended**]

1. From the Home Assistant front-end, navigate to 'Configuration' then 'Integrations'. Click `+` button in botton right corner,
search '**SamsungTV Smart**' and click 'Configure'.
2. In the configuration mask, enter the IP address of the TV, the name for the Entity and the SmartThings personal
access token (if created) and then click 'Submit'
3. **Important**: look for your TV screen and confirm **immediately** with OK if a popup appear.
4. Congrats! You're all set!

**Note**: be sure that your TV and HA are connected to the same VLAN. Websocket connection through different VLAN normally
not work because not supported by Samsung TV.
If you have errors during configuration, try to power cycle your TV. This will close running applications that can prevent
websocket connection initialization.

### Option B: Configuration via editing `configuration.yaml`

**From v0.3.16 initial configuration from yaml is not allowed.**<br>
You can still use `configuration.yaml` to set the additional parameter as explained below.

## Configuration options

From the Home Assistant front-end, navigate to 'Configuration' then 'Integrations'. Identify the '**SamsungTV Smart**'
integration configured for your TV and click the `OPTIONS` button.<br/>
Here you can change the following options:

- **Use SmartThings TV Status information**<br/>
(default = True)<br/>
**This option is available only if SmartThings is configured.**
When enabled the component will try to retrieve from SmartThings the information
about the TV Status. This information is always used in conjunction with local ping result.<br/>

- **Use SmartThings TV Channels information**<br/>
(default = True)<br/>
**This option is available only if SmartThings is configured.**
When enabled the component will try to retrieve from SmartThings the information about the TV Channel
and TV Channel Name or the Running App<br/>
**Note: in some case this information is not properly updated, disabled it you have incorrect information.**<br/>

- **Use SmartThings TV Channels number information**<br/>
(default = False)<br/>
**This option is available only if SmartThings is configured.**
When enabled then the TV Channel Names will show as media titles, by setting this to True the
TV Channel Number will also be attached to the end of the media title (when applicable).<br/>
**Note: not always SmartThings provide the information for channel_name and channel_number.**<br/>

- **Logo options**<br/>
The background color and channel / service logo preference to use, example: "white-color" (background: white, logo: color).<br/>
Supported values: "none", "white-color", "dark-white", "blue-color", "blue-white", "darkblue-white", "transparent-color", "transparent-white"<br/>
Default value: "white-color" (background: white, logo: color)<br/>
Notice that your logo is missing or outdated? In case of a missing TV channel logo also make sure you have Smartthings enabled.
This is required for the component to know the name of the TV channel.<br/>
Check guide [here](https://github.com/jaruba/ha-samsungtv-tizen/blob/master/Logos.md)
for updating the logo database this component is relying on.

- **Allow use of local logo images**<br/>
(default = True)<br/>
When enabled the integration will try to get logo image for the current media from the `www/samsungtv_smart_logos` sub folder of home-assistant configuration folder.
You can add new logo images in this folder, using the following rules for logo filename:
  - must be equal to the name of the `media_title` attribute, removing space, `_` and `.` characters and replacing `+` character with
  the string `plus`
  - must have the `.png` suffix
  - must be in `png` format (suggested size is 400x400 pixels)

- **Applications list load mode at startup**<br/>
Possible values: `All Apps`, `Default Apps` and `Not Load`<br/>
This option determine the mode application list is automatic generated.<br>
With `All Apps` the list will contain all apps installed on the TV, with `Default Apps` will be generated a minimal list
with only the most common application, with `Not Load` application list will be empty.<br/>
**Note: If a custom `Application List` in config options is defined this option is not available.**<br>

- **Method used to turn on TV**<br/>
Possible values: `WOL Packet` and `SmartThings`<br/>
**This option is available only if SmartThings is configured.**
WOL Packet is better when TV use wired connection.<br/>
SmartThings normally work only when TV use wireless connection.<br/>

- **Show advanced options**<br/>
Selecting this option and clicking submit a new options menu is opened containing the list of other options described below.

### Advanced options

- **Applications launch method used**<br/>
Possible values: `Control Web Socket Channel`, `Remote Web Socket Channel` and `Rest API Call`<br/>
This option determine the mode used to launch applications.<br/>
Use `Rest API Call` only if the other 2 methods do not work.<br/>

- **Number of times WOL packet is sent to turn on TV**<br/>
(default = 1, range from 1 to 5)<br/>
This option allow to configure the number of time the WOL packet is sent to turn on TV. Increase the value
until the TV properly turn-on.<br/>

- **TCP port used to check power status**<br/>
(default = 0, range from 0 to 65535)<br/>
With this option is possible to check the availability of a specific port to determinate power status instead
of using ICMP echo. To continue use ICMP echo, leave the value to `0`, otherwise set a port that is known becoming
available when TV is on (possible working ports, depending on TV models, are `9110`, `9119`, `9197`).</br>
**N.B. If you set an invalid port here, TV is always reported as `off`.**</br>

- **Binary sensor to help detect power status**<br/>
An external `binary_sensor` selectable from a list that can be used to determinate TV power status.<br/>
This can be any available `binary_sensor` that can better determinate the status of the TV, for example a
`binary_sensor` based on TV power consumption. It is suggested to not use a sensor based on `ping` platform
because this method is already implemented by the integration.</br>

- **Use volume mute status to detect fake power ON**<br/>
(default = True)<br/>
When enabled try to detect fake power on based on the Volume mute state, based on the assumption that when the
TV is powered on the volume is always unmuted.<br/>

- **Dump apps list on log file at startup**<br/>
(default = False)<br/>
When enabled the component will try to dump the list of available apps on TV in the HA log file at Info level.
The dump of the apps may not work for some TV models.<br/>

- **Power button switch to art mode**<br/>
(default = False)<br/>
When enabled the power button in UI will be used to toggle from `On` to `Art Mode` (and vice versa) and will not
power off the TV (you can still use the `turn off` service to power off the TV).<br/>
**Note: This option is valid only for TV that support `Art Mode` ("The Frame" models).**<br>

### Synched entities configuration

- **List of entity to Power OFF with TV**<br/>
A list of HA entity to Turn OFF when the TV entity is turned OFF (maximum 4). Select entities from list.
This call the service `homeassistant.turn_off` for maximum the first 4 entity in the provided list.<br/>

- **List of entity to Power ON with TV**<br/>
A list of HA entity to Turn ON when the TV entity is turned ON (maximum 4).  Select entities from list.
This call the service `homeassistant.turn_on` for maximum the first 4 entity in the provided list.<br/>

### Sources list configuration

This contains the KEYS visible sources in the dropdown list in media player UI.<br/>
You can configure the pair list `Name: Key` using the yaml editor in the option page. If a source list is present in
`configuration.yaml`, it will be imported in the options the first time that the integration is loaded.<br/>

Default value:<br/>
```
    1| TV: KEY_TV
    2| HDMI: KEY_HDMI
```

If SmartThings is [configured](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md) and the
source_list not, the component will try to identify and configure automatically the sources configured on the TV with
the relative associated names (new feature, tested on QLed TV). The created list is available in the HA log file.<br/>
You can also chain KEYS, example:
```
    1| TV: KEY_SOURCES+KEY_ENTER
```

And even add delays (in milliseconds) between sending KEYS, example:<br/>
```
    1| TV: KEY_SOURCES+500+KEY_ENTER
```

Resources: [key codes](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_codes.md) / [key patterns](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_chaining.md)<br/>
**Warning: changing input source with voice commands only works if you set the device name in `source_list` as one of
the whitelisted words that can be seen on [this page](https://web.archive.org/web/20181218120801/https://developers.google.com/actions/reference/smarthome/traits/modes#mode-settings)
(under "Mode Settings")**<br/>

### Application list configuration

This contains the APPS visible sources in the dropdown list in media player UI.<br/>
You can configure the pair list `Name: Key` using the yaml editor in the option page. If an application list is present in
`configuration.yaml`, it will be imported in the options the first time that the integration is loaded.<br/>

If the `Application list` is not manually configured, during startup the integration will try to automatically generate a list
of available application and a log message is generated with the content of the list. This list can be used to create a manual
list following [app_list guide](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/App_list.md). Automatic list
generation not work with some TV models.<br/>

Example value:
```
    1| Netflix: "11101200001"
    2| YouTube: "111299001912"
    3| Spotify: "3201606009684"
```

Known lists of App IDs: [List 1](https://github.com/tavicu/homebridge-samsung-tizen/issues/26#issuecomment-447424879),
[List 2](https://github.com/Ape/samsungctl/issues/75#issuecomment-404941201)<br/>

### Channel list configuration

This contains the tv CHANNELS visible sources in the dropdown list in media player UI. To guarantee performance keep the list small,
recommended maximum 30 channels.<br/>
You can configure the pair list `Name: Key` using the yaml editor in the option page. If a channel list is present in
`configuration.yaml`, it will be imported in the options the first time that the integration is loaded.<br/>

Example value:
```
    1| MTV: "14"
    2| Eurosport: "20"
    3| TLC: "21"
```

You can also specify the source that must be used for every channel. The source must be one of the source name defined in the `source_list`<br/>
Example value:
```
    1| MTV: 14@TV
    2| Eurosport: 20@TV
    3| TLC: 21@HDMI
```

## Custom configuration parameters

You can configure additional option for the component using configuration variable in `configuration.yaml` section.<br/>

Section in `configuration.yaml` file can also not be present and is not required for component to work. If you
want to configure any parameters, you must create one section that start with `- host` as shown in the example below:<br/>
```
samsungtv_smart:
  - host: <YOUR TV IP ADDRES>
    ...
```
Then you can add any of the following parameters:<br/>

- **mac:**<br/>
(string)(Optional)<br/>
This is an optional value, normally is automatically detected during setup phase and so is not required to specify it.
You should try to configure this parameter only if the setup fail in the detection.<br/>
The mac-address is used to turn on the TV. If you set it manually, you must find the right value from the TV Menu or
from your network router.<br/>

- **broadcast_address:**<br/>
(string)(Optional)<br/>
**Do not set this option if you do not know what it does, it can break turning your TV on.**<br/>
The ip address of the host to send the magic packet (for wakeonlan) to if the "mac" property is also set.<br/>
Default value: "255.255.255.255"<br/>
Example value: "192.168.1.255"<br/>

### Deprecated configuration parameters

Deprecated parameters were used by old integration version. Are still valid but normally are automatically imported
in application options and not used anymore, so after first import can be removed from `configuration.yaml`.

- **source_list:**<br/>
(json)(Optional)<br/>
This contains the KEYS visible sources in the dropdown list in media player UI.<br/>
Default value: '{"TV": "KEY_TV", "HDMI": "KEY_HDMI"}'<br/>
If SmartThings is [configured](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md) and the
source_list not, the component will try to identify and configure automatically the sources configured on the TV with
the relative associated names (new feature, tested on QLed TV). The created list is available in the HA log file.<br/>
You can also chain KEYS, example: '{"TV": "KEY_SOURCES+KEY_ENTER"}'<br/>
And even add delays (in milliseconds) between sending KEYS, example:<br/>
    '{"TV": "KEY_SOURCES+500+KEY_ENTER"}'<br/>
Resources: [key codes](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_codes.md) / [key patterns](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_chaining.md)<br/>
**Warning: changing input source with voice commands only works if you set the device name in `source_list` as one of
the whitelisted words that can be seen on [this page](https://web.archive.org/web/20181218120801/https://developers.google.com/actions/reference/smarthome/traits/modes#mode-settings)
(under "Mode Settings")**<br/>

- **app_list:**<br/>
(json)(Optional)<br/>
This contains the APPS visible sources in the dropdown list in media player UI.<br/>
Default value: AUTOGENERATED<br/>
If the `app_list` is not manually configured, during startup is generated a file in the custom component folder with the
list of all available applications. This list can be used to create a manual list following [app_list guide](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/App_list.md)<br/>
Example value: '{"Netflix": "11101200001", "YouTube": "111299001912", "Spotify": "3201606009684"}'<br/>
Known lists of App IDs: [List 1](https://github.com/tavicu/homebridge-samsung-tizen/issues/26#issuecomment-447424879),
[List 2](https://github.com/Ape/samsungctl/issues/75#issuecomment-404941201)<br/>

- **channel_list:**<br/>
(json)(Optional)<br/>
This contains the tv CHANNELS visible sources in the dropdown list in media player UI. To guarantee performance keep the list small,
recommended maximum 30 channels.<br/>
Example value: '{"MTV": "14", "Eurosport": "20", "TLC": "21"}'<br/>
You can also specify the source that must be used for every channel. The source must be one of the defined in the `source_list`<br/>
Example value: '{"MTV": "14@TV", "Eurosport": "20@TV", "TLC": "21@HDMI"}'<br/>


### Removed configuration parameters

Removed parameters were used by old integration version, are not used and supported anymore and replaced by application option.
For this reason should be removed from `configuration.yaml`.

- **api_key:**<br/>
(string)(Optional) (obsolete/not used from v0.3.16 - configuration from yaml is not allowed)<br/>
API Key for the SmartThings Cloud API, this is optional but adds better state handling on, off, channel name, hdmi source,
and a few new keys: `ST_TV`, `ST_HDMI1`, `ST_HDMI2`, `ST_HDMI3`, etc. (see more at [SmartThings Keys](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md#smartthings-keys))<br/>
Read [How to get an API Key for SmartThings](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md)<br/>
This parameter can also be provided during the component configuration using the user interface.<br/>
**Note: this parameter is used only during initial configuration and then stored in the registry. It's not possible to change the value after that the component is configured. To change the value you must delete the integration from UI.**<br/>

- **device_id:**<br/>
(string)(Optional) (obsolete/not used from v0.3.16 - configuration from yaml is not allowed)<br/>
Device ID for the SmartThings Cloud API. This is optional, to be used only if component fails to automatically determinate it.
Read [SmartThings Device ID](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md#smartthings-device-id)
to understand how identify the correct value to use.<br/>
This parameter will be requested during component configuration from user interface when required.<br/>
**Note: this parameter is used only during initial configuration and then stored in the registry. It's not possible to
change the value after that the component is configured. To change the value you must delete the integration from UI.**<br/>

- **device_name:** (obsolete/not used from v0.3.16 - configuration from yaml is not allowed)<br/>
(string)(Optional)<br/>
This is an optional value, used only to identify the TV in SmartThings during initial configuration if you have more TV
registered. You should  configure this parameter only if the setup fails in the detection.<br/>
The device_name to use can be read using the SmartThings app<br/>
**Note: this parameter is used only during initial configuration.**<br/>

- **show_channel_number:** (obsolete/not used from v0.3.16 and replaced by Configuration options)<br/>
(boolean)(Optional)<br/>
If the SmartThings API is enabled (by settings "api_key" and "device_id"), then the TV Channel Names will show as media
titles, by setting this to True the TV Channel Number will also be attached to the end of the media title (when applicable).<br/>
**Note: not always SmartThings provide the information for channel_name and channel_number.**<br/>

- **load_all_apps:** (obsolete/not used from v0.3.4 and replaced by Configuration options)<br/>
(boolean)(Optional)<br/>
This option is `True` by default.</br>
Setting this parameter to false, if a custom `app_list` is not defined, the automatic app_list will be generated
limited to few application (the most common).<br/>

- **update_method:** (obsolete/not used from v0.3.3)<br/>
(string)(Optional)<br/>
This change the ping method used for state update. Values: "ping", "websockets" and "smartthings"<br/>
Default value: "ping" if SmartThings is not enabled, else "smartthings"<br/>
Example update_method: "websockets"<br/>

- **update_custom_ping_url:** (obsolete/not used from v0.2.x)<br/>
(string)(Optional)<br/>
Use custom endpoint to ping.<br/>
Default value: PING TO 8001 ENDPOINT<br/>
Example update_custom_ping_url: "http://192.168.1.77:9197/dmr"<br/>

- **scan_app_http:** (obsolete/not used from v0.2.x)<br/>
(boolean)(Optional)<br/>
This option is `True` by default. In some cases (if numerical IDs are used when setting `app_list`) HTTP polling will
be used (1 request per app) to get the running app.<br/>
This is a lengthy task that some may want to disable, you can do so by setting this option to `False`.<br/>
For more information about how we get the running app, read the [app_list guide](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/App_list.md).<br/>

# Usage

### Known Supported Voice Commands

* Turn on `SAMSUNG-TV-NAME-HERE` (for some older TVs this only works if the TV is connected by LAN cable to the Network)
* Turn off `SAMSUNG-TV-NAME-HERE`
* Volume up on `SAMSUNG-TV-NAME-HERE` (increases volume by 1)
* Volume down on `SAMSUNG-TV-NAME-HERE` (decreases volume by 1)
* Set volume to 50 on `SAMSUNG-TV-NAME-HERE` (sets volume to 50 out of 100)
* Mute `SAMSUNG-TV-NAME-HERE` (sets volume to 0)
* Change input source to `DEVICE-NAME-HERE` on `SAMSUNG-TV-NAME-HERE` (only works if `DEVICE-NAME-HERE` is a whitelisted word from [this page](https://web.archive.org/web/20181218120801/https://developers.google.com/actions/reference/smarthome/traits/modes) under "Mode Settings")

(if you find more supported voice commands, please create an issue so I can add them here)

### Cast to TV

```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "url",
  "media_content_id": "FILE_URL",
}
```
Replace `FILE_URL` with the url of your file

### Cast to YouTube

```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "url",
  "media_content_id": "YOUTUBE_URL",
  "enqueue": "play",
}
```
Replace `YOUTUBE_URL` with the url of the video you want to play
All 4 enqueue modes are supported. Shorts videos URL are also supported.
**Note**: `enqueue` is required, or the service will open the video using TV Web Browser.

### Send Keys

```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "send_key",
  "media_content_id": "KEY_CODE"
}
```
**Note**: Change "KEY_CODE" by desired [key_code](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_codes.md). (also works with key chaining and SmartThings keys: ST_TV, ST_HDMI1, ST_HDMI2, ST_HDMI3, etc. / see more at [SmartThings Keys](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md#smartthings-keys))

Script example:
```
tv_channel_down:
  alias: Channel down
  sequence:
  - service: media_player.play_media
    data:
      entity_id: media_player.samsung_tv55
      media_content_type: "send_key"
      media_content_id: KEY_CHDOWN
```

### Hold Keys
```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "send_key",
  "media_content_id": "KEY_CODE, <hold_time>"
}
```

**Note**: Change "KEY_CODE" by desired [key_code](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_codes.md) and <hold_time> with a valid numeric value in milliseconds (this also works with key chaining but not with SmartThings keys).

***Key Chaining Patterns***
---------------
Key chaining is also supported, which means a pattern of keys can be set by delimiting the keys with the "+" symbol, delays can also be set in milliseconds between the "+" symbols.

[See the list of known Key Chaining Patterns](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Key_chaining.md)


***Open Browser Page***
---------------

```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "browser",
  "media_content_id": "https://www.google.com"
}
```

***Send Text***
---------------
To send a specific text to a selected text input

```
service: media_player.play_media
```

```json
{
  "entity_id": "media_player.samsungtv",
  "media_content_type": "send_text",
  "media_content_id": "your text"
}
```

***Select sound mode (SmartThings only)***
---------------

```
service: media_player.select_sound_mode
```

```json
{
  "entity_id": "media_player.samsungtv",
  "sound_mode": "your mode"
}
```

**Note**: You can get list of valid `sound_mode` in the `sound_mode_list` state attribute


***Select picture mode (SmartThings only)***
---------------

```
service: samsungtv_smart.select_picture_mode
```

```json
{
  "entity_id": "media_player.samsungtv",
  "picture_mode": "your mode"
}
```

**Note**: You can get list of valid `picture_mode` in the `picture_mode_list` state attribute


***Set Art Mode (for TV that support it)***
---------------

```
service: samsungtv_smart.set_art_mode
```

```json
{
  "entity_id": "media_player.samsungtv"
}
```

# Be kind!
If you like the component, why don't you support me by buying me a coffe?
It would certainly motivate me to further improve this work.

[![Buy me a coffe!](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/ollo69)

Credits
-------

This integration is developed by [Ollo69][ollo69] based on integration [SamsungTV Tizen][samsungtv_tizen].<br/>
Original SamsungTV Tizen integration was developed by [jaruba][jaruba].<br/>
Logo support is based on [jaruba channels-logo][channels-logo] and was developed with the support of [Screwdgeh][Screwdgeh].<br/>

[ollo69]: https://github.com/ollo69
[samsungtv_tizen]: https://github.com/jaruba/ha-samsungtv-tizen
[jaruba]: https://github.com/jaruba
[Screwdgeh]: https://github.com/Screwdgeh
[channels-logo]: https://github.com/jaruba/channel-logos
