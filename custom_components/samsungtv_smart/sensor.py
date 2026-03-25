"""Samsung Frame TV Art Mode sensor entity."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_ID, CONF_NAME, CONF_PORT, CONF_TOKEN, LIGHT_LUX
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from pysmartthings import Attribute, Capability

from .api.art import SamsungTVAsyncArt
from .const import (
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_ST_ENTRY,
    CONF_API_KEY,
    CONF_AUTH_METHOD,
    CONF_DEVICE_ID,
    CONF_OAUTH_TOKEN,
    CONF_WS_NAME,
    DATA_ART_API,
    DATA_CFG,
    DEFAULT_PORT,
    DOMAIN,
    WS_PREFIX,
)
from . import async_get_samsungtv_api_key

_LOGGER = logging.getLogger(__name__)

# Update interval for the Frame Art sensor (reduced for faster manual updates)
SCAN_INTERVAL = timedelta(seconds=15)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Samsung Frame Art sensor from config entry."""
    config = hass.data[DOMAIN][entry.entry_id][DATA_CFG]
    host = config[CONF_HOST]
    port = config.get(CONF_PORT, DEFAULT_PORT)
    token = config.get(CONF_TOKEN)
    ws_name = config.get(CONF_WS_NAME, "HomeAssistant")

    # Get device unique ID - must match entity.py logic for device grouping
    device_unique_id = config.get(CONF_ID, entry.entry_id)

    # Get device name from config or entry title, fallback to host
    device_name = config.get(CONF_NAME) or entry.title or host
    
    session = async_get_clientsession(hass)
    
    entities = []
    
    # Create the Art API instance
    art_api = SamsungTVAsyncArt(
        host=host,
        port=port,
        token=token,
        session=session,
        timeout=5,
        name=f"{WS_PREFIX} {ws_name} Art",
    )
    
    # Quick check if Frame TV is supported (with short timeout)
    try:
        async with asyncio.timeout(5):
            is_supported = await art_api.supported()
    except asyncio.TimeoutError:
        _LOGGER.debug("Timeout checking Frame TV support for %s", host)
        is_supported = False
    except Exception as ex:
        _LOGGER.debug("Frame TV support check failed: %s", ex)
        is_supported = False
    
    if is_supported:
        # Create www/frame_art directory if it doesn't exist
        import os
        www_path = hass.config.path("www", "frame_art")
        try:
            os.makedirs(www_path, exist_ok=True)
            _LOGGER.debug("Frame Art directory ready: %s", www_path)
        except Exception as ex:
            _LOGGER.warning("Could not create frame_art directory: %s", ex)
        
        # Store art_api in hass.data for sharing with media_player
        hass.data[DOMAIN][entry.entry_id][DATA_ART_API] = art_api
        
        # Create the coordinator
        coordinator = FrameArtCoordinator(hass, art_api, entry)
        
        # Add Frame Art sensor
        entities.append(FrameArtSensor(coordinator, entry, art_api, device_name, device_unique_id))
        
        # Schedule first refresh in background (non-blocking)
        hass.async_create_background_task(
            coordinator.async_request_refresh(),
            f"frame_art_initial_refresh_{entry.entry_id}",
        )
    else:
        _LOGGER.info("Frame TV art mode not supported on %s", host)
    
    # Add SmartThings sensors if SmartThings is configured
    api_key = config.get(CONF_API_KEY)
    device_id = config.get(CONF_DEVICE_ID)
    auth_method = config.get(CONF_AUTH_METHOD)
    
    # For OAuth, get token from oauth_token if api_key is not available
    if auth_method == AUTH_METHOD_OAUTH and not api_key:
        oauth_token = config.get(CONF_OAUTH_TOKEN)
        if oauth_token and isinstance(oauth_token, dict):
            api_key = oauth_token.get("access_token")
            _LOGGER.debug("SmartThings sensors using OAuth token")
    
    if api_key and device_id:
        try:
            # Create SmartThings client for initial setup
            from pysmartthings import SmartThings
            st_client = SmartThings(session=session)
            st_client.authenticate(api_key)
            
            # Get the main TV device info
            main_device = await st_client.get_device(device_id)
            main_location_id = main_device.location_id
            main_room_id = main_device.room_id
            
            _LOGGER.debug(
                "Main TV device: %s (location: %s, room: %s)",
                main_device.label,
                main_location_id,
                main_room_id,
            )
            
            # Get ALL devices in the location
            all_devices = await st_client.get_devices()
            
            # Find child devices (same location + parent_device_id or same room)
            related_devices = []
            for device in all_devices:
                # Skip the main TV device
                if device.device_id == device_id:
                    continue
                
                # Check if it's a child device
                is_child = (
                    device.parent_device_id == device_id
                    or (
                        device.location_id == main_location_id
                        and main_room_id
                        and device.room_id == main_room_id
                        and "light sensor" in device.label.lower()
                    )
                )
                
                if is_child:
                    _LOGGER.debug(
                        "Found related device: %s (parent: %s, room: %s)",
                        device.label,
                        device.parent_device_id,
                        device.room_id,
                    )
                    related_devices.append(device)
            
            # Add sensors for related devices with light sensor capabilities
            for device in related_devices:
                try:
                    components = await st_client.get_device_status(device.device_id)
                    
                    # Check for illuminance sensor
                    if (
                        "main" in components
                        and Capability.ILLUMINANCE_MEASUREMENT in components["main"]
                        and Attribute.ILLUMINANCE in components["main"][Capability.ILLUMINANCE_MEASUREMENT]
                    ):
                        _LOGGER.info(
                            "Adding illuminance sensor for %s (child of %s)",
                            device.label,
                            device_name,
                        )
                        entities.append(
                            SmartThingsIlluminanceSensor(
                                hass=hass,
                                entry=entry,
                                session=session,
                                device_id=device.device_id,
                                device_name=device.label,
                                parent_device_id=device_unique_id,
                            )
                        )
                    
                    # Check for brightness intensity sensor
                    if (
                        "main" in components
                        and Capability.RELATIVE_BRIGHTNESS in components["main"]
                        and Attribute.BRIGHTNESS_INTENSITY in components["main"][Capability.RELATIVE_BRIGHTNESS]
                    ):
                        _LOGGER.info(
                            "Adding brightness intensity sensor for %s (child of %s)",
                            device.label,
                            device_name,
                        )
                        entities.append(
                            SmartThingsBrightnessIntensitySensor(
                                hass=hass,
                                entry=entry,
                                session=session,
                                device_id=device.device_id,
                                device_name=device.label,
                                parent_device_id=device_unique_id,
                            )
                        )
                    
                    if (
                        "main" not in components
                        or (
                            Capability.ILLUMINANCE_MEASUREMENT not in components["main"]
                            and Capability.RELATIVE_BRIGHTNESS not in components["main"]
                        )
                    ):
                        _LOGGER.debug(
                            "Device %s does not have light sensor capabilities",
                            device.label,
                        )
                except Exception as ex:
                    _LOGGER.warning(
                        "Error checking device %s: %s", device.label, ex
                    )
            
            if not related_devices:
                _LOGGER.debug(
                    "No child devices found for %s (device_id: %s)",
                    device_name,
                    device_id,
                )
        except Exception as ex:
            _LOGGER.warning("Could not setup SmartThings sensors: %s", ex)
    
    if entities:
        async_add_entities(entities)


class FrameArtCoordinator(DataUpdateCoordinator):
    """Coordinator for Frame Art data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        art_api: SamsungTVAsyncArt,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Frame Art {entry.title}",
            update_interval=SCAN_INTERVAL,
        )
        self._art_api = art_api
        self._entry = entry
        self._hass = hass
        self._last_content_id: str | None = None
        # Enabled by default - thumbnails are fetched for current artwork
        self._thumbnail_fetch_enabled = True
        self._thumbnail_failures = 0
        
        # Connection failure tracking to prevent infinite reconnection loops
        self._connection_failures = 0
        self._max_connection_failures = 5
        self._backoff_until: float | None = None
        
        _LOGGER.info("Frame Art Coordinator initialized with thumbnail fetching enabled")

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Frame TV."""
        # Check if we're in backoff period (after multiple connection failures)
        if self._backoff_until is not None:
            if time.time() < self._backoff_until:
                # Still in backoff period, skip update
                _LOGGER.debug(
                    "Frame Art: Skipping update due to connection backoff (%.0fs remaining)",
                    self._backoff_until - time.time()
                )
                # Return minimal data during backoff
                return {
                    "art_mode": "unavailable",
                    "current_artwork": None,
                    "artwork_count": None,
                    "slideshow_status": None,
                    "api_version": None,
                    "current_thumbnail_url": None,
                    "tv_powered_off": False,
                }
            else:
                # Backoff period expired, reset and try again
                _LOGGER.info("Frame Art: Backoff period expired, resuming updates")
                self._backoff_until = None
                self._connection_failures = 0
        
        data = {
            "art_mode": None,
            "current_artwork": None,
            "artwork_count": None,
            "slideshow_status": None,
            "api_version": None,
            "current_thumbnail_url": None,
            "tv_powered_off": False,
        }
        
        # FIRST: Check if TV is powered off
        if self._is_tv_powered_off():
            _LOGGER.debug("Frame Art: TV is powered off, returning minimal data")
            data["tv_powered_off"] = True
            data["art_mode"] = "off"
            # Keep current_thumbnail_url from last known state (for Lovelace display)
            if self._has_current_thumbnail():
                data["current_thumbnail_url"] = "/local/frame_art/current.jpg"
            # Keep artwork_count from previous data if available
            if self.data and self.data.get("artwork_count") is not None:
                data["artwork_count"] = self.data["artwork_count"]
            # Keep current_artwork (current_content_id) from previous data for Lovelace
            if self.data and self.data.get("current_artwork"):
                data["current_artwork"] = self.data["current_artwork"]
            # Return immediately with minimal data when TV is off
            return data
        
        try:
            # First, try to get art_mode from media_player state (more reliable)
            # This avoids double API calls and keeps sensor in sync with media_player
            media_player_art_mode = self._get_media_player_art_mode()
            if media_player_art_mode is not None:
                data["art_mode"] = media_player_art_mode
                _LOGGER.debug("Frame Art: Using media_player art_mode_status: %s", media_player_art_mode)
            else:
                # Fallback to direct API call if media_player state not available
                try:
                    async with asyncio.timeout(8):
                        art_mode = await self._art_api.get_artmode()
                        data["art_mode"] = art_mode
                        _LOGGER.debug("Frame Art: Direct API art_mode: %s", art_mode)
                except asyncio.TimeoutError:
                    _LOGGER.debug("Timeout getting art mode status")
                except Exception as ex:
                    _LOGGER.debug("Error getting art mode: %s", ex)
            
            # Get current artwork with timeout
            content_id = None
            try:
                async with asyncio.timeout(8):
                    current = await self._art_api.get_current()
                    if current:
                        content_id = current.get("content_id")
                        data["current_artwork"] = {
                            "content_id": content_id,
                            "category_id": current.get("category_id"),
                            "matte_id": current.get("matte_id"),
                        }
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout getting current artwork")
            except Exception as ex:
                _LOGGER.debug("Error getting current artwork: %s", ex)
            
            # Only fetch thumbnail if:
            # - Thumbnail fetching is enabled
            # - We have a content_id
            # - Content has changed OR we don't have a thumbnail yet
            if (
                self._thumbnail_fetch_enabled
                and content_id
                and (content_id != self._last_content_id or not self._has_current_thumbnail())
            ):
                _LOGGER.info(
                    "Frame Art: Triggering thumbnail fetch for %s (changed: %s, has_thumbnail: %s)",
                    content_id,
                    content_id != self._last_content_id,
                    self._has_current_thumbnail()
                )
                # Schedule thumbnail fetch as background task (non-blocking)
                self._hass.async_create_background_task(
                    self._fetch_and_save_thumbnail(content_id),
                    f"frame_art_thumbnail_{content_id}",
                )
                self._last_content_id = content_id
            elif content_id and not self._thumbnail_fetch_enabled:
                _LOGGER.debug("Frame Art: Thumbnail fetching disabled, skipping %s", content_id)
            elif content_id:
                _LOGGER.debug(
                    "Frame Art: Skipping thumbnail fetch - same content_id %s, has_thumbnail: %s",
                    content_id,
                    self._has_current_thumbnail()
                )
            
            # If we have a saved thumbnail, use it
            if self._has_current_thumbnail():
                data["current_thumbnail_url"] = "/local/frame_art/current.jpg"
            
            # Get artwork count (less frequently, only if art_mode is on)
            if data["art_mode"] == "on":
                try:
                    async with asyncio.timeout(15):
                        artwork_list = await self._art_api.available()
                        data["artwork_count"] = len(artwork_list) if artwork_list else 0
                except asyncio.TimeoutError:
                    _LOGGER.debug("Timeout getting artwork list")
                except Exception as ex:
                    _LOGGER.debug("Error getting artwork list: %s", ex)
            
            # Get slideshow status with timeout
            try:
                async with asyncio.timeout(8):
                    slideshow = await self._art_api.get_slideshow_status()
                    if slideshow:
                        data["slideshow_status"] = slideshow.get("value", "off")
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout getting slideshow status")
            except Exception as ex:
                _LOGGER.debug("Error getting slideshow status: %s", ex)
                
        except Exception as ex:
            # Track connection failures to prevent infinite reconnection loops
            error_msg = str(ex).lower()
            is_connection_error = any(
                keyword in error_msg
                for keyword in ["connect", "timeout", "closed", "transport"]
            )
            
            if is_connection_error:
                self._connection_failures += 1
                _LOGGER.warning(
                    "Frame Art: Connection error (%d/%d): %s",
                    self._connection_failures,
                    self._max_connection_failures,
                    ex
                )
                
                # If too many consecutive failures, enter backoff period
                if self._connection_failures >= self._max_connection_failures:
                    # Exponential backoff: 5 minutes, then 15 minutes, then 30 minutes
                    backoff_minutes = min(5 * (2 ** (self._connection_failures - self._max_connection_failures)), 30)
                    self._backoff_until = time.time() + (backoff_minutes * 60)
                    _LOGGER.warning(
                        "Frame Art: Too many connection failures (%d), "
                        "entering %d minute backoff period. "
                        "Frame Art sensor will pause updates until backoff expires.",
                        self._connection_failures,
                        backoff_minutes
                    )
            else:
                _LOGGER.warning("Frame Art: Error updating data: %s", ex)
            
            # Don't raise UpdateFailed, just return partial data
        else:
            # Update successful, reset failure counter
            if self._connection_failures > 0:
                _LOGGER.info("Frame Art: Update successful, resetting failure counter")
                self._connection_failures = 0
            
        return data

    def _is_tv_powered_off(self) -> bool:
        """Check if the TV (media_player) is powered off."""
        try:
            # Find media_player entity for this config entry
            from homeassistant.helpers import entity_registry as er
            entity_registry = er.async_get(self._hass)
            
            for entity in entity_registry.entities.values():
                if (
                    entity.config_entry_id == self._entry.entry_id
                    and entity.domain == "media_player"
                ):
                    state = self._hass.states.get(entity.entity_id)
                    if state:
                        # TV is powered off if media_player state is "off" or "unavailable"
                        return state.state in ("off", "unavailable")
                    break
        except Exception as ex:
            _LOGGER.debug("Could not check media_player power state: %s", ex)
        return False

    def _get_media_player_art_mode(self) -> str | None:
        """Get art_mode_status from the linked media_player entity."""
        try:
            # Find media_player entity for this config entry
            from homeassistant.helpers import entity_registry as er
            entity_registry = er.async_get(self._hass)
            
            for entity in entity_registry.entities.values():
                if (
                    entity.config_entry_id == self._entry.entry_id
                    and entity.domain == "media_player"
                ):
                    state = self._hass.states.get(entity.entity_id)
                    if state and state.attributes:
                        art_mode_status = state.attributes.get("art_mode_status")
                        if art_mode_status:
                            return art_mode_status
                    break
        except Exception as ex:
            _LOGGER.debug("Could not get media_player art_mode_status: %s", ex)
        return None

    def _has_current_thumbnail(self) -> bool:
        """Check if current thumbnail file exists."""
        import os
        www_path = self._hass.config.path("www", "frame_art", "current.jpg")
        return os.path.isfile(www_path)

    def _create_drm_placeholder(self) -> bytes:
        """Create a DRM Protected placeholder image.
        
        Creates a dark image with visual indication that content is DRM protected.
        Uses PIL if available for better quality, otherwise creates a basic PNG.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            # Create image with PIL
            width, height = 480, 320
            img = Image.new('RGB', (width, height), color=(30, 30, 35))
            draw = ImageDraw.Draw(img)
            
            # Draw border
            draw.rectangle([10, 10, width-10, height-10], outline=(60, 60, 70), width=2)
            
            # Draw lock icon (simple representation)
            lock_x, lock_y = width // 2, height // 2 - 30
            # Lock body
            draw.rectangle([lock_x-25, lock_y, lock_x+25, lock_y+40], fill=(80, 80, 90), outline=(100, 100, 110))
            # Lock shackle
            draw.arc([lock_x-18, lock_y-25, lock_x+18, lock_y+5], 0, 180, fill=(100, 100, 110), width=4)
            
            # Try to use a font, fall back to default
            try:
                font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            except Exception:
                font_large = ImageFont.load_default()
                font_small = ImageFont.load_default()
            
            # Draw text
            text1 = "DRM Protected"
            text2 = "Art Store Content"
            
            # Center text
            bbox1 = draw.textbbox((0, 0), text1, font=font_large)
            bbox2 = draw.textbbox((0, 0), text2, font=font_small)
            
            x1 = (width - (bbox1[2] - bbox1[0])) // 2
            x2 = (width - (bbox2[2] - bbox2[0])) // 2
            
            draw.text((x1, lock_y + 55), text1, fill=(200, 200, 210), font=font_large)
            draw.text((x2, lock_y + 85), text2, fill=(140, 140, 150), font=font_small)
            
            # Save to bytes
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            return buffer.getvalue()
            
        except ImportError:
            # PIL not available, create a simple PNG
            import struct
            import zlib
            
            width, height = 400, 300
            
            # PNG signature
            signature = b'\x89PNG\r\n\x1a\n'
            
            # IHDR chunk
            ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
            
            # IDAT chunk - create simple dark image with lighter center
            raw_data = b''
            for y in range(height):
                raw_data += b'\x00'  # filter byte
                for x in range(width):
                    # Dark background
                    gray = 35
                    # Lighter rectangle in center (where text would be)
                    if 80 < x < 320 and 100 < y < 200:
                        gray = 50
                    # Border
                    if x < 5 or x > width - 5 or y < 5 or y > height - 5:
                        gray = 60
                    raw_data += bytes([gray, gray, gray + 5])
            
            compressed = zlib.compress(raw_data, 9)
            idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
            idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
            
            # IEND chunk
            iend_crc = zlib.crc32(b'IEND') & 0xffffffff
            iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
            
            return signature + ihdr + idat + iend

    async def _save_drm_placeholder(self, content_id: str) -> None:
        """Save a DRM placeholder image when thumbnail fetch fails due to DRM."""
        try:
            import os
            www_path = self._hass.config.path("www", "frame_art")
            
            def _write_placeholder():
                os.makedirs(www_path, exist_ok=True)
                
                # Create a simple text file as placeholder indicator
                # and a dark image
                placeholder_data = self._create_drm_placeholder()
                
                # Save as current.jpg (actually PNG but browsers handle it)
                file_path = os.path.join(www_path, "current.jpg")
                with open(file_path, "wb") as f:
                    f.write(placeholder_data)
                
                # Save DRM marker file
                drm_marker = os.path.join(www_path, "current_drm.txt")
                with open(drm_marker, "w") as f:
                    f.write(f"DRM Protected: {content_id}\n")
                
                return file_path
            
            await self._hass.async_add_executor_job(_write_placeholder)
            _LOGGER.debug("Saved DRM placeholder for %s", content_id)
            
        except Exception as ex:
            _LOGGER.debug("Error saving DRM placeholder: %s", ex)

    async def _fetch_and_save_thumbnail(self, content_id: str) -> None:
        """Fetch and save thumbnail in background (non-blocking)."""
        import os
        
        _LOGGER.info("Frame Art: Starting thumbnail fetch for %s", content_id)
        
        # Check if this is a Store image (SAM-S*) - these are DRM protected
        is_store_image = content_id.startswith("SAM-S")
        if is_store_image:
            _LOGGER.debug("Frame Art: %s is a Store image (may be DRM protected)", content_id)
        
        try:
            async with asyncio.timeout(20):  # Longer timeout for thumbnails
                _LOGGER.debug("Frame Art: Calling get_thumbnail API for %s", content_id)
                thumbnail_data = await self._art_api.get_thumbnail(content_id)
                
                _LOGGER.info(
                    "Frame Art: get_thumbnail returned %d bytes for %s",
                    len(thumbnail_data) if thumbnail_data else 0,
                    content_id
                )
                
                if thumbnail_data and len(thumbnail_data) > 1:
                    www_path = self._hass.config.path("www", "frame_art")
                    
                    def _write_thumbnails():
                        os.makedirs(www_path, exist_ok=True)
                        
                        # Remove DRM marker if it exists
                        drm_marker = os.path.join(www_path, "current_drm.txt")
                        if os.path.exists(drm_marker):
                            os.remove(drm_marker)
                        
                        # Save as current.jpg
                        file_path = os.path.join(www_path, "current.jpg")
                        with open(file_path, "wb") as f:
                            f.write(thumbnail_data)
                        
                        # Also save with content_id name for gallery
                        content_file = f"{content_id.replace(':', '_')}.jpg"
                        content_path = os.path.join(www_path, content_file)
                        with open(content_path, "wb") as f:
                            f.write(thumbnail_data)
                        
                        _LOGGER.info("Frame Art: Written thumbnail to %s", file_path)
                        return file_path, content_path
                    
                    # Run file I/O in executor to avoid blocking
                    await self._hass.async_add_executor_job(_write_thumbnails)
                    
                    _LOGGER.info("Frame Art: Successfully saved thumbnail for %s", content_id)
                    self._thumbnail_failures = 0
                    
                    # Trigger state update
                    self.async_set_updated_data(self.data)
                else:
                    # No data or empty data - likely DRM protected
                    _LOGGER.info(
                        "Frame Art: No thumbnail data for %s (got %d bytes, DRM protected?)",
                        content_id,
                        len(thumbnail_data) if thumbnail_data else 0
                    )
                    await self._save_drm_placeholder(content_id)
                    
        except asyncio.TimeoutError:
            self._thumbnail_failures += 1
            _LOGGER.warning(
                "Frame Art: Timeout fetching thumbnail for %s (failure %d/3)",
                content_id,
                self._thumbnail_failures,
            )
            
            # For store images, save DRM placeholder instead of disabling
            if is_store_image:
                await self._save_drm_placeholder(content_id)
            elif self._thumbnail_failures >= 3:
                _LOGGER.warning(
                    "Frame Art: Disabling automatic thumbnail fetch after %d failures. "
                    "Use art_get_thumbnail service to fetch manually.",
                    self._thumbnail_failures,
                )
                self._thumbnail_fetch_enabled = False
                
        except Exception as ex:
            _LOGGER.warning("Frame Art: Error fetching thumbnail for %s: %s", content_id, ex)
            # For store images, assume DRM and save placeholder
            if is_store_image:
                await self._save_drm_placeholder(content_id)


class FrameArtSensor(CoordinatorEntity, SensorEntity):
    """Sensor entity for Samsung Frame TV Art Mode."""

    _attr_icon = "mdi:image-frame"

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        art_api: SamsungTVAsyncArt,
        device_name: str,
        device_unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._art_api = art_api
        self._attr_unique_id = f"{entry.entry_id}_frame_art"
        # Use explicit name instead of has_entity_name to avoid "None" prefix
        self._attr_name = f"{device_name} Frame Art"
        self._last_service_result: dict[str, Any] | None = None

        # Device info to link with the main TV entity
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_unique_id)},
        )

    @property
    def native_value(self) -> str | None:
        """Return the current art mode status."""
        if self.coordinator.data:
            return self.coordinator.data.get("art_mode")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {}
        
        if self.coordinator.data:
            data = self.coordinator.data
            
            # If TV is powered off, return minimal attributes
            if data.get("tv_powered_off", False):
                attrs["art_mode_status"] = "off"
                # Keep artwork_count if we have it (from last time TV was on)
                if data.get("artwork_count") is not None:
                    attrs["artwork_count"] = data["artwork_count"]
                # Keep current_thumbnail_url for Lovelace display
                if data.get("current_thumbnail_url"):
                    attrs["current_thumbnail_url"] = data["current_thumbnail_url"]
                # Keep current_content_id for Lovelace display
                if data.get("current_artwork"):
                    current = data["current_artwork"]
                    content_id = current.get("content_id")
                    if content_id:
                        attrs["current_content_id"] = content_id
                # Add indicator that TV is off
                attrs["tv_power_state"] = "off"
                # Thumbnail auto-fetch status
                attrs["thumbnail_auto_fetch"] = self.coordinator._thumbnail_fetch_enabled
                return attrs
            
            # TV is on - return full attributes
            attrs["tv_power_state"] = "on"
            
            # Art mode status
            if data.get("art_mode") is not None:
                attrs["art_mode_status"] = data["art_mode"]
            
            # Current artwork details (only when TV is on)
            if data.get("current_artwork"):
                current = data["current_artwork"]
                content_id = current.get("content_id")
                attrs["current_content_id"] = content_id
                attrs["current_category_id"] = current.get("category_id")
                attrs["current_matte_id"] = current.get("matte_id")
                
                # Check if current image is DRM protected (SAM-S* = Art Store)
                if content_id:
                    is_drm = content_id.startswith("SAM-S")
                    attrs["current_is_drm_protected"] = is_drm
                    if is_drm:
                        attrs["current_content_type"] = "Art Store (DRM)"
                    elif content_id.startswith("MY_F"):
                        attrs["current_content_type"] = "My Photos"
                    elif content_id.startswith("SAM-"):
                        attrs["current_content_type"] = "Samsung Collection"
                    else:
                        attrs["current_content_type"] = "Unknown"
            
            # Current thumbnail URL (for Lovelace)
            if data.get("current_thumbnail_url"):
                attrs["current_thumbnail_url"] = data["current_thumbnail_url"]
            
            # Artwork count
            if data.get("artwork_count") is not None:
                attrs["artwork_count"] = data["artwork_count"]
            
            # Slideshow status
            if data.get("slideshow_status") is not None:
                attrs["slideshow_status"] = data["slideshow_status"]
            
            # API version
            if data.get("api_version") is not None:
                attrs["api_version"] = data["api_version"]
        
        # Thumbnail auto-fetch status
        attrs["thumbnail_auto_fetch"] = self.coordinator._thumbnail_fetch_enabled
        
        # Last service result (for debugging/monitoring service calls)
        if self._last_service_result:
            attrs["last_service_result"] = self._last_service_result
        
        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    async def async_set_artmode(self, enabled: bool) -> dict:
        """Enable or disable Art Mode."""
        try:
            await self._art_api.set_artmode(enabled)
            result = {"service": "set_artmode", "success": True, "enabled": enabled}
        except Exception as ex:
            result = {"service": "set_artmode", "error": str(ex)}
        self._last_service_result = result
        await self.coordinator.async_request_refresh()
        return result

    async def async_select_image(
        self,
        content_id: str,
        category_id: str | None = None,
        show: bool = True,
    ) -> dict:
        """Select and display artwork."""
        try:
            await self._art_api.select_image(content_id, category_id, show)
            result = {
                "service": "select_image",
                "success": True,
                "content_id": content_id,
            }
        except Exception as ex:
            result = {"service": "select_image", "error": str(ex)}
        self._last_service_result = result
        await self.coordinator.async_request_refresh()
        return result

    async def async_get_available(self, category_id: str | None = None) -> dict:
        """Get list of available artwork."""
        try:
            artwork_list = await self._art_api.available(category_id)
            result = {
                "service": "get_available",
                "success": True,
                "count": len(artwork_list) if artwork_list else 0,
                "artwork": artwork_list,
            }
        except Exception as ex:
            result = {"service": "get_available", "error": str(ex)}
        self._last_service_result = result
        self.async_write_ha_state()
        return result

    async def async_upload_image(
        self,
        file_path: str,
        matte_id: str | None = None,
        file_type: str = "png",
    ) -> dict:
        """Upload an image to the TV."""
        try:
            content_id = await self._art_api.upload(
                file_path,
                matte=matte_id or "shadowbox_polar",
                file_type=file_type,
            )
            result = {
                "service": "upload_image",
                "success": content_id is not None,
                "content_id": content_id,
            }
        except Exception as ex:
            result = {"service": "upload_image", "error": str(ex)}
        self._last_service_result = result
        await self.coordinator.async_request_refresh()
        return result

    async def async_delete_image(self, content_id: str) -> dict:
        """Delete an uploaded image."""
        try:
            success = await self._art_api.delete(content_id)
            result = {
                "service": "delete_image",
                "success": success,
                "content_id": content_id,
            }
        except Exception as ex:
            result = {"service": "delete_image", "error": str(ex)}
        self._last_service_result = result
        await self.coordinator.async_request_refresh()
        return result

    async def async_set_slideshow(
        self,
        duration: int = 0,
        shuffle: bool = True,
        category_id: int = 2,
    ) -> dict:
        """Configure slideshow settings."""
        try:
            success = await self._art_api.set_slideshow_status(
                duration=duration,
                shuffle=shuffle,
                category=category_id,
            )
            result = {
                "service": "set_slideshow",
                "success": success,
                "duration": duration,
                "shuffle": shuffle,
            }
        except Exception as ex:
            result = {"service": "set_slideshow", "error": str(ex)}
        self._last_service_result = result
        await self.coordinator.async_request_refresh()
        return result

    async def async_change_matte(
        self,
        content_id: str,
        matte_id: str,
    ) -> dict:
        """Change the matte/frame style for artwork."""
        try:
            success = await self._art_api.change_matte(content_id, matte_id)
            result = {
                "service": "change_matte",
                "success": success,
                "content_id": content_id,
                "matte_id": matte_id,
            }
        except Exception as ex:
            result = {"service": "change_matte", "error": str(ex)}
        self._last_service_result = result
        self.async_write_ha_state()
        return result

    async def async_set_photo_filter(
        self,
        content_id: str,
        filter_id: str,
    ) -> dict:
        """Apply a photo filter to artwork."""
        try:
            success = await self._art_api.set_photo_filter(content_id, filter_id)
            result = {
                "service": "set_photo_filter",
                "success": success,
                "content_id": content_id,
                "filter_id": filter_id,
            }
        except Exception as ex:
            result = {"service": "set_photo_filter", "error": str(ex)}
        self._last_service_result = result
        self.async_write_ha_state()
        return result

    async def async_set_favourite(
        self,
        content_id: str,
        status: str = "on",
    ) -> dict:
        """Add or remove artwork from favorites."""
        try:
            success = await self._art_api.set_favourite(content_id, status)
            result = {
                "service": "set_favourite",
                "success": success,
                "content_id": content_id,
                "status": status,
            }
        except Exception as ex:
            result = {"service": "set_favourite", "error": str(ex)}
        self._last_service_result = result
        self.async_write_ha_state()
        return result

    async def async_enable_thumbnail_fetch(self, enabled: bool = True) -> dict:
        """Enable or disable automatic thumbnail fetching.
        
        If thumbnail fetching times out repeatedly, it is automatically disabled.
        Use this method to re-enable it.
        """
        self.coordinator._thumbnail_fetch_enabled = enabled
        self.coordinator._thumbnail_failures = 0
        result = {
            "service": "enable_thumbnail_fetch",
            "success": True,
            "enabled": enabled,
        }
        self._last_service_result = result
        self.async_write_ha_state()
        
        # If enabling, trigger an immediate refresh
        if enabled:
            await self.coordinator.async_request_refresh()
        
        return result

    async def async_get_thumbnail(self, content_id: str) -> dict:
        """Manually fetch and save a thumbnail for a specific artwork."""
        try:
            thumbnail_data = await self._art_api.get_thumbnail(content_id, timeout=30)
            if thumbnail_data:
                import os
                www_path = self.hass.config.path("www", "frame_art")
                
                def _write_thumbnail():
                    os.makedirs(www_path, exist_ok=True)
                    file_name = f"{content_id.replace(':', '_')}.jpg"
                    file_path = os.path.join(www_path, file_name)
                    with open(file_path, "wb") as f:
                        f.write(thumbnail_data)
                    return file_name
                
                file_name = await self.hass.async_add_executor_job(_write_thumbnail)
                
                result = {
                    "service": "get_thumbnail",
                    "success": True,
                    "content_id": content_id,
                    "thumbnail_url": f"/local/frame_art/{file_name}",
                    "size": len(thumbnail_data),
                }
            else:
                result = {
                    "service": "get_thumbnail",
                    "success": False,
                    "content_id": content_id,
                    "error": "No thumbnail data received",
                }
        except Exception as ex:
            result = {
                "service": "get_thumbnail",
                "success": False,
                "content_id": content_id,
                "error": str(ex),
            }
        self._last_service_result = result
        self.async_write_ha_state()
        return result


class SmartThingsIlluminanceSensor(SensorEntity):
    """Samsung Frame TV light sensor via SmartThings."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "illuminance"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session,  # aiohttp session
        device_id: str,
        device_name: str,
        parent_device_id: str,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._session = session
        self._device_id = device_id
        self._device_name = device_name
        self._parent_device_id = parent_device_id
        self._attr_unique_id = f"{device_id}_illuminance"
        self._attr_native_value = None

    async def _get_st_client(self):
        """Get SmartThings client with current token from config entry."""
        from pysmartthings import SmartThings
        
        api_key = await async_get_samsungtv_api_key(self.hass, self._entry)
        
        if not api_key:
            config = self.hass.data[DOMAIN][self._entry.entry_id][DATA_CFG]
            api_key = config.get(CONF_API_KEY)
            if not api_key:
                oauth_token = config.get(CONF_OAUTH_TOKEN)
                if oauth_token and isinstance(oauth_token, dict):
                    api_key = oauth_token.get("access_token")
        
        if not api_key:
            return None
            
        st_client = SmartThings(session=self._session)
        st_client.authenticate(api_key)
        return st_client

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info - link to parent TV device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._parent_device_id)},
            name=self._device_name,
            manufacturer="Samsung",
            model="Frame TV Light Sensor",
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Light Level"

    async def async_update(self) -> None:
        """Update the sensor value from SmartThings."""
        try:
            st_client = await self._get_st_client()
            if not st_client:
                return
                
            components = await st_client.get_device_status(self._device_id)
            
            if (
                "main" in components
                and Capability.ILLUMINANCE_MEASUREMENT in components["main"]
                and Attribute.ILLUMINANCE in components["main"][Capability.ILLUMINANCE_MEASUREMENT]
            ):
                illuminance_status = components["main"][Capability.ILLUMINANCE_MEASUREMENT][Attribute.ILLUMINANCE]
                self._attr_native_value = illuminance_status.value
                _LOGGER.debug(
                    "Updated illuminance sensor for %s: %s lux",
                    self._device_name,
                    self._attr_native_value,
                )
            else:
                _LOGGER.debug("Illuminance data not available for %s", self._device_name)
        except Exception as ex:
            _LOGGER.warning("Error updating illuminance sensor: %s", ex)


class SmartThingsBrightnessIntensitySensor(SensorEntity):
    """Samsung Frame TV brightness intensity sensor via SmartThings."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "brightness_intensity"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session,  # aiohttp session
        device_id: str,
        device_name: str,
        parent_device_id: str,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._entry = entry
        self._session = session
        self._device_id = device_id
        self._device_name = device_name
        self._parent_device_id = parent_device_id
        self._attr_unique_id = f"{device_id}_brightness_intensity"
        self._attr_native_value = None

    async def _get_st_client(self):
        """Get SmartThings client with current token from config entry."""
        from pysmartthings import SmartThings
        
        api_key = await async_get_samsungtv_api_key(self.hass, self._entry)
        
        if not api_key:
            config = self.hass.data[DOMAIN][self._entry.entry_id][DATA_CFG]
            api_key = config.get(CONF_API_KEY)
            if not api_key:
                oauth_token = config.get(CONF_OAUTH_TOKEN)
                if oauth_token and isinstance(oauth_token, dict):
                    api_key = oauth_token.get("access_token")
        
        if not api_key:
            return None
            
        st_client = SmartThings(session=self._session)
        st_client.authenticate(api_key)
        return st_client

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info - link to parent TV device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._parent_device_id)},
            name=self._device_name,
            manufacturer="Samsung",
            model="Frame TV Light Sensor",
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Brightness Intensity"

    async def async_update(self) -> None:
        """Update the sensor value from SmartThings."""
        try:
            st_client = await self._get_st_client()
            if not st_client:
                return
                
            components = await st_client.get_device_status(self._device_id)
            
            if (
                "main" in components
                and Capability.RELATIVE_BRIGHTNESS in components["main"]
                and Attribute.BRIGHTNESS_INTENSITY in components["main"][Capability.RELATIVE_BRIGHTNESS]
            ):
                brightness_status = components["main"][Capability.RELATIVE_BRIGHTNESS][Attribute.BRIGHTNESS_INTENSITY]
                self._attr_native_value = brightness_status.value
                _LOGGER.debug(
                    "Updated brightness intensity sensor for %s: %s",
                    self._device_name,
                    self._attr_native_value,
                )
            else:
                _LOGGER.debug("Brightness intensity data not available for %s", self._device_name)
        except Exception as ex:
            _LOGGER.warning("Error updating brightness intensity sensor: %s", ex)
