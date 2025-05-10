# HomeAssistant - SamsungTV Smart Component

## ***Enable SmartThings*** - Setup instructions

### Create personal access token

1. Log into the [personal access tokens page](https://account.smartthings.com/tokens) and click '[Generate new token](https://account.smartthings.com/tokens/new)'
2. Enter a token name (can be whatever you want), for example, 'Home Assistant' and select the following authorized scopes:
    - Devices (all)
    - Installed Applications (all)
    - Scenes (all)
    - Applications (all)
    - Locations (all)
    - Schedules (all)
    
3. Click 'Generate token'. When the token is displayed, copy and save it somewhere safe (such as your keystore) as you will not be able to retrieve it again.

### Configure Home Assistant

Once the SmartThings token has been generated, you need to configure the component with it in order to make it work as explained in the main guide.

**Note:** if the component has been already configured for your TV, you must delete it from the HA web interface and then re-configure it to enable SmartThings integration.<br/>

#### SmartThings Device ID

If during configuration flow automatic detection of SmartThings device ID fails, a new configuration page will open requesting you to manual
insert it.
To identify your TV device ID use the following steps:

- Go [here](https://my.smartthings.com/advanced/devices) and login with your SmartThings credential
- Click on the name of your TV from the list of available devices
- In the new page search the column called `Device ID`
- Copy the value (is a UUID code) and paste it in the HomeAssistant configuration page



***Benefits of Enabling SmartThings***
---------------

- Better states for running apps (read [app_list guide](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/App_list.md) for more information)
- New keys available (read more below about [SmartThings Keys](https://github.com/ollo69/ha-samsungtv-smart/blob/master/docs/Smartthings.md#smartthings-keys))
- Shows TV channel names
- Shows accurate states for HDMI or TV input sources


***SmartThings Keys***
---------------

*Input Keys*
____________
Key|Description
---|-----------
ST_TV|TV
ST_VD:`src`|`src`
ST_HDMI1|HDMI1
ST_HDMI2|HDMI2
ST_HDMI3|HDMI3
ST_HDMI4|HDMI4
...


With ST_VD:`src` replace `src` with the name of the source you want activate


*Channel Keys*
______________
Key|Description
---|-----------
ST_CHUP|ChannelUp
ST_CHDOWN|ChannelDown
ST_CH1|Channel1
ST_CH2|Channel2
ST_CH3|Channel3
...

*Volume Keys*
______________
Key|Description
---|-----------
ST_MUTE|Mute/Unmute
ST_VOLUP|VolumeUp
ST_VOLDOWN|VolumeDown
ST_VOL1|VolumeLevel1
ST_VOL2|VolumeLevel2
...
ST_VOL100|VolumeLevel100
