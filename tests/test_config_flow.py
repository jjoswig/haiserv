"""Unit tests for IServConfigFlow.

Tests verify:
- Successful flow with valid credentials creates entry
- Invalid credentials shows authentication error
- Unreachable URL shows connection error
- Empty fields show validation error
- Invalid URL format shows URL error

Requirements: 8.2
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- Ensure config_entries.ConfigFlow is a proper base class ---
# The conftest mocks homeassistant.* as MagicMock, but IServConfigFlow
# needs a real class to inherit from. We set that up before importing.


class _FakeConfigFlow:
    """Minimal stub for config_entries.ConfigFlow."""

    VERSION = 1

    def __init__(self):
        self.hass = MagicMock()

    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)
        if domain is not None:
            cls.DOMAIN = domain

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}


# Inject our stub as the ConfigFlow class before config_flow.py is imported
_config_entries_mod = sys.modules["homeassistant.config_entries"]
_config_entries_mod.ConfigFlow = _FakeConfigFlow

# Also set FlowResult to a simple dict alias
_data_entry_flow_mod = sys.modules["homeassistant.data_entry_flow"]
_data_entry_flow_mod.FlowResult = dict

# Provide async_get_clientsession
_aiohttp_client_mod = sys.modules["homeassistant.helpers.aiohttp_client"]
_aiohttp_client_mod.async_get_clientsession = MagicMock(return_value=MagicMock())

# Remove cached config_flow module to force re-import with our stubs
if "custom_components.iserv.config_flow" in sys.modules:
    del sys.modules["custom_components.iserv.config_flow"]

from custom_components.iserv.config_flow import IServConfigFlow  # noqa: E402
from custom_components.iserv.api import AuthenticationError, CannotConnect  # noqa: E402


# --- Fixtures ---


@pytest.fixture
def flow():
    """Create an IServConfigFlow instance with a mock hass."""
    instance = IServConfigFlow()
    instance.hass = MagicMock()
    return instance


@pytest.fixture
def valid_input():
    """Return valid user input for the config flow."""
    return {
        "url": "https://school.iserv.de",
        "username": "student",
        "password": "secret123",
    }


# --- Test: Successful flow with valid credentials ---


class TestSuccessfulFlow:
    """Tests verifying that valid credentials create a config entry."""

    @pytest.mark.asyncio
    async def test_successful_flow_creates_entry(self, flow, valid_input):
        """Valid credentials should result in a create_entry response."""
        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock()
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(valid_input)

        assert result["type"] == "create_entry"
        assert result["title"] == "iServ (student)"
        assert result["data"]["url"] == "https://school.iserv.de"
        assert result["data"]["username"] == "student"
        assert result["data"]["password"] == "secret123"

    @pytest.mark.asyncio
    async def test_successful_flow_strips_whitespace(self, flow):
        """URL and username are stripped of leading/trailing whitespace."""
        user_input = {
            "url": "  https://school.iserv.de  ",
            "username": "  student  ",
            "password": "secret123",
        }

        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock()
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(user_input)

        assert result["type"] == "create_entry"
        assert result["data"]["url"] == "https://school.iserv.de"
        assert result["data"]["username"] == "student"

    @pytest.mark.asyncio
    async def test_initial_form_shown_with_no_input(self, flow):
        """When user_input is None, the form should be shown with no errors."""
        result = await flow.async_step_user(None)

        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"] == {}


# --- Test: Invalid credentials shows authentication error ---


class TestInvalidCredentials:
    """Tests verifying that authentication errors are handled correctly."""

    @pytest.mark.asyncio
    async def test_invalid_credentials_shows_auth_error(self, flow, valid_input):
        """AuthenticationError should produce 'invalid_auth' error."""
        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock(
                side_effect=AuthenticationError("Invalid credentials")
            )
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(valid_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_auth_error_allows_reentry(self, flow, valid_input):
        """After auth error, the form is shown again for re-entry."""
        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock(
                side_effect=AuthenticationError("Bad password")
            )
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(valid_input)

        assert result["type"] == "form"
        assert result["step_id"] == "user"


# --- Test: Unreachable URL shows connection error ---


class TestConnectionError:
    """Tests verifying that connection errors are handled correctly."""

    @pytest.mark.asyncio
    async def test_cannot_connect_shows_connection_error(self, flow, valid_input):
        """CannotConnect should produce 'cannot_connect' error."""
        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock(
                side_effect=CannotConnect("Connection refused")
            )
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(valid_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_unexpected_exception_shows_connection_error(self, flow, valid_input):
        """Any unexpected exception should produce 'cannot_connect' error."""
        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock(
                side_effect=RuntimeError("Something went wrong")
            )
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(valid_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_connection_error_allows_reentry(self, flow, valid_input):
        """After connection error, the form is shown again for re-entry."""
        with patch(
            "custom_components.iserv.config_flow.async_get_clientsession"
        ) as mock_session_fn, patch(
            "custom_components.iserv.config_flow.IServClient"
        ) as MockClient:
            mock_session_fn.return_value = MagicMock()
            mock_client_instance = MagicMock()
            mock_client_instance.authenticate = AsyncMock(
                side_effect=CannotConnect("Timeout")
            )
            MockClient.return_value = mock_client_instance

            result = await flow.async_step_user(valid_input)

        assert result["type"] == "form"
        assert result["step_id"] == "user"


# --- Test: Empty fields show validation error ---


class TestEmptyFieldValidation:
    """Tests verifying that empty/missing fields produce validation errors."""

    @pytest.mark.asyncio
    async def test_empty_url_shows_missing_fields_error(self, flow):
        """Empty URL should produce 'missing_fields' error."""
        user_input = {"url": "", "username": "student", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "missing_fields"}

    @pytest.mark.asyncio
    async def test_empty_username_shows_missing_fields_error(self, flow):
        """Empty username should produce 'missing_fields' error."""
        user_input = {"url": "https://school.iserv.de", "username": "", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "missing_fields"}

    @pytest.mark.asyncio
    async def test_empty_password_shows_missing_fields_error(self, flow):
        """Empty password should produce 'missing_fields' error."""
        user_input = {"url": "https://school.iserv.de", "username": "student", "password": ""}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "missing_fields"}

    @pytest.mark.asyncio
    async def test_all_empty_shows_missing_fields_error(self, flow):
        """All empty fields should produce 'missing_fields' error."""
        user_input = {"url": "", "username": "", "password": ""}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "missing_fields"}

    @pytest.mark.asyncio
    async def test_whitespace_only_url_shows_missing_fields_error(self, flow):
        """Whitespace-only URL should produce 'missing_fields' error after stripping."""
        user_input = {"url": "   ", "username": "student", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "missing_fields"}

    @pytest.mark.asyncio
    async def test_whitespace_only_username_shows_missing_fields_error(self, flow):
        """Whitespace-only username should produce 'missing_fields' error after stripping."""
        user_input = {"url": "https://school.iserv.de", "username": "   ", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "missing_fields"}


# --- Test: Invalid URL format ---


class TestInvalidUrlFormat:
    """Tests verifying that invalid URL formats produce validation errors."""

    @pytest.mark.asyncio
    async def test_http_url_shows_invalid_url_error(self, flow):
        """HTTP (not HTTPS) URL should produce 'invalid_url' error."""
        user_input = {"url": "http://school.iserv.de", "username": "student", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_url"}

    @pytest.mark.asyncio
    async def test_no_protocol_shows_invalid_url_error(self, flow):
        """URL without protocol should produce 'invalid_url' error."""
        user_input = {"url": "school.iserv.de", "username": "student", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_url"}

    @pytest.mark.asyncio
    async def test_https_only_no_host_shows_invalid_url_error(self, flow):
        """'https://' with no host should produce 'invalid_url' error."""
        user_input = {"url": "https://", "username": "student", "password": "secret"}
        result = await flow.async_step_user(user_input)

        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_url"}
