# SamsungTV Smart — Enhanced Fork

[![Version](https://img.shields.io/badge/version-6.3.2-blue.svg)](https://github.com)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2025.6.0-green.svg)](https://www.home-assistant.io)
[![License: LGPL v2.1](https://img.shields.io/badge/License-LGPL%20v2.1-yellow.svg)](https://www.gnu.org/licenses/lgpl-2.1)

A custom integration for Home Assistant to control Samsung Smart TVs (Tizen OS), based on the excellent work of [ollo69/ha-samsungtv-smart](https://github.com/ollo69/ha-samsungtv-smart).

This fork brings improved WebSocket stability, full Samsung Frame TV Art Mode support, and OAuth2 authentication for SmartThings.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
  - [SmartThings Authentication](#smartthings-authentication)
  - [Integration Setup](#integration-setup)
  - [Options](#options)
- [Entities](#entities)
- [Services](#services)
  - [Standard TV Services](#standard-tv-services)
  - [Frame Art Services](#frame-art-services)
- [Frame Art Mode](#frame-art-mode)
  - [Thumbnail Downloads](#thumbnail-downloads)
- [Automations & Tips](#automations--tips)
- [Troubleshooting](#troubleshooting)
- [Credits](#credits)

---

## Features

- Full Samsung Smart TV (Tizen OS) control via WebSocket
- Power on/off, volume, source selection, app launching
- SmartThings integration for enhanced status polling (channel info, picture mode, sound mode…)
- **Three SmartThings authentication methods**: OAuth2, Personal Access Token, or existing ST integration
- **Samsung Frame TV Art Mode** — full artwork management via a dedicated async API
- New dedicated entities: Art Mode switch and Frame Art sensor
- Improved WebSocket connection stability — prevents zombie connections and saturation
- Wake-on-LAN support
- Channel and app list management
- Logo fetching for apps and sources

---

## Requirements

- Home Assistant **≥ 2025.6.0**
- Python packages (installed automatically): `websocket-client`, `wakeonlan`, `aiofiles`, `casttube`, `pysmartthings==3.5.0`
- A Samsung Smart TV running **Tizen OS** (2016+), reachable on the local network
- For SmartThings features: a Samsung account and a SmartThings-registered TV

---

## Installation

### HACS (recommended)

1. In Home Assistant, open **HACS → Integrations**.
2. Click the three-dot menu **⋮ → Custom repositories**.
3. Add the repository URL and set category to **Integration**.
4. Search for **SamsungTV Smart** and click **Download**.
5. Restart Home Assistant.

### Manual

1. Download or clone this repository.
2. Copy the `samsungtv_smart` folder into your Home Assistant `custom_components` directory:

   ```
   config/
   └── custom_components/
       └── samsungtv_smart/
   ```

3. Restart Home Assistant.

---

## Configuration

### SmartThings Authentication

Three methods are available. Choose **one**.

---

#### Option 1 — OAuth2 (Recommended)

OAuth2 provides automatic token refresh, eliminating the need for manual PAT renewal.
As of 2025/2026, the SmartThings Developer Workspace is deprecated and new projects can not be created. 
Instead, the SmartThings CLI is the best way to obtain the required OAuth secret. 

### Step 1: Create SmartThings OAuth Application
These steps can be followed on any device where you can log into your Samsung account.

1. Install the [SmartThings CLI](https://developer.smartthings.com/docs/sdks/cli/)
2. Run `smartthings apps:create`.
3. Follow the interactive instructions:
   a. Display Name: Home Assistant Samsung TV
   b. Description: For Home Assistant integration of Samsung The Frame TV
   c. Icon Image URL: Can be left blank
   d. Target URL: Can be left blank
   e. Select Scopes: select `r:devices:*` and `x:devices:*`
   f. Now select `Add Redirect URI`, and set it to `https://my.home-assistant.io/redirect/oauth`
   g. Select `Finish and create OAuth-In SmartApp.`
4. You can now see the details of the app and OAuth data, save these

> ⚠️ **Important**: Use the "OAuth Client Id", NOT the "App Id"!

### Step 2: Configure Home Assistant

Add your credentials to Home Assistant:

**Option A: Via UI**
1. Go to **Settings** → **Devices & Services** → **Application Credentials** (three dots in top right corner)
2. Click **Add Credentials**
3. Select **Samsung TV Smart**
4. Enter your Client ID and Client Secret

**Option B: Via configuration.yaml**
```yaml
# configuration.yaml
application_credentials:
  - platform: samsungtv_smart
    client_id: "YOUR_CLIENT_ID"
    client_secret: "YOUR_CLIENT_SECRET"
```

### Step 3: Add Integration with OAuth

1. Go to **Settings** → **Devices & Services**
2. Click **Add Integration** → **Samsung TV Smart**
3. Select **SmartThings OAuth** as authentication method
4. Complete the OAuth flow in your browser
5. If needed, the device ID can be found [here](https://my.smartthings.com/advanced/devices)
6. Your TV should now appear with OAuth authentication

---

#### Option 2 — Personal Access Token (PAT)

1. Go to [https://account.smartthings.com/tokens](https://account.smartthings.com/tokens).
2. Create a new token with at least **Devices** permissions.
3. Copy the token.
4. When adding the integration, select **Personal Access Token** and paste it.

---

#### Option 3 — SmartThings Integration Link

If you already have the native SmartThings integration configured in Home Assistant:

1. When adding the integration, select **Personal Access Token**.
2. In the dropdown, select your existing SmartThings integration instead of entering a token manually.

---

### Integration Setup

1. Go to **Settings → Devices & Services → + Add Integration**.
2. Search for **SamsungTV Smart**.
3. Choose your authentication method (see above).
4. Enter your **TV's IP address** (a static IP or DHCP reservation is strongly recommended).
5. Follow the on-screen steps. Your TV may prompt you to accept the pairing request — accept it.

> **Tip**: If your TV is off and you are using Wake-on-LAN, make sure WOL is enabled in your TV's network settings.

---

### Options

After initial setup, click **Configure** on the integration card to access these options:

| Option | Description |
|---|---|
| **Source list** | Define custom input sources (JSON: `{"HDMI 1": "KEY_HDMI1", ...}`) |
| **App list** | Define custom app shortcuts (JSON) |
| **App load method** | How to load the app list: All, Default, or Disabled |
| **App launch method** | Standard, Remote, or REST |
| **Power on method** | Wake-on-LAN or SmartThings |
| **WOL repeat count** | Number of WOL packets sent (1–5) |
| **Scan interval** | SmartThings polling interval (seconds) |
| **Use ST channel info** | Fetch live channel info from SmartThings |
| **Use ST status info** | Fetch power/input status from SmartThings |
| **Show channel number** | Display channel number alongside channel name |
| **Use mute check** | Detect mute state via SmartThings |
| **Logo option** | Show logos for apps/channels (local or remote) |
| **Sync turn on/off** | Optional entity to mirror TV power state |
| **External power entity** | Use an external sensor to determine power state |
| **Toggle Art Mode** | Toggle Art Mode when turning on a Frame TV that is already in Art Mode |
| **Ping port** | Port used to detect TV presence |
| **WS name** | Name shown on the TV when pairing (default: `[Home Assistant]`) |

---

## Entities

Each configured TV creates the following entities:

| Entity | Type | Description |
|---|---|---|
| `media_player.<tv_name>` | Media Player | Main TV control entity |
| `switch.<tv_name>_art_mode` | Switch | Toggle Art Mode on/off (Frame TVs only) |
| `sensor.<tv_name>_frame_art` | Sensor | Currently displayed artwork info (Frame TVs only) |

### Media Player Attributes

In addition to standard media player attributes, the following are available:

- `device_model`, `device_name`, `device_os`, `device_mac`
- `picture_mode`, `picture_mode_list`
- `sound_mode`, `sound_mode_list`
- `channel`, `channel_name`, `channel_number`
- `app_id`, `app_name`
- `frame_art_mode` — whether Art Mode is active
- `frame_art_current` — content ID of the current artwork

### Frame Art Sensor Attributes

- `art_mode` — current Art Mode state
- `content_id` — artwork content ID
- `content_type` — artwork category
- `thumbnail_url` — local URL to the thumbnail (if downloaded)

---

## Services

### Standard TV Services

These are called on the `media_player` entity.

| Service | Description |
|---|---|
| `media_player.turn_on` | Turn on the TV (WOL or SmartThings) |
| `media_player.turn_off` | Turn off the TV |
| `media_player.volume_up/down` | Adjust volume |
| `media_player.mute_volume` | Mute/unmute |
| `media_player.set_volume_level` | Set volume level (0.0–1.0) |
| `media_player.select_source` | Switch input source or launch an app |
| `media_player.play_media` | Send a key command or launch a URL |
| `samsungtv_smart.select_picture_mode` | Change picture mode |
| `remote.send_command` | Send raw key commands (via remote entity) |

**Sending key commands via `play_media`:**

```yaml
service: media_player.play_media
target:
  entity_id: media_player.samsung_tv
data:
  media_content_type: send_key
  media_content_id: KEY_MUTE
```

---

### Frame Art Services

These services require a Samsung **Frame TV** with Art Mode. They are called on the `media_player` entity.

| Service | Description |
|---|---|
| `samsungtv_smart.art_get_artmode` | Get current Art Mode status |
| `samsungtv_smart.art_set_artmode` | Enable or disable Art Mode |
| `samsungtv_smart.art_available` | List all available artworks (optionally filtered by category) |
| `samsungtv_smart.art_get_current` | Get info about the currently displayed artwork |
| `samsungtv_smart.art_select_image` | Display a specific artwork by content ID |
| `samsungtv_smart.art_upload` | Upload a local image to the TV |
| `samsungtv_smart.art_delete` | Delete a user-uploaded artwork (MY-* IDs only) |
| `samsungtv_smart.art_get_thumbnail` | Download a single artwork thumbnail |
| `samsungtv_smart.art_get_thumbnails_batch` | Batch-download thumbnails for multiple artworks |
| `samsungtv_smart.art_set_brightness` | Set Art Mode brightness (0–100, mapped to TV scale 1–10) |
| `samsungtv_smart.art_get_brightness` | Get current Art Mode brightness |
| `samsungtv_smart.art_change_matte` | Change the matte/frame style of an artwork |
| `samsungtv_smart.art_set_photo_filter` | Apply a photo filter to an artwork |
| `samsungtv_smart.art_get_photo_filter_list` | List available photo filters |
| `samsungtv_smart.art_get_matte_list` | List available matte styles |
| `samsungtv_smart.art_set_favourite` | Add/remove artwork from favourites |
| `samsungtv_smart.art_set_slideshow` | Configure slideshow (duration, shuffle, category) |
| `samsungtv_smart.art_set_auto_rotation` | Configure auto-rotation (duration, shuffle, category) |

#### Service Examples

**Select an artwork:**

```yaml
service: samsungtv_smart.art_select_image
data:
  entity_id: media_player.samsung_frame
  content_id: SAM-F0206
  show: true
```

**Upload a local image:**

```yaml
service: samsungtv_smart.art_upload
data:
  entity_id: media_player.samsung_frame
  file_path: /config/www/my_art.jpg
  matte_id: modern_apricot
  file_type: jpg
```

**Batch download thumbnails:**

```yaml
service: samsungtv_smart.art_get_thumbnails_batch
data:
  entity_id: media_player.samsung_frame
  category_id: MY-C0002
  favorites_only: false
  force_download: false
```

**Configure slideshow:**

```yaml
service: samsungtv_smart.art_set_slideshow
data:
  entity_id: media_player.samsung_frame
  duration: 15min
  shuffle: true
  category_id: 2
```

---

## Frame Art Mode

### Overview

Frame TVs can display artwork when not in use. This integration provides full programmatic control over the Art Mode, including artwork selection, brightness, matting, filters, and slideshow settings.

### Content IDs

Artworks are identified by content IDs:

| Prefix | Source |
|---|---|
| `SAM-*` | Samsung Art Store content |
| `MY-F*` | User-uploaded photos |
| `MY-C*` | Categories (MY-C0002=My Photos, MY-C0004=Favorites, MY-C0008=All) |

### Matte Styles

Format: `type_color`

**Types**: `none`, `modernthin`, `modern`, `modernwide`, `shadowboxthin`, `shadowbox`, `shadowboxwide`, `panoramic`, `flexible`

**Colors**: `black`, `neutral`, `antique`, `warm`, `polar`, `sand`, `seafoam`, `sage`, `burgandy`, `navy`, `apricot`, `byzantine`, `lavender`, `redorange`

**Example**: `modern_apricot`, `shadowbox_polar`

### Photo Filters

Available filters: `none`, `mono`, `original`, `ink`, `watercolor`, `oil`, `pastel`, `posterize`, `noir`, `quartertone`

### Thumbnail Downloads

Thumbnails are automatically organized and saved to:

```
config/www/frame_art/
├── personal/    ← user-uploaded photos (MY-F*)
├── store/       ← Samsung Art Store (SAM-*)
└── other/       ← everything else
```

These are then accessible via Home Assistant's `/local/` URL path, making them directly usable in Lovelace dashboards and galleries.

**Smart caching**: thumbnails are only downloaded once. Subsequent calls to `art_get_thumbnail` or `art_get_thumbnails_batch` skip files that already exist, making batch operations fast on repeat runs. Use `force_download: true` to override.

---

## Automations & Tips

### Wake-on-LAN with delayed command

Samsung TVs may need a moment to become responsive after WOL. Use a delay in automations:

```yaml
automation:
  - alias: "Turn on TV and switch to HDMI 1"
    trigger:
      - platform: ...
    action:
      - service: media_player.turn_on
        target:
          entity_id: media_player.samsung_tv
      - delay: "00:00:08"
      - service: media_player.select_source
        target:
          entity_id: media_player.samsung_tv
        data:
          source: HDMI 1
```

### Preventive maintenance (integration reload)

To prevent WebSocket connection saturation over time, you can schedule a periodic reload:

```yaml
automation:
  - alias: "Reload SamsungTV integration nightly"
    trigger:
      - platform: time
        at: "03:00:00"
    action:
      - service: homeassistant.reload_config_entry
        target:
          entity_id: media_player.samsung_tv
```

### Art Mode automation on TV off

```yaml
automation:
  - alias: "Enable Art Mode when TV turns off"
    trigger:
      - platform: state
        entity_id: media_player.samsung_frame
        to: "off"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.samsung_frame_art_mode
```

---

## Troubleshooting

### TV not found during setup

- Make sure the TV is on and connected to the same network as Home Assistant.
- Ensure the TV's IP address is correct and reachable (`ping <ip>`).
- Disable any VLANs or firewall rules blocking ports **8001** and **8002**.

### TV accepts pairing but integration shows unavailable

- The first pairing token is stored in the config entry. If the token is rejected, delete the integration and re-add it — the TV will prompt again for pairing.
- Make sure you **Accept** the pairing request on the TV screen within the timeout window.

### WebSocket connectivity issues / TV becomes unresponsive

Samsung TVs have strict limits on simultaneous WebSocket connections. If the integration creates too many connections without properly closing them, the TV's SmartThings service can become saturated.

Signs of this issue:
- TV stops responding to commands
- Logs show repeated `WebSocketProtocolException` or connection refused errors
- Issue resolves temporarily after a TV restart

Mitigations built into this fork:
- Proper handling of invalid WebSocket close opcodes
- Active connection cleanup to prevent zombie connections
- Use the **nightly reload automation** above as a preventive measure.

### SmartThings features not working

- Verify your API key/token has `Devices` permissions.
- Check that your TV is registered and visible in the SmartThings app.
- For OAuth2: confirm your Developer Portal app is still active and has the correct scopes (`r:devices:*`, `x:devices:*`).

### OAuth2 — "Token refresh failed"

1. Check internet connectivity from Home Assistant.
2. Verify your OAuth app on [developer.smartthings.com](https://developer.smartthings.com) is still active.
3. Re-authenticate: go to **Settings → Devices & Services → Samsung TV Smart → Reconfigure**.

### Frame Art services not working

- These services require a Samsung **Frame** TV with Art Mode capability.
- Make sure the TV is on (not just in Art Mode).
- Check that port **8002** (encrypted WebSocket) is not blocked.

---

## Credits

This project is a fork of [ollo69/ha-samsungtv-smart](https://github.com/ollo69/ha-samsungtv-smart), itself based on work by [@jaruba](https://github.com/jaruba) and [@screwdgeh](https://github.com/screwdgeh).

Frame Art API based on [xchwarze/samsung-tv-ws-api](https://github.com/xchwarze/samsung-tv-ws-api) (art-updates branch), with contributions from Matthew Garrett and Nick Waterton.

WebSocket library: [websocket-client](https://github.com/websocket-client/websocket-client) / [Xchwarze](https://github.com/Xchwarze).

---

*Licensed under the GNU Lesser General Public License v2.1.*
