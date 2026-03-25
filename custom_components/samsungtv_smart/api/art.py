"""
Samsung Frame TV Art Mode API wrapper for Home Assistant.

Based on xchwarze/samsung-tv-ws-api art-updates branch
https://github.com/xchwarze/samsung-tv-ws-api/tree/art-updates

Copyright (C) 2019 DSR! <xchwarze@gmail.com>
Copyright (C) 2021 Matthew Garrett <mjg59@srcf.ucam.org>
Copyright (C) 2024 Nick Waterton <n.waterton@outlook.com>

Adapted for Home Assistant integration using aiohttp

SPDX-License-Identifier: LGPL-3.0
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import json
import logging
import os
import random
import ssl
import time
from typing import Any
import uuid

import aiohttp

_LOGGER = logging.getLogger(__name__)

ART_ENDPOINT = "com.samsung.art-app"
D2D_SERVICE_MESSAGE_EVENT = "d2d_service_message"
MS_CHANNEL_CONNECT_EVENT = "ms.channel.connect"
MS_CHANNEL_READY_EVENT = "ms.channel.ready"


def _get_ssl_context() -> ssl.SSLContext:
    """Get SSL context for secure connections without blocking calls."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _serialize_string(string: str | bytes) -> str:
    """Serialize string to base64."""
    if isinstance(string, str):
        string = string.encode()
    return base64.b64encode(string).decode("utf-8")


class SamsungTVAsyncArt:
    """Async Samsung Frame TV Art Mode API class using aiohttp."""

    def __init__(
        self,
        host: str,
        port: int = 8001,
        token: str | None = None,
        session: aiohttp.ClientSession | None = None,
        timeout: int = 5,
        name: str = "HomeAssistant",
    ) -> None:
        """Initialize the Art API."""
        self._host = host
        self._port = port
        self._token = token
        self._external_session = session
        self._session: aiohttp.ClientSession | None = None
        self._timeout = timeout
        self._name = name
        
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._art_uuid: str = str(uuid.uuid4())
        
        # State
        self.art_mode: bool | None = None
        
        # Async handling
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._recv_task: asyncio.Task | None = None
        self._connected = False
        
        # Connection failure tracking for exponential backoff (v6.3.5)
        self._connection_failures = 0
        self._max_connection_failures = 3  # Start backoff after 3 failures
        self._backoff_until: float | None = None
        self._last_connection_attempt: float = 0
        
        # Connection lock to prevent concurrent connection attempts (v6.3.5)
        self._connection_lock = asyncio.Lock()

    def _get_uuid(self) -> str:
        """Generate a new UUID for art requests."""
        self._art_uuid = str(uuid.uuid4())
        return self._art_uuid

    @property
    def _ws_url(self) -> str:
        """Get the WebSocket URL for the art API."""
        scheme = "wss" if self._port == 8002 else "ws"
        name = _serialize_string(self._name)
        token_part = f"&token={self._token}" if self._token and self._port == 8002 else ""
        return f"{scheme}://{self._host}:{self._port}/api/v2/channels/{ART_ENDPOINT}?name={name}{token_part}"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._external_session and not self._external_session.closed:
            return self._external_session
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def open(self) -> bool:
        """Open WebSocket connection and start listening."""
        # Acquire lock to prevent concurrent connection attempts (v6.3.5)
        async with self._connection_lock:
            if self._ws and not self._ws.closed:
                return True

            # Check if in backoff period (anti-saturation protection)
            if self._backoff_until is not None:
                if time.time() < self._backoff_until:
                    remaining = int(self._backoff_until - time.time())
                    _LOGGER.debug(
                        "Art API: In backoff period, skipping connection attempt (%ds remaining)",
                        remaining
                    )
                    return False
                else:
                    _LOGGER.info("Art API: Backoff period expired, resuming connection attempts")
                    self._backoff_until = None
                    self._connection_failures = 0

            # Rate limit connection attempts (min 5 seconds between attempts)
            time_since_last = time.time() - self._last_connection_attempt
            if time_since_last < 5:
                _LOGGER.debug(
                    "Art API: Too soon since last attempt (%.1fs ago), waiting",
                    time_since_last
                )
                return False
            
            self._last_connection_attempt = time.time()

            try:
                session = await self._get_session()
                ssl_context = _get_ssl_context() if self._port == 8002 else None
                
                _LOGGER.debug("Art API: Connecting to %s", self._ws_url)
                
                self._ws = await session.ws_connect(
                    self._ws_url,
                    timeout=aiohttp.ClientTimeout(total=self._timeout),
                    ssl=ssl_context,
                )
                
                # Wait for connection events
                # Frame TV 2024 sends "connect" but may never send "ready"
                connected = False
                for _ in range(3):  # Max 3 events (reduced from 5)
                    try:
                        msg = await asyncio.wait_for(self._ws.receive(), timeout=2)  # Reduced timeout
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            response = json.loads(msg.data)
                            event = response.get("event", "")
                            _LOGGER.debug("Art API: Connection event: %s", event)
                            
                            if event == MS_CHANNEL_READY_EVENT:
                                # Perfect! Got ready event
                                connected = True
                                break
                            elif event == MS_CHANNEL_CONNECT_EVENT:
                                # Frame TV 2024 often only sends connect, accept it!
                                _LOGGER.debug("Art API: Accepting connect event (Frame TV 2024 compatible)")
                                connected = True
                                break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                    except asyncio.TimeoutError:
                        break
                
                if not connected:
                    _LOGGER.warning("Art API: Did not receive connect/ready event, connection may not be stable")
                    await self.close()
                    
                    # Track connection failure
                    self._connection_failures += 1
                    _LOGGER.warning(
                        "Art API: Connection failure %d/%d",
                        self._connection_failures,
                        self._max_connection_failures
                    )
                    
                    # Activate backoff if too many failures
                    if self._connection_failures >= self._max_connection_failures:
                        # Exponential backoff: 2, 5, 10, 20, 30 minutes (capped)
                        backoff_minutes = min(2 ** (self._connection_failures - self._max_connection_failures + 1), 30)
                        self._backoff_until = time.time() + (backoff_minutes * 60)
                        _LOGGER.warning(
                            "Art API: Too many connection failures (%d), entering %d minute backoff period",
                            self._connection_failures,
                            backoff_minutes
                        )
                    
                    return False
                
                # Connection successful! Reset failure counter
                if self._connection_failures > 0:
                    _LOGGER.info("Art API: Connection successful, resetting failure counter")
                    self._connection_failures = 0
                
                self._connected = True
                
                # Start the receive loop
                self._recv_task = asyncio.create_task(self._receive_loop())
                
                _LOGGER.debug("Art API: Connected and listening")
                return True
                
            except Exception as ex:
                _LOGGER.warning("Art API: Connection failed: %s", ex)
                await self.close()
                
                # Track connection failure
                self._connection_failures += 1
                _LOGGER.warning(
                    "Art API: Connection failure %d/%d",
                    self._connection_failures,
                    self._max_connection_failures
                )
                
                # Activate backoff if too many failures
                if self._connection_failures >= self._max_connection_failures:
                    backoff_minutes = min(2 ** (self._connection_failures - self._max_connection_failures + 1), 30)
                    self._backoff_until = time.time() + (backoff_minutes * 60)
                    _LOGGER.warning(
                        "Art API: Too many connection failures (%d), entering %d minute backoff period",
                        self._connection_failures,
                        backoff_minutes
                    )
                
                return False

    async def close(self) -> None:
        """Close the connection."""
        self._connected = False
        
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        
        # Cancel all pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
        
        # Close own session if created
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None

    async def _receive_loop(self) -> None:
        """Background task to receive and process WebSocket messages."""
        if not self._ws:
            return
            
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        response = json.loads(msg.data)
                        event = response.get("event", "")
                        await self._process_event(event, response)
                    except json.JSONDecodeError:
                        _LOGGER.debug("Art API: Failed to decode message")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.debug("Art API: WebSocket error")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.debug("Art API: WebSocket closed")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            _LOGGER.debug("Art API: Receive loop error: %s", ex)
        finally:
            self._connected = False

    async def _process_event(self, event: str, response: dict) -> None:
        """Process incoming WebSocket events."""
        _LOGGER.debug("Art API: Received event '%s'", event)
        
        if event != D2D_SERVICE_MESSAGE_EVENT:
            return
            
        try:
            data_str = response.get("data", "{}")
            data = json.loads(data_str) if isinstance(data_str, str) else data_str
            _LOGGER.debug("Art API: Event data: %s", data)
        except json.JSONDecodeError:
            return
            
        sub_event = data.get("event", "")
        
        # Update art mode status from events
        if "artmode_status" in sub_event:
            self.art_mode = data.get("value") == "on"
        elif sub_event == "art_mode_changed":
            self.art_mode = data.get("status") == "on"
        elif sub_event == "go_to_standby":
            self.art_mode = False
        
        # Check for error
        if sub_event == "error":
            error_code = data.get("error_code", "unknown")
            _LOGGER.debug("Art API: Error event: %s", error_code)
        
        # Resolve pending requests
        request_id = data.get("request_id", data.get("id"))
        _LOGGER.debug(
            "Art API: Looking for request_id='%s' or sub_event='%s' in pending: %s",
            request_id,
            sub_event,
            list(self._pending_requests.keys()),
        )
        
        # Try to match by request_id first
        if request_id and request_id in self._pending_requests:
            future = self._pending_requests.get(request_id)
            if future and not future.done():
                _LOGGER.debug("Art API: Matched by request_id '%s'", request_id)
                future.set_result(data)
                return
        
        # Try to match by sub_event
        if sub_event and sub_event in self._pending_requests:
            future = self._pending_requests.get(sub_event)
            if future and not future.done():
                _LOGGER.debug("Art API: Matched by sub_event '%s'", sub_event)
                future.set_result(data)

    async def _wait_for_response(
        self,
        request_key: str,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """Wait for a response matching the request key."""
        if request_key not in self._pending_requests:
            self._pending_requests[request_key] = asyncio.get_event_loop().create_future()
        
        try:
            result = await asyncio.wait_for(
                self._pending_requests[request_key],
                timeout=timeout,
            )
            return result
        except asyncio.TimeoutError:
            _LOGGER.debug("Art API: Timeout waiting for '%s'", request_key)
            return None
        except asyncio.CancelledError:
            return None
        finally:
            self._pending_requests.pop(request_key, None)

    async def _send_art_request(
        self,
        request_data: dict[str, Any],
        wait_for_event: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any] | None:
        """Send an art API request and wait for response."""
        # Ensure connected - also reconnect if WebSocket was closed by TV
        if not self._connected or not self._ws or self._ws.closed:
            if self._ws and self._ws.closed:
                _LOGGER.debug("Art API: WebSocket was closed, reconnecting...")
                self._connected = False  # Reset flag to allow reconnection
            if not await self.open():
                _LOGGER.debug("Art API: Failed to connect/reconnect")
                return None
        
        # Double-check connection after open()
        if not self._ws or self._ws.closed:
            _LOGGER.debug("Art API: WebSocket still not connected after open()")
            return None
        
        # Set up request IDs (both old and new API style)
        if not request_data.get("id"):
            request_data["id"] = self._get_uuid()
        request_data["request_id"] = request_data["id"]
        
        request_key = wait_for_event or request_data["id"]
        
        # Create future before sending
        self._pending_requests[request_key] = asyncio.get_event_loop().create_future()
        
        # Build command
        command = {
            "method": "ms.channel.emit",
            "params": {
                "event": "art_app_request",
                "to": "host",
                "data": json.dumps(request_data),
            },
        }
        
        try:
            await self._ws.send_json(command)
            _LOGGER.debug("Art API: Sent request '%s'", request_data.get("request", "unknown"))
            
            # Wait for response
            return await self._wait_for_response(request_key, timeout)
            
        except Exception as ex:
            _LOGGER.debug("Art API: Error sending request: %s", ex)
            self._pending_requests.pop(request_key, None)
            # Mark as disconnected to force reconnection on next request
            self._connected = False
            return None

    # ==================== REST API Methods ====================

    async def supported(self) -> bool:
        """Check if the TV supports Frame TV art mode."""
        try:
            session = await self._get_session()
            url = f"http://{self._host}:8001/api/v2/"
            async with asyncio.timeout(5):
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        device = data.get("device", {})
                        return device.get("FrameTVSupport") == "true"
        except Exception as ex:
            _LOGGER.debug("Art API: Error checking support: %s", ex)
        return False

    async def on(self) -> bool:
        """Check if the TV is on."""
        try:
            session = await self._get_session()
            url = f"http://{self._host}:8001/api/v2/"
            async with asyncio.timeout(5):
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        device = data.get("device", {})
                        return device.get("PowerState", "off") == "on"
        except Exception:
            pass
        return False

    async def is_artmode(self) -> bool:
        """Check if currently in art mode."""
        return await self.on() and self.art_mode is True

    # ==================== Art API Methods ====================

    async def get_api_version(self) -> str | None:
        """Get the art API version."""
        data = await self._send_art_request({"request": "get_api_version"})
        if not data:
            data = await self._send_art_request({"request": "api_version"})
        return data.get("version") if data else None

    async def available(self, category: str | None = None) -> list:
        """Get list of available artwork.
        
        category: 'MY-C0002' for my pictures, 'MY-C0004' for favourites, 'MY-C0008' for store
        """
        data = await self._send_art_request(
            {"request": "get_content_list", "category": category},
            timeout=15,
        )
        if not data:
            return []
        
        content_list = data.get("content_list", "[]")
        if isinstance(content_list, str):
            try:
                content_list = json.loads(content_list)
            except json.JSONDecodeError:
                return []
        
        if category:
            return [v for v in content_list if v.get("category_id") == category]
        return content_list

    async def get_current(self) -> dict[str, Any] | None:
        """Get information about the currently displayed artwork."""
        return await self._send_art_request({"request": "get_current_artwork"})

    async def get_thumbnail_list(self, content_id_list: list[dict]) -> dict[str, bytes]:
        """Get thumbnails for a list of content IDs (multi-download)."""
        _LOGGER.debug("Art API: Requesting get_thumbnail_list for %s", content_id_list)

        data = await self._send_art_request(
            {
                "request": "get_thumbnail_list",
                "content_id_list": content_id_list,
                "conn_info": {
                    "d2d_mode": "socket",
                    "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                    "id": self._get_uuid(),
                },
            },
            timeout=15,
        )

        if not data:
            _LOGGER.debug("Art API: No response for get_thumbnail_list")
            return {}

        # Si la TV répond directement par un event d'erreur
        if data.get("event") == "error":
            _LOGGER.debug(
                "Art API: get_thumbnail_list returned error: %s",
                data.get("error_code"),
            )
            return {}

        try:
            conn_info = data.get("conn_info", "{}")
            _LOGGER.debug("Art API: get_thumbnail_list conn_info raw: %s", conn_info)

            if isinstance(conn_info, str):
                conn_info = json.loads(conn_info)

            ip = conn_info.get("ip")
            port = conn_info.get("port")
            secured = conn_info.get("secured", False)

            if not ip or not port:
                _LOGGER.debug(
                    "Art API: Invalid conn_info for thumbnail_list - ip=%s, port=%s",
                    ip,
                    port,
                )
                return {}

            ssl_context = _get_ssl_context() if secured else None
            _LOGGER.debug(
                "Art API: Opening thumbnail socket %s:%s (ssl=%s)",
                ip,
                port,
                ssl_context is not None,
            )

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, int(port), ssl=ssl_context),
                timeout=10,
            )
            _LOGGER.debug("Art API: Connected to thumbnail socket")

            try:
                thumbnail_data_dict: dict[str, bytes] = {}
                total_num_thumbnails = 1
                current_thumb = -1

                while current_thumb + 1 < total_num_thumbnails:
                    _LOGGER.debug("Art API: Reading thumbnail header.")
                    header_len = int.from_bytes(
                        await reader.readexactly(4), "big"
                    )
                    _LOGGER.debug("Art API: Header length: %d", header_len)

                    header_raw = await reader.readexactly(header_len)
                    header = json.loads(header_raw)
                    _LOGGER.debug("Art API: Thumbnail header: %s", header)

                    thumbnail_data_len = int(header["fileLength"])
                    current_thumb = int(header["num"])
                    total_num_thumbnails = int(header["total"])
                    filename = "{}.{}".format(
                        header.get("fileID", header.get("content_id", "unknown")),
                        header.get("fileType", "jpg"),
                    )

                    _LOGGER.debug(
                        "Art API: Reading %d bytes for thumbnail %d/%d (%s)",
                        thumbnail_data_len,
                        current_thumb + 1,
                        total_num_thumbnails,
                        filename,
                    )
                    thumbnail_data = await reader.readexactly(thumbnail_data_len)
                    thumbnail_data_dict[filename] = thumbnail_data
                    _LOGGER.debug(
                        "Art API: Got thumbnail %s (%d bytes)",
                        filename,
                        len(thumbnail_data),
                    )

                return thumbnail_data_dict

            finally:
                writer.close()
                await writer.wait_closed()
                _LOGGER.debug("Art API: Thumbnail socket closed")

        except asyncio.TimeoutError:
            _LOGGER.debug("Art API: Timeout connecting to thumbnail socket")
            return {}
        except asyncio.IncompleteReadError as ex:
            _LOGGER.debug(
                "Art API: Incomplete read in get_thumbnail_list "
                "(%d bytes read, %d expected)",
                len(ex.partial or b""),
                ex.expected,
            )
            return {}
        except Exception as ex:
            _LOGGER.debug(
                "Art API: Error getting thumbnail_list: %s (type: %s)",
                ex,
                type(ex).__name__,
            )
            import traceback

            _LOGGER.debug("Art API: Traceback: %s", traceback.format_exc())
            return {}


    async def get_thumbnail(self, content_id: str) -> bytes | None:
        """Get thumbnail for a specific piece of art."""
        _LOGGER.debug("Art API: Getting thumbnail for %s", content_id)
        
        # For SAM-S (Art Store) images, warm up the TV by calling get_content_list first
        # This seems to help the TV prepare the thumbnail data
        is_artstore = content_id.startswith("SAM-")
        if is_artstore:
            _LOGGER.debug("Art API: Art Store image detected, warming up with get_content_list")
            await self._send_art_request({
                "request": "get_content_list",
                "category": "MY-C0004",  # Favorites category
            }, timeout=5)
            # Small delay to let TV prepare
            await asyncio.sleep(0.1)
        
        # Try get_thumbnail_list first for better compatibility with 2024 TVs
        _LOGGER.debug("Art API: Trying get_thumbnail_list first for %s", content_id)
        result = await self._get_thumbnail_via_list(content_id)
        if result:
            return result
        
        _LOGGER.debug("Art API: get_thumbnail_list failed, trying simple get_thumbnail")
        
        # Send the request and get connection info
        data = await self._send_art_request({
            "request": "get_thumbnail",
            "content_id": content_id,
            "conn_info": {
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                "id": self._get_uuid(),
            },
        }, timeout=10)
        
        if not data:
            _LOGGER.debug("Art API: No response for get_thumbnail either")
            return None
        
        # Check for error
        if data.get("event") == "error":
            _LOGGER.debug("Art API: get_thumbnail error: %s", data.get("error_code"))
            return None
        
        try:
            conn_info = data.get("conn_info", "{}")
            _LOGGER.debug("Art API: get_thumbnail conn_info: %s", conn_info)
            
            if isinstance(conn_info, str):
                conn_info = json.loads(conn_info)
            
            ip = conn_info.get("ip")
            port = conn_info.get("port")
            
            if not ip or not port:
                _LOGGER.debug("Art API: Invalid conn_info for thumbnail")
                return None
            
            _LOGGER.debug("Art API: Connecting to %s:%s for thumbnail", ip, port)
            
            # Connect without SSL - reference implementation doesn't use SSL for thumbnail socket
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, int(port)),
                timeout=10,
            )
            
            try:
                _LOGGER.debug("Art API: Reading thumbnail header...")
                header_len = int.from_bytes(await reader.readexactly(4), "big")
                _LOGGER.debug("Art API: Header length: %d", header_len)
                header = json.loads(await reader.readexactly(header_len))
                _LOGGER.debug("Art API: Thumbnail header: %s", header)
                
                thumbnail_len = int(header["fileLength"])
                _LOGGER.debug("Art API: Reading %d bytes of thumbnail data...", thumbnail_len)
                thumbnail_data = await reader.readexactly(thumbnail_len)
                _LOGGER.debug("Art API: Got thumbnail (%d bytes)", len(thumbnail_data))
                
                return thumbnail_data
            finally:
                writer.close()
                await writer.wait_closed()
                
        except asyncio.TimeoutError:
            _LOGGER.debug("Art API: Timeout getting thumbnail")
            return None
        except Exception as ex:
            _LOGGER.debug("Art API: Error getting thumbnail: %s (type: %s)", ex, type(ex).__name__)
            return None

    async def _get_thumbnail_via_list(
        self,
        content_id: str,
        retry_count: int = 0,
    ) -> bytes | None:
        """Get thumbnail for a single content via get_thumbnail_list."""
        _LOGGER.debug(
            "Art API: Trying get_thumbnail_list for %s (attempt %d)",
            content_id,
            retry_count + 1,
        )

        data = await self._send_art_request(
            {
                "request": "get_thumbnail_list",
                "content_id_list": [{"content_id": content_id}],
                "conn_info": {
                    "d2d_mode": "socket",
                    "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                    "id": self._get_uuid(),
                },
            },
            timeout=15,
        )

        if not data:
            _LOGGER.debug("Art API: No response for get_thumbnail_list (single)")
            return None

        # Sur certains modèles, la TV répond directement "event: error" (code -1)
        if data.get("event") == "error":
            _LOGGER.debug(
                "Art API: get_thumbnail_list error for %s: %s",
                content_id,
                data.get("error_code"),
            )
            return None

        try:
            conn_info = data.get("conn_info", "{}")
            _LOGGER.debug(
                "Art API: get_thumbnail_list (single) conn_info: %s", conn_info
            )

            if isinstance(conn_info, str):
                conn_info = json.loads(conn_info)

            ip = conn_info.get("ip")
            port = conn_info.get("port")
            secured = conn_info.get("secured", False)

            if not ip or not port:
                _LOGGER.debug("Art API: Invalid conn_info for %s", content_id)
                return None

            ssl_context = _get_ssl_context() if secured else None
            _LOGGER.debug(
                "Art API: Opening connection for %s to %s:%s (ssl=%s)",
                content_id,
                ip,
                port,
                ssl_context is not None,
            )

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, int(port), ssl=ssl_context),
                    timeout=10,
                )
                _LOGGER.debug("Art API: Connected successfully for %s", content_id)
            except ConnectionResetError as ex:
                _LOGGER.debug("Art API: Connection reset for %s: %s", content_id, ex)
                # Retry uniquement pour le Art Store (SAM-), comme discuté
                if content_id.startswith("SAM-") and retry_count < 2:
                    _LOGGER.debug(
                        "Art API: Art Store image %s, retrying after delay", content_id
                    )
                    await asyncio.sleep(0.5 * (retry_count + 1))
                    return await self._get_thumbnail_via_list(
                        content_id, retry_count + 1
                    )
                return None

            try:
                _LOGGER.debug("Art API: Reading thumbnail header for %s", content_id)
                header_len = int.from_bytes(await reader.readexactly(4), "big")
                _LOGGER.debug(
                    "Art API: Header length for %s: %d", content_id, header_len
                )

                header_raw = await reader.readexactly(header_len)
                header = json.loads(header_raw)
                _LOGGER.debug(
                    "Art API: Thumbnail header for %s: %s", content_id, header
                )

                thumbnail_len = int(header["fileLength"])
                _LOGGER.debug(
                    "Art API: Reading %d bytes of thumbnail data for %s",
                    thumbnail_len,
                    content_id,
                )
                thumbnail_data = await reader.readexactly(thumbnail_len)
                _LOGGER.debug(
                    "Art API: Got thumbnail for %s (%d bytes)",
                    content_id,
                    len(thumbnail_data),
                )

                return thumbnail_data

            except asyncio.IncompleteReadError as ex:
                _LOGGER.debug(
                    "Art API: Incomplete read for %s: %d bytes read on %d expected",
                    content_id,
                    len(ex.partial or b""),
                    ex.expected,
                )
                # même logique : petit retry pour les images SAM- si besoin
                if content_id.startswith("SAM-") and retry_count < 2:
                    _LOGGER.debug(
                        "Art API: Art Store image %s, retrying after incomplete read",
                        content_id,
                    )
                    await asyncio.sleep(0.5 * (retry_count + 1))
                    return await self._get_thumbnail_via_list(
                        content_id, retry_count + 1
                    )
                return None

            finally:
                writer.close()
                await writer.wait_closed()
                _LOGGER.debug(
                    "Art API: Thumbnail connection closed for %s", content_id
                )

        except Exception as ex:
            _LOGGER.debug(
                "Art API: Error in _get_thumbnail_via_list for %s: %s (type: %s)",
                content_id,
                ex,
                type(ex).__name__,
            )
            return None


    async def select_image(
        self,
        content_id: str,
        category: str | None = None,
        show: bool = True,
    ) -> bool:
        """Select and display a piece of art."""
        data = await self._send_art_request({
            "request": "select_image",
            "category_id": category,
            "content_id": content_id,
            "show": show,
        })
        return data is not None

    async def get_artmode(self) -> str | None:
        """Get current art mode status."""
        data = await self._send_art_request({"request": "get_artmode_status"})
        if data:
            value = data.get("value")
            self.art_mode = value == "on"
            return value
        return None

    async def set_artmode(self, mode: str | bool) -> bool:
        """Set art mode on or off."""
        if isinstance(mode, bool):
            mode = "on" if mode else "off"
        data = await self._send_art_request({
            "request": "set_artmode_status",
            "value": mode,
        })
        return data is not None

    async def set_favourite(self, content_id: str, status: str = "on") -> bool:
        """Add or remove artwork from favorites."""
        data = await self._send_art_request(
            {
                "request": "change_favorite",
                "content_id": content_id,
                "status": status,
            },
            wait_for_event="favorite_changed",
        )
        return data is not None

    async def get_photo_filter_list(self) -> list[str]:
        """Get list of available photo filters."""
        data = await self._send_art_request({"request": "get_photo_filter_list"})
        if data:
            filter_list = data.get("filter_list", "[]")
            if isinstance(filter_list, str):
                try:
                    return json.loads(filter_list)
                except json.JSONDecodeError:
                    pass
        return []

    async def set_photo_filter(self, content_id: str, filter_id: str) -> bool:
        """Apply a photo filter to artwork."""
        data = await self._send_art_request({
            "request": "set_photo_filter",
            "content_id": content_id,
            "filter_id": filter_id,
        })
        return data is not None

    async def get_matte_list(self, include_color: bool = False) -> list | tuple:
        """Get list of available matte types."""
        data = await self._send_art_request({"request": "get_matte_list"})
        if data:
            matte_types = data.get("matte_type_list", "[]")
            if isinstance(matte_types, str):
                try:
                    matte_types = json.loads(matte_types)
                except json.JSONDecodeError:
                    matte_types = []
            
            if include_color:
                matte_colors = data.get("matte_color_list", "[]")
                if isinstance(matte_colors, str):
                    try:
                        matte_colors = json.loads(matte_colors)
                    except json.JSONDecodeError:
                        matte_colors = []
                return matte_types, matte_colors
            return matte_types
        return ([], []) if include_color else []

    async def change_matte(
        self,
        content_id: str,
        matte_id: str | None = None,
        portrait_matte: str | None = None,
    ) -> bool:
        """Set the matte for a piece of artwork."""
        request = {
            "request": "change_matte",
            "content_id": content_id,
            "matte_id": matte_id or "none",
        }
        if portrait_matte:
            request["portrait_matte_id"] = portrait_matte
        data = await self._send_art_request(request)
        return data is not None

    async def get_artmode_settings(self, setting: str = "") -> dict | list | None:
        """Get art mode settings."""
        data = await self._send_art_request({"request": "get_artmode_settings"})
        if data:
            settings_data = data.get("data", "[]")
            if isinstance(settings_data, str):
                try:
                    settings_data = json.loads(settings_data)
                except json.JSONDecodeError:
                    return None
            if setting:
                return next((item for item in settings_data if item.get("item") == setting), None)
            return settings_data
        return None

    async def get_brightness(self) -> dict | None:
        """Get current art mode brightness."""
        data = await self._send_art_request({"request": "get_brightness"})
        if not data:
            data = await self.get_artmode_settings("brightness")
        return data

    async def set_brightness(self, value: int) -> bool:
        """Set art mode brightness."""
        data = await self._send_art_request({
            "request": "set_brightness",
            "value": value,
        })
        return data is not None

    async def get_color_temperature(self) -> dict | None:
        """Get current art mode color temperature."""
        data = await self._send_art_request({"request": "get_color_temperature"})
        if not data:
            data = await self.get_artmode_settings("color_temperature")
        return data

    async def set_color_temperature(self, value: int) -> bool:
        """Set art mode color temperature."""
        data = await self._send_art_request({
            "request": "set_color_temperature",
            "value": value,
        })
        return data is not None

    async def get_auto_rotation_status(self) -> dict | None:
        """Get auto rotation settings."""
        return await self._send_art_request({"request": "get_auto_rotation_status"})

    async def set_auto_rotation_status(
        self,
        duration: int = 0,
        shuffle: bool = True,
        category: int = 2,
    ) -> bool:
        """Configure auto rotation."""
        data = await self._send_art_request({
            "request": "set_auto_rotation_status",
            "value": str(duration) if duration > 0 else "off",
            "category_id": f"MY-C000{category}",
            "type": "shuffleslideshow" if shuffle else "slideshow",
        })
        return data is not None

    async def get_slideshow_status(self) -> dict | None:
        """Get slideshow settings."""
        return await self._send_art_request({"request": "get_slideshow_status"})

    async def set_slideshow_status(
        self,
        duration: int = 0,
        shuffle: bool = True,
        category: int = 2,
    ) -> bool:
        """Configure slideshow settings."""
        data = await self._send_art_request({
            "request": "set_slideshow_status",
            "value": str(duration) if duration > 0 else "off",
            "category_id": f"MY-C000{category}",
            "type": "shuffleslideshow" if shuffle else "slideshow",
        })
        return data is not None

    async def upload(
        self,
        file: str | bytes,
        matte: str = "shadowbox_polar",
        portrait_matte: str = "shadowbox_polar",
        file_type: str = "png",
        date: str | None = None,
        timeout: int = 30,
        hass = None,
    ) -> str | None:
        """Upload a new image to the TV."""
        _LOGGER.debug("Art API: Starting upload, file type: %s", type(file))
        
        if isinstance(file, str):
            _LOGGER.debug("Art API: Loading file from path: %s", file)
            file_name, file_extension = os.path.splitext(file)
            file_type = file_extension[1:].lower()
            try:
                # Use executor to avoid blocking the event loop
                def read_file(path):
                    with open(path, "rb") as f:
                        return f.read()
                
                if hass:
                    file = await hass.async_add_executor_job(read_file, file)
                else:
                    # Fallback for non-HA usage
                    file = await asyncio.get_event_loop().run_in_executor(None, read_file, file)
                    
                _LOGGER.debug("Art API: File loaded, size: %d bytes", len(file))
            except Exception as ex:
                _LOGGER.error("Art API: Failed to read file: %s", ex)
                return None
        
        file_size = len(file)
        if file_type == "jpeg":
            file_type = "jpg"
        
        _LOGGER.debug("Art API: Upload - file_size=%d, file_type=%s, matte=%s", 
                     file_size, file_type, matte)
        
        if date is None:
            date = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        
        request_id = self._get_uuid()
        _LOGGER.debug("Art API: Sending send_image request, request_id=%s", request_id)
        
        data = await self._send_art_request({
            "request": "send_image",
            "file_type": file_type,
            "request_id": request_id,
            "id": request_id,
            "conn_info": {
                "d2d_mode": "socket",
                "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
                "id": request_id,
            },
            "image_date": date,
            "matte_id": matte or "none",
            "portrait_matte_id": portrait_matte or "none",
            "file_size": file_size,
        }, timeout=15)
        
        _LOGGER.debug("Art API: send_image response: %s", data)
        
        if not data:
            _LOGGER.error("Art API: No response from send_image request")
            return None
        
        if data.get("event") == "error":
            _LOGGER.error("Art API: send_image error: %s", data.get("error_code"))
            return None
        
        try:
            conn_info = data.get("conn_info", "{}")
            _LOGGER.debug("Art API: Upload conn_info (raw): %s", conn_info)
            
            if isinstance(conn_info, str):
                conn_info = json.loads(conn_info)
            
            _LOGGER.debug("Art API: Upload conn_info (parsed): %s", conn_info)
            
            if not conn_info.get("ip") or not conn_info.get("port"):
                _LOGGER.error("Art API: Invalid conn_info - missing ip or port")
                return None
            
            header = json.dumps({
                "num": 0,
                "total": 1,
                "fileLength": file_size,
                "fileName": "dummy",
                "fileType": file_type,
                "secKey": conn_info["key"],
                "version": "0.0.1",
            })
            
            _LOGGER.debug("Art API: Connecting to %s:%s for upload (secured=%s)", 
                         conn_info["ip"], conn_info["port"], conn_info.get("secured"))
            
            ssl_context = _get_ssl_context() if conn_info.get("secured") else None
            
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        conn_info["ip"],
                        int(conn_info["port"]),
                        ssl=ssl_context,
                    ),
                    timeout=10,
                )
                _LOGGER.debug("Art API: Connected for upload")
            except asyncio.TimeoutError:
                _LOGGER.error("Art API: Timeout connecting for upload")
                return None
            except Exception as ex:
                _LOGGER.error("Art API: Failed to connect for upload: %s", ex)
                return None
            
            try:
                _LOGGER.debug("Art API: Sending header (%d bytes)", len(header))
                writer.write(len(header).to_bytes(4, "big"))
                writer.write(header.encode("ascii"))
                
                _LOGGER.debug("Art API: Sending file data (%d bytes)", file_size)
                writer.write(file)
                await writer.drain()
                _LOGGER.debug("Art API: Data sent successfully")
            finally:
                writer.close()
                await writer.wait_closed()
            
            # Wait for image_added event
            _LOGGER.debug("Art API: Waiting for image_added event (timeout=%ds)", timeout)
            result = await self._wait_for_response("image_added", timeout=timeout)
            
            if result:
                content_id = result.get("content_id")
                _LOGGER.info("Art API: Upload successful, content_id=%s", content_id)
                return content_id
            else:
                _LOGGER.error("Art API: No image_added event received")
                return None
            
        except Exception as ex:
            _LOGGER.error("Art API: Error uploading image: %s", ex)
            import traceback
            _LOGGER.debug("Art API: Upload traceback: %s", traceback.format_exc())
            return None

    async def delete(self, content_id: str) -> bool:
        """Delete an uploaded piece of art."""
        return await self.delete_list([content_id])

    async def delete_list(self, content_ids: list[str]) -> bool:
        """Delete multiple uploaded pieces of art."""
        content_id_list = [{"content_id": cid} for cid in content_ids]
        await self._send_art_request({
            "request": "delete_image_list",
            "content_id_list": content_id_list,
        })
        return True

    # ==================== Context Manager ====================

    async def __aenter__(self) -> "SamsungTVAsyncArt":
        """Async context manager entry."""
        await self.open()
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()
