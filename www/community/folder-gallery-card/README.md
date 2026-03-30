# Folder Gallery Card

Custom Lovelace card for displaying image galleries from folders or sensors.

Perfect for Frame TV artwork galleries with click-to-display functionality.

---

## Installation

### Method 1: Copy to www folder (Recommended)

1. **Copy the card file:**
   ```bash
   mkdir -p /config/www/community/folder-gallery-card
   cp folder-gallery-card.js /config/www/community/folder-gallery-card/
   ```

2. **Add resource in Lovelace:**
   
   **Via UI:**
   - Settings → Dashboards → ⋮ (menu) → Resources
   - Add Resource
   - URL: `/local/community/folder-gallery-card/folder-gallery-card.js`
   - Type: JavaScript Module

   **Via YAML (configuration.yaml):**
   ```yaml
   lovelace:
     mode: yaml
     resources:
       - url: /local/community/folder-gallery-card/folder-gallery-card.js
         type: module
   ```

### Method 2: Direct from this repo

If you're using this integration from GitHub:

```yaml
lovelace:
  resources:
    - url: /local/community/folder-gallery-card/folder-gallery-card.js
      type: module
```

The file is already in the correct location!

---

## Quick Start

### Basic Gallery

```yaml
type: custom:folder-gallery-card
title: My Gallery
folder: /local/frame_art/personal
columns: 4
image_height: 150px
```

### Frame TV Gallery with Sensor

```yaml
type: custom:folder-gallery-card
title: "🖼️ Personal Artwork"
sensor: sensor.frame_art_personal_gallery
columns: 4
image_height: 180px
action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame_tv
  data:
    content_id: "{{content_id}}"
```

---

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `title` | string | - | Card title |
| `folder` | string | **required*** | Folder path (/local/...) |
| `sensor` | string | - | Sensor providing image list |
| `image_list` | array | - | Static list of images |
| `columns` | number | 4 | Number of columns |
| `image_height` | string | 150px | Image height |
| `gap` | string | 8px | Gap between images |
| `border_radius` | string | 8px | Corner radius |
| `show_filename` | boolean | true | Show filename on hover |
| `tap_action` | string | lightbox | Click action: `lightbox`, `action` |
| `hold_action` | object | - | Long press action |
| `action` | object | - | Service call configuration |

*Either `folder`, `sensor`, or `image_list` is required

---

## Template Variables

In `action.data`, you can use these variables:

| Template | Description |
|----------|-------------|
| `{{image_path}}` | Full image path |
| `{{filename}}` | File name |
| `{{name}}` | Name without extension |
| `{{content_id}}` | Content ID (for Frame TV) |
| `{{index}}` | Image index in list |

---

## Examples

### Personal Photos Gallery

```yaml
type: custom:folder-gallery-card
title: "📷 My Photos"
sensor: sensor.frame_art_personal_gallery
columns: 4
image_height: 150px
gap: 10px
border_radius: 12px
tap_action: lightbox
action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame_tv
  data:
    content_id: "{{content_id}}"
```

### Art Store Gallery

```yaml
type: custom:folder-gallery-card
title: "🎨 Art Store"
sensor: sensor.frame_art_store_gallery
columns: 5
image_height: 200px
show_filename: false
action:
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame_tv
  data:
    content_id: "{{content_id}}"
```

### With Multiple Actions

```yaml
type: custom:folder-gallery-card
title: "Gallery with Multiple Actions"
sensor: sensor.frame_art_gallery
columns: 4
image_height: 160px
tap_action: lightbox  # Click = open lightbox
hold_action:  # Long press = direct action
  service: samsungtv_smart.art_select_image
  target:
    entity_id: media_player.samsung_frame_tv
  data:
    content_id: "{{content_id}}"
```

---

## Required Template Sensors

For Frame TV galleries, add these template sensors to `configuration.yaml`:

```yaml
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
```

---

## Troubleshooting

### Images not displaying
1. Verify images are in `/config/www/...`
2. Path must start with `/local/...` (not `/config/www/`)
3. Check file permissions

### Sensor is empty
1. Verify `sensor.samsung_frame_art_list` exists
2. Reload template sensors after modification
3. Check logs for template errors

### Action not working
1. Test service manually in Developer Tools
2. Verify `content_id` is being passed
3. Check Home Assistant logs for errors

### Card not loading
1. Clear browser cache
2. Verify resource URL is correct
3. Check browser console for errors
4. Confirm JavaScript file exists at specified path

---

## See Also

- **[Frame Art Guide](../../docs/Frame_Art.md)** - Complete Frame Art documentation
- **[Gallery Configuration Guide](../../docs/Frame_Art_Gallery.md)** - Alternative gallery methods
- **[Configuration Examples](../../examples/frame_art/)** - Ready-to-use YAML files

---

**Version:** 3.0  
**Author:** Custom integration for Frame TV  
**License:** MIT
