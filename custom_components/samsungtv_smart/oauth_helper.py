"""OAuth2 token management for Samsung TV Smart.

This module handles OAuth2 token retrieval, validation, and refresh
for SmartThings API authentication.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_API_KEY,
    CONF_AUTH_METHOD,
    CONF_OAUTH_TOKEN,
    CONF_ST_ENTRY_UNIQUE_ID,
    AUTH_METHOD_OAUTH,
    AUTH_METHOD_PAT,
    AUTH_METHOD_ST_ENTRY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Token refresh buffer (refresh 5 minutes before expiration)
TOKEN_REFRESH_BUFFER = timedelta(minutes=5)


class OAuth2TokenManager:
    """Manage OAuth2 tokens with automatic refresh."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the token manager."""
        self.hass = hass
        self.entry = entry
        self._token: dict | None = entry.data.get(CONF_OAUTH_TOKEN)

    @property
    def access_token(self) -> str | None:
        """Return the current access token."""
        if not self._token:
            return None
        return self._token.get("access_token")

    @property
    def expires_at(self) -> datetime | None:
        """Return the token expiration time."""
        if not self._token or "expires_at" not in self._token:
            return None
        return datetime.fromtimestamp(self._token["expires_at"])

    def is_token_valid(self) -> bool:
        """Check if the token is valid and not expired."""
        if not self.access_token:
            return False

        expires_at = self.expires_at
        if not expires_at:
            # No expiration info, assume valid
            return True

        # Check if token expires within buffer time
        return datetime.now() < (expires_at - TOKEN_REFRESH_BUFFER)

    async def async_get_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary."""
        if self.is_token_valid():
            return self.access_token

        _LOGGER.debug("OAuth token expired or expiring soon, refreshing...")

        try:
            # Get the OAuth implementation
            implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
                self.hass, self.entry
            )

            if not implementation:
                _LOGGER.error("OAuth implementation not found for refresh")
                return None

            # Refresh the token
            new_token = await implementation.async_refresh_token(self._token)

            # Update stored token
            self._token = new_token
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={
                    **self.entry.data,
                    CONF_OAUTH_TOKEN: new_token,
                    CONF_API_KEY: new_token["access_token"],
                },
            )

            _LOGGER.info("OAuth token refreshed successfully")
            return new_token["access_token"]

        except Exception as ex:
            _LOGGER.error("Failed to refresh OAuth token: %s", ex)
            # Trigger reauth flow
            self.entry.async_start_reauth(self.hass)
            return None


async def async_get_api_key(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Get the API key/access token based on authentication method.
    
    This function abstracts the different auth methods and returns
    a valid access token for SmartThings API calls.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry for the integration
        
    Returns:
        Access token string if available, None otherwise
    """
    auth_method = entry.data.get(CONF_AUTH_METHOD, AUTH_METHOD_PAT)

    if auth_method == AUTH_METHOD_OAUTH:
        # OAuth2 - use token manager with auto-refresh
        token_manager = OAuth2TokenManager(hass, entry)
        return await token_manager.async_get_access_token()

    elif auth_method == AUTH_METHOD_ST_ENTRY:
        # SmartThings integration - get token from linked entry
        st_entry_id = entry.data.get(CONF_ST_ENTRY_UNIQUE_ID)
        if not st_entry_id:
            _LOGGER.warning("ST entry unique ID not found")
            return entry.data.get(CONF_API_KEY)

        # Find the SmartThings entry
        for st_entry in hass.config_entries.async_entries("smartthings"):
            if st_entry.unique_id == st_entry_id:
                token = st_entry.data.get("token", {})
                return token.get("access_token")

        _LOGGER.warning("SmartThings entry %s not found", st_entry_id)
        return entry.data.get(CONF_API_KEY)

    else:
        # PAT - direct token from config
        return entry.data.get(CONF_API_KEY)


async def async_validate_token(hass: HomeAssistant, token: str) -> bool:
    """Validate a SmartThings API token.
    
    Args:
        hass: Home Assistant instance
        token: The access token to validate
        
    Returns:
        True if token is valid, False otherwise
    """
    if not token:
        return False

    session = async_get_clientsession(hass)
    try:
        async with session.get(
            "https://api.smartthings.com/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        ) as resp:
            return resp.status == 200
    except Exception as ex:
        _LOGGER.warning("Token validation failed: %s", ex)
        return False
