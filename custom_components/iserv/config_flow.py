"""Config flow for iServ integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthenticationError, CannotConnect, IServClient, validate_url
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)


class IServConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle iServ integration configuration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user-initiated config. Validates URL format and credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input.get("url", "").strip()
            username = user_input.get("username", "").strip()
            password = user_input.get("password", "")

            # Validate all fields are non-empty
            if not url or not username or not password:
                errors["base"] = "missing_fields"
            # Validate URL format
            elif not validate_url(url):
                errors["base"] = "invalid_url"
            else:
                # Attempt login with IServClient
                try:
                    session = async_get_clientsession(self.hass)
                    client = IServClient(session, url, username, password)
                    await client.authenticate()
                except AuthenticationError:
                    errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected exception during iServ login")
                    errors["base"] = "cannot_connect"
                else:
                    # Authentication successful — create the config entry
                    return self.async_create_entry(
                        title=f"iServ ({username})",
                        data={
                            "url": url,
                            "username": username,
                            "password": password,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )
