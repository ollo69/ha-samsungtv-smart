# HomeAssistant - SamsungTV Smart Integration

## ***Enable SmartThings*** - Setup instructions

### SmartThings authentication

To use SmartThings feature in integration you must provide authentication information. There are 2 way to do this.

#### Method 1: Use native SmartThings integration (suggested)

Configure on your HA instance the [native HA SmartThings integration](https://www.home-assistant.io/integrations/smartthings/). In this way the API key to access to SmartThings will be automatically provided to `Samsung TV Smart` integration and you don't have to do any other steps. Just remember to select the `SmartThings entry used to provide SmartThings credential` in Samsung TV Smart configuration flow.


#### Method 2: Create personal access token (deprecated)

1. Log into the [personal access tokens page](https://account.smartthings.com/tokens) and click '[Generate new token](https://account.smartthings.com/tokens/new)'
2. Enter a token name (can be whatever you want), for example, 'Home Assistant' and select the following authorized scopes:
    - Devices (all)
    - Installed Applications (all)
    - Scenes (all)
    - Applications (all)
    - Locations (all)
    - Schedules (all)

3. Click 'Generate token'. When the token is displayed, copy and save it somewhere safe (such as your keystore) as you will not be able to retrieve it again.

**Note:** starting from 30 December 2024 generated `personal access token (PAT)` have a duration of 24 hours as explained [here](https://developer.smartthings.com/docs/getting-started/authorization-and-permissions). For this reason use of `PAT` is not recommended because you should manually update your token every 24 hours. In case you can use the integration reconfigure option to update it.<br/>

### Configure Home Assistant

Once the SmartThings token has been generated, you need to configure the integration with it in order to make it work as explained in the main guide. If you previously
configured the [native HA SmartThings integration](https://www.home-assistant.io/integrations/smartthings/), remenber to select the `SmartThings entry used to provide SmartThings credential` during configuration flow.

**Note:** if the integration has been already configured for your TV, you must delete it from the HA web interface and then re-configure it to enable SmartThings integration.<br/>

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
