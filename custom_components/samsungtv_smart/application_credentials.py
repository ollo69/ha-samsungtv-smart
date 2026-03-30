"""Application credentials platform for Samsung TV Smart."""

from json import JSONDecodeError
import logging
import time
from typing import cast

from aiohttp import BasicAuth, ClientError

from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2Implementation

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# SmartThings OAuth endpoints
AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"
TOKEN_URL = "https://auth-global.api.smartthings.com/oauth/token"


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AbstractOAuth2Implementation:
    """Return auth implementation."""
    return SmartThingsOAuth2Implementation(
        hass,
        DOMAIN,
        credential,
        authorization_server=AuthorizationServer(
            authorize_url=AUTHORIZE_URL,
            token_url=TOKEN_URL,
        ),
    )


class SmartThingsOAuth2Implementation(AuthImplementation):
    """OAuth2 implementation for SmartThings.
    
    SmartThings requires HTTP Basic Auth for the token endpoint,
    not the standard POST body credentials.
    """

    async def _token_request(self, data: dict) -> dict:
        """Make a token request with Basic Auth."""
        session = async_get_clientsession(self.hass)

        resp = await session.post(
            self.token_url,
            data=data,
            auth=BasicAuth(self.client_id, self.client_secret),
        )
        if resp.status >= 400:
            try:
                error_response = await resp.json()
            except (ClientError, JSONDecodeError):
                error_response = {}
            error_code = error_response.get("error", "unknown")
            error_description = error_response.get("error_description", "unknown error")
            _LOGGER.error(
                "Token request for %s failed (%s): %s",
                self.domain,
                error_code,
                error_description,
            )
        resp.raise_for_status()
        
        token = cast(dict, await resp.json())
        
        # Always recalculate expires_at from expires_in to ensure correctness
        # SmartThings may return an incorrect expires_at or none at all
        if "expires_in" in token:
            token["expires_at"] = time.time() + token["expires_in"]
            _LOGGER.info(
                "Token received: expires_in=%s sec (%.1f hours), expires_at=%s",
                token["expires_in"],
                token["expires_in"] / 3600,
                token["expires_at"],
            )
        
        return token
