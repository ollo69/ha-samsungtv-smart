# 🖼️ Frame Art Gallery - Lovelace Guide

Create interactive artwork galleries in Home Assistant with click-to-display functionality.

---

## Table of Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Folder Gallery Card](#folder-gallery-card-recommended)
- [Auto-Entities Gallery](#auto-entities-gallery)
- [Template Sensors](#template-sensors)
- [Advanced Layouts](#advanced-layouts)
- [Customization](#customization)
- [Troubleshooting](#troubleshooting)

---

## Overview

Frame Art Gallery transforms your Home Assistant dashboard into an interactive art gallery:

- 📸 Click thumbnails to display artwork on Frame TV
- 🎨 Separate galleries for personal photos, favorites, and Art Store
- 🔄 Auto-generated from actual TV content
- 📱 Fully responsive layouts
- ⚡ Fast loading with cached thumbnails
- 🖱️ Lightbox preview with hold-to-select
- 🧹 Automatic cleanup of orphaned thumbnails

---

## Requirements

### Required Components

1. **SamsungTV Smart integration** with Frame Art support

2. **Downloaded thumbnails** (see [Quick Start](#quick-start))

3. **Folder sensor** for gallery updates:
   ```yaml
   # configuration.yaml
   sensor:
     - platform: folder
       folder: /config/www/frame_art/store
       filter: "*.jpg"
       scan_interval: 30
   ```

4. **Gallery Card** (choose one):

   **Option A: folder-gallery-card** ⭐ **RECOMMENDED**
   - Included with this integration
   - Faster and cleaner than auto-entities
   - Better performance with large galleries
   - Built-in lightbox and actions

   **Option B: auto-entities**
   - Install via HACS: Search "auto-entities"
   - More flexible but more complex

### Optional But Recommended

- **card-mod** for custom styling
- **Browser Mod** for popups/modals

---

## Quick Start

### Step 1: Create Directory Structure

```bash
mkdir -p /config/www/frame_art/personal
mkdir -p /config/www/frame_art/store
mkdir -p /config/www/frame_art/other
```

### Step 2: Download Thumbnails

```yaml
service: samsungtv_smart.art_get_thumbnails_batch
target:
  entity_id: media_player.samsung_frame
data:
  favorites_only: true
  cleanup_orphans: true
```

**First run:** 2-5 minutes  
**Subsequent runs:** 2-5 seconds (skips existing)

### Step 3: Create Folder Sensor

Add to `configuration.yaml`:

```yaml
sensor:
  - platform: folder
    folder: /config/www/frame_art/store
    filter: "*.jpg"
    scan_interval: 30
```

### Step 4: Install Gallery Card

See [Folder Gallery Card](#folder-gallery-card-recommended) section below.

---

## Folder Gallery Card (Recommended)

The custom `folder-gallery-card` provides the best experience for Frame Art galleries.

### Installation

1. Copy `folder-gallery-card.js` to `/config/www/community/folder-gallery-card/`

2. Add to Lovelace resources:
   ```yaml
   resources:
     - url: /local/community/folder-gallery-card/folder-gallery-card.js
       type: module
   ```

3. Restart Home Assistant

### Basic Configuration

```yaml
type: custom:folder-gallery-card
title: Frame TV Favorites
folder_sensor: sensor.store
folder: /local/frame_art/store
columns: 4
image_height: 160px
aspect_ratio: "1"
tap_action: lightbox
hold_action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame
  data:
    content_id: "{{content_id}}"
```

### All Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `title` | string | - | Card title |
| `folder_sensor` | string | - | Folder sensor entity ID |
| `folder` | string | - | Base folder path (e.g., `/local/frame_art/store`) |
| `columns` | number | `4` | Number of columns |
| `image_height` | string | `150px` | Image height (ignored if `aspect_ratio` set) |
| `aspect_ratio` | string | - | Aspect ratio (e.g., `1`, `16/9`, `3/4`) |
| `gap` | string | `8px` | Gap between images |
| `border_radius` | string | `8px` | Image border radius |
| `show_filename` | boolean | `true` | Show filename on hover |
| `filter` | string | `*` | File filter pattern |
| `tap_action` | string/object | - | Action on tap |
| `hold_action` | object | - | Action on long press |
| `action` | object | - | Default action (used by lightbox button) |

### Tap Action Options

| Value | Description |
|-------|-------------|
| `lightbox` | Open image in fullscreen lightbox |
| `action` | Execute the configured action directly |
| `more-info` | Show entity more-info dialog |

### Template Variables

Use these in your action data:
| Variable | Description |
|----------|-------------|
| `{{content_id}}` | Artwork content ID (extracted from filename) |
| `{{filename}}` | Full filename with extension |
| `{{image_path}}` | Full image path |
| `{{name}}` | Artwork name (filename without extension) |
| `{{index}}` | Image index in gallery |

### Example: Favorites Gallery with Actions

```yaml
type: custom:folder-gallery-card
title: ⭐ Favorites
folder_sensor: sensor.store
folder: /local/frame_art/store
columns: 4
aspect_ratio: "1"
gap: 10px
border_radius: 12px
tap_action: lightbox
hold_action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame
  data:
    content_id: "{{content_id}}"
action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame
  data:
    content_id: "{{content_id}}"
```

### Example: Personal Photos Gallery

First, create folder sensor:

```yaml
sensor:
  - platform: folder
    folder: /config/www/frame_art/personal
    filter: "*.jpg"
    scan_interval: 30
```

Then add card:

```yaml
type: custom:folder-gallery-card
title: 📷 Personal Photos
folder_sensor: sensor.personal
folder: /local/frame_art/personal
columns: 3
aspect_ratio: "4/3"
tap_action: lightbox
hold_action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame
  data:
    content_id: "{{content_id}}"
```

### Example: Direct Action (No Lightbox)

```yaml
type: custom:folder-gallery-card
title: Quick Select
folder_sensor: sensor.store
folder: /local/frame_art/store
columns: 5
aspect_ratio: "1"
tap_action: action
action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame
  data:
    content_id: "{{content_id}}"
```

---

## Auto-Entities Gallery

Alternative method using `auto-entities` card (more complex but flexible).

### Installation

Install via HACS: Search "auto-entities"

### Personal Photos Gallery

```yaml
type: custom:auto-entities
card:
  type: grid
  columns: 4
  square: true
  title: 📷 My Photos
filter:
  template: |
    {% for img in state_attr('sensor.frame_art_personal_gallery', 'images') or [] %}
      {{
        {
          'type': 'picture',
          'image': img.path,
          'tap_action': {
            'action': 'call-service',
            'service': 'samsungtv_smart.art_select_image',
            'target': {
              'entity_id': 'media_player.samsung_frame'
            },
            'data': {
              'content_id': img.content_id,
              'show': true
            }
          }
        }
      }},
    {% endfor %}
show_empty: true
card_param: cards
```

### Art Store Gallery

```yaml
type: custom:auto-entities
card:
  type: grid
  columns: 4
  square: true
  title: 🎨 Art Store
filter:
  template: |
    {% for img in state_attr('sensor.frame_art_store_gallery', 'images') or [] %}
      {{
        {
          'type': 'picture',
          'image': img.path,
          'tap_action': {
            'action': 'call-service',
            'service': 'samsungtv_smart.art_select_image',
            'target': {
              'entity_id': 'media_player.samsung_frame'
            },
            'data': {
              'content_id': img.content_id
            }
          }
        }
      }},
    {% endfor %}
show_empty: true
card_param: cards
```

---

## Template Sensors

If using auto-entities, create these template sensors:

```yaml
# configuration.yaml
template:
  - sensor:
      # Personal Photos
      - name: "Frame Art Personal Gallery"
        unique_id: frame_art_personal_gallery
        state: >
          {% set list = state_attr('sensor.samsung_frame_art_list', 'content_list') or [] %}
          {% set personal = list | selectattr('category_id', 'eq', 'MY-C0002') | list %}
          {{ personal | length }}
        attributes:
          images: >
            {% set ns = namespace(images=[]) %}
            {% for item in state_attr('sensor.samsung_frame_art_list', 'content_list') or [] %}
              {% if item.category_id == 'MY-C0002' %}
                {% set ns.images = ns.images + [{
                  'path': '/local/frame_art/personal/' ~ item.content_id ~ '.jpg',
                  'filename': item.content_id ~ '.jpg',
                  'name': item.content_id,
                  'content_id': item.content_id
                }] %}
              {% endif %}
            {% endfor %}
            {{ ns.images }}
      
      # Art Store
      - name: "Frame Art Store Gallery"
        unique_id: frame_art_store_gallery
        state: >
          {% set list = state_attr('sensor.samsung_frame_art_list', 'content_list') or [] %}
          {% set store = list | selectattr('content_id', 'match', '^SAM-') | list %}
          {{ store | length }}
        attributes:
          images: >
            {% set ns = namespace(images=[]) %}
            {% for item in state_attr('sensor.samsung_frame_art_list', 'content_list') or [] %}
              {% if item.content_id.startswith('SAM-') %}
                {% set ns.images = ns.images + [{
                  'path': '/local/frame_art/store/' ~ item.content_id ~ '.jpg',
                  'filename': item.content_id ~ '.jpg',
                  'name': item.content_id,
                  'content_id': item.content_id
                }] %}
              {% endif %}
            {% endfor %}
            {{ ns.images }}
      
      # Favorites
      - name: "Frame Art Favorites Gallery"
        unique_id: frame_art_favorites_gallery
        state: >
          {% set list = state_attr('sensor.samsung_frame_art_list', 'content_list') or [] %}
          {% set favorites = list | selectattr('category_id', 'eq', 'MY-C0004') | list %}
          {{ favorites | length }}
        attributes:
          images: >
            {% set ns = namespace(images=[]) %}
            {% for item in state_attr('sensor.samsung_frame_art_list', 'content_list') or [] %}
              {% if item.category_id == 'MY-C0004' %}
                {% set subdir = 'personal' if item.content_id.startswith('MY_F') else ('store' if item.content_id.startswith('SAM-') else 'other') %}
                {% set ns.images = ns.images + [{
                  'path': '/local/frame_art/' ~ subdir ~ '/' ~ item.content_id ~ '.jpg',
                  'filename': item.content_id ~ '.jpg',
                  'name': item.content_id,
                  'content_id': item.content_id,
                  'subdirectory': subdir
                }] %}
              {% endif %}
            {% endfor %}
            {{ ns.images }}
```

---

## Advanced Layouts

### Responsive Columns

Adjust `columns` value for different layouts:

| Columns | Best For |
|---------|----------|
| 2 | Large thumbnails, mobile |
| 3 | Medium thumbnails, tablet |
| 4 | Default, desktop |
| 5-6 | Compact view, many images |

### Non-Square Thumbnails

```yaml
# Portrait (3:4)
aspect_ratio: "3/4"

# Landscape (16:9)
aspect_ratio: "16/9"

# Square
aspect_ratio: "1"

# Use height instead
image_height: 200px
```

### Card Styling with card-mod

```yaml
type: custom:folder-gallery-card
title: Styled Gallery
folder_sensor: sensor.store
folder: /local/frame_art/store
columns: 4
aspect_ratio: "1"
card_mod:
  style: |
    ha-card {
      border: 2px solid var(--primary-color);
      border-radius: 16px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }
    .gallery-item:hover {
      transform: scale(1.05);
      box-shadow: 0 8px 24px rgba(0,0,0,0.3);
    }
```

---

## Customization

### Multiple Galleries Dashboard

```yaml
type: vertical-stack
cards:
  - type: custom:folder-gallery-card
    title: ⭐ Favorites
    folder_sensor: sensor.store
    folder: /local/frame_art/store
    columns: 4
    aspect_ratio: "1"
    tap_action: lightbox
    hold_action:
      service: samsungtv_smart.art_select_image
      target:
        entity_id: media_player.samsung_frame
      data:
        content_id: "{{content_id}}"
  
  - type: custom:folder-gallery-card
    title: 📷 Personal
    folder_sensor: sensor.personal
    folder: /local/frame_art/personal
    columns: 4
    aspect_ratio: "1"
    tap_action: lightbox
    hold_action:
      service: samsungtv_smart.art_select_image
      target:
        entity_id: media_player.samsung_frame
      data:
        content_id: "{{content_id}}"
```

### Gallery with Controls Panel

```yaml
type: vertical-stack
cards:
  # Controls
  - type: horizontal-stack
    cards:
      - type: button
        name: Sync Thumbnails
        icon: mdi:sync
        tap_action:
          action: call-service
          service: samsungtv_smart.art_get_thumbnails_batch
          target:
            entity_id: media_player.samsung_frame
          data:
            favorites_only: true
            cleanup_orphans: true
      
      - type: button
        name: Art Mode
        icon: mdi:image-frame
        tap_action:
          action: call-service
          service: switch.toggle
          target:
            entity_id: switch.samsung_frame_frame_art_mode
  
  # Gallery
  - type: custom:folder-gallery-card
    title: Gallery
    folder_sensor: sensor.store
    folder: /local/frame_art/store
    columns: 4
    aspect_ratio: "1"
    tap_action: lightbox
    action:
      service: samsungtv_smart.art_select_image
      target:
        entity_id: media_player.samsung_frame
      data:
        content_id: "{{content_id}}"
```

---

## Troubleshooting

### Gallery Shows No Images

**Causes:**
1. Thumbnails not downloaded
2. Folder sensor not configured
3. Wrong folder path

**Solutions:**

```yaml
# 1. Download thumbnails
service: samsungtv_smart.art_get_thumbnails_batch
target:
  entity_id: media_player.samsung_frame
data:
  favorites_only: true

# 2. Check folder sensor in Developer Tools > States
# Look for: sensor.store (or your sensor name)
# Verify file_list attribute contains files

# 3. Verify files exist
# Check: /config/www/frame_art/store/
```

### Thumbnails Not Loading

**Causes:**
1. Wrong file paths
2. Files don't exist
3. Permission issues

**Solutions:**

```bash
# Check files exist
ls -lh /config/www/frame_art/store/

# Check permissions
chmod -R 755 /config/www/frame_art/

# Test URL in browser
http://YOUR_HA_IP:8123/local/frame_art/store/SAM-S1234567.jpg
```

### Click Not Working

**Causes:**
1. TV off or not in Art Mode
2. Invalid content_id
3. Wrong entity_id

**Solutions:**

```yaml
# Enable Art Mode first
service: switch.turn_on
target:
  entity_id: switch.samsung_frame_frame_art_mode

# Test with Developer Tools > Services
service: samsungtv_smart.art_select_image
target:
  entity_id: media_player.samsung_frame
data:
  content_id: SAM-S1234567
```

### Gallery Not Updating After Changes

**Issue:** New favorites or deleted items not reflected

**Solution:** Use cleanup_orphans and refresh sensor:

```yaml
# Automation or script
- action: samsungtv_smart.art_get_thumbnails_batch
  target:
    entity_id: media_player.samsung_frame
  data:
    favorites_only: true
    cleanup_orphans: true
- delay:
    seconds: 2
- action: homeassistant.update_entity
  target:
    entity_id: sensor.store
```

### Slow Loading with Many Images

**Issue:** Gallery loads slowly with 100+ images

**Solutions:**

1. Reduce `scan_interval` on folder sensor
2. Use pagination (first 20 images):
   ```yaml
   # With auto-entities
   filter:
     template: |
       {% set images = state_attr('sensor.frame_art_store_gallery', 'images') or [] %}
       {% for img in images[:20] %}
         ...
       {% endfor %}
   ```

3. Optimize thumbnails:
   ```bash
   # Resize all thumbnails
   apt-get install imagemagick
   cd /config/www/frame_art/store
   mogrify -resize 400x400 -quality 85 *.jpg
   ```

---

## Automation: Keep Gallery Synced

```yaml
alias: "Frame Art: Auto Sync Gallery"
triggers:
  - trigger: time_pattern
    hours: "/6"
actions:
  - action: samsungtv_smart.art_get_thumbnails_batch
    target:
      entity_id: media_player.samsung_frame
    data:
      favorites_only: true
      cleanup_orphans: true
  - delay:
      seconds: 2
  - action: homeassistant.update_entity
    target:
      entity_id: sensor.store
  - action: persistent_notification.create
    data:
      title: Frame Art
      message: Gallery synchronized
mode: single
```

---

## See Also

- **[Frame Art Guide](Frame_Art.md)** - Complete service documentation
- **[Main README](README.md)** - Integration overview and OAuth2 setup

---

Happy gallery building! 🖼️✨
