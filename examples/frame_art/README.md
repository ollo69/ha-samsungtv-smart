# Frame Art Configuration Examples

Ready-to-use configuration files for Frame Art integration.

---

## Files Included

- **[configuration.yaml](configuration.yaml)** - Sensors, template sensors, input helpers
- **[scripts.yaml](scripts.yaml)** - 15+ utility scripts
- **[automations.yaml](automations.yaml)** - 20+ automation examples
- **[lovelace.yaml](lovelace.yaml)** - Complete interactive gallery dashboard

---

## Quick Start

### 1. Create Directory Structure

```bash
mkdir -p /config/www/frame_art/personal
mkdir -p /config/www/frame_art/store
mkdir -p /config/www/frame_art/other
```

### 2. Add Configuration

Copy relevant sections from `configuration.yaml` to your `/config/configuration.yaml`:

```yaml
# Minimum required: template sensors
template:
  - sensor:
      - name: "Frame Art Personal Gallery"
        # ... (copy from configuration.yaml)
```

### 3. Add Scripts (Optional)

Copy scripts from `scripts.yaml` to your `/config/scripts.yaml`

### 4. Add Automations (Optional)

Copy desired automations from `automations.yaml` to your `/config/automations.yaml`

### 5. Create Dashboard

Use `lovelace.yaml` as template for your Frame Art dashboard.

---

## File Details

### configuration.yaml

**Contains:**
- Folder sensors to track downloaded thumbnails
- Template sensors for galleries (Personal, Store, Favorites)
- Input helpers for brightness and matte control

**Required:**
- Template sensors (for galleries to work)

**Optional:**
- Folder sensors (tracking only)
- Input helpers (if using UI controls)

---

### scripts.yaml

**15+ Scripts Including:**
- Thumbnail downloads (all, personal, favorites, force)
- Time-based routines (morning, evening, night)
- Random artwork selection
- Matte style management
- Slideshow control

**All scripts are independent** - copy only what you need.

---

### automations.yaml

**20+ Automations Including:**
- Time-based brightness changes
- Auto-update thumbnails
- Motion-triggered artwork
- Weather-based artwork
- Presence-based routines
- Special occasions (birthdays, holidays)

**All automations are standalone** - choose what fits your needs.

---

### lovelace.yaml

**Complete Dashboard With:**
- Control panel (brightness, matte)
- Personal photos gallery
- Art Store gallery
- Favorites gallery
- Thumbnail management
- Quick action buttons

**Multiple layout options included** (4-column, 3-column, 2-column, mobile).

---

## Installation Options

### Option A: Copy Everything

```bash
# Backup first!
cp /config/configuration.yaml /config/configuration.yaml.backup
cp /config/scripts.yaml /config/scripts.yaml.backup
cp /config/automations.yaml /config/automations.yaml.backup

# Add all content from examples
cat examples/frame_art/configuration.yaml >> /config/configuration.yaml
cat examples/frame_art/scripts.yaml >> /config/scripts.yaml
cat examples/frame_art/automations.yaml >> /config/automations.yaml
```

### Option B: Selective Copy

1. Open each example file
2. Copy only sections you want
3. Paste into your corresponding config file
4. Adjust `entity_id` names if needed

---

## Customization

### Change Entity IDs

Replace throughout all files:
```
media_player.samsung_frame_tv → media_player.YOUR_TV_NAME
sensor.samsung_frame_art → sensor.YOUR_SENSOR_NAME
```

### Change Content IDs

In automations and scripts, update:
```
MY_F0001 → Your morning photo ID
MY_F0002 → Your evening photo ID
```

### Adjust Times

In automations, modify trigger times:
```yaml
trigger:
  - platform: time
    at: "07:00:00"  # Change to your preferred time
```

---

## Requirements

### Mandatory

1. **SamsungTV Smart integration** installed
2. **auto-entities** card installed (for galleries)
3. **Frame TV** connected and configured

### Optional But Recommended

4. **card-mod** (for styling)
5. **Browser Mod** (for advanced features)

---

## Testing

### Test Template Sensors

After adding template sensors to `configuration.yaml`:

1. Restart Home Assistant
2. Go to Developer Tools > States
3. Search for `sensor.frame_art_personal_gallery`
4. Check attributes contain `images` list

### Test Scripts

After adding scripts:

1. Go to Developer Tools > Services
2. Search for `script.frame_art_download_all`
3. Call the service
4. Check thumbnails in `/config/www/frame_art/`

### Test Automations

After adding automations:

1. Go to Settings > Automations
2. Find your Frame Art automations
3. Check for configuration errors
4. Manually trigger to test

### Test Dashboard

After creating Lovelace dashboard:

1. Open dashboard
2. Verify galleries show thumbnails
3. Click thumbnail to test TV display
4. Test all control buttons

---

## Common Issues

### Galleries Empty

**Cause:** Template sensors not working or thumbnails not downloaded

**Fix:**
```yaml
# Download thumbnails first
service: samsungtv_smart.art_get_thumbnails_batch
data:
  entity_id: media_player.samsung_frame_tv

# Restart Home Assistant
# Settings > System > Restart
```

### Automations Not Running

**Cause:** Entity IDs don't match

**Fix:**
1. Check your TV entity_id
2. Replace in all automations
3. Restart Home Assistant

### Scripts Not Appearing

**Cause:** YAML syntax error

**Fix:**
1. Check YAML configuration
2. Developer Tools > YAML > Check Configuration
3. Fix any errors shown
4. Restart Home Assistant

---

## Performance Notes

### First-Time Setup

- Download all thumbnails: 2-5 minutes
- Template sensors creation: Instant
- Dashboard loading: 1-2 seconds

### Daily Operation

- Auto-update thumbnails: 2-5 seconds (skips existing)
- Gallery refresh: Instant
- Artwork change: <1 second

---

## Next Steps

After installation:

1. 📖 Read [Frame Art Guide](../../docs/Frame_Art.md)
2. 🖼️ Read [Gallery Guide](../../docs/Frame_Art_Gallery.md)
3. 🎨 Customize to your preferences
4. 🤖 Add your own automations

---

## Support

- 📚 [Documentation](../../docs/)
- 🐛 [Report Issues](https://github.com/ollo69/ha-samsungtv-smart/issues)
- 💬 [Community Forum](https://community.home-assistant.io/)

---

**All examples are tested and working!** 🎨✨
