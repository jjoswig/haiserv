"""Unit tests for the IServClient class and URL validation."""

import pytest
import pytest_asyncio
import aiohttp
from aioresponses import aioresponses

from custom_components.haiserv.api import (
    AuthenticationError,
    CannotConnect,
    IServClient,
    validate_url,
)


# --- URL Validation Tests ---


class TestValidateUrl:
    """Tests for the validate_url helper function."""

    def test_valid_https_url(self):
        """Valid https URL with proper domain."""
        assert validate_url("https://school.iserv.de") is True

    def test_valid_https_url_with_path(self):
        """Valid https URL with path."""
        assert validate_url("https://school.iserv.de/some/path") is True

    def test_valid_https_url_with_port(self):
        """Valid https URL with port."""
        assert validate_url("https://school.iserv.de:8443") is True

    def test_valid_localhost(self):
        """Localhost is valid for testing purposes."""
        assert validate_url("https://localhost") is True

    def test_valid_localhost_with_port(self):
        """Localhost with port is valid."""
        assert validate_url("https://localhost:8080") is True

    def test_invalid_http_url(self):
        """HTTP (non-secure) URLs are rejected."""
        assert validate_url("http://school.iserv.de") is False

    def test_invalid_no_scheme(self):
        """URLs without scheme are rejected."""
        assert validate_url("school.iserv.de") is False

    def test_invalid_empty_string(self):
        """Empty string is rejected."""
        assert validate_url("") is False

    def test_invalid_only_scheme(self):
        """Only the scheme without a host is rejected."""
        assert validate_url("https://") is False

    def test_invalid_no_dot_in_host(self):
        """Single-word host without dot (not localhost) is rejected."""
        assert validate_url("https://justadomain") is False

    def test_invalid_ftp_scheme(self):
        """FTP scheme is rejected."""
        assert validate_url("ftp://school.iserv.de") is False

    def test_invalid_non_string(self):
        """Non-string input returns False."""
        assert validate_url(None) is False  # type: ignore[arg-type]
        assert validate_url(123) is False  # type: ignore[arg-type]


# --- IServClient Tests ---


class TestIServClient:
    """Tests for the IServClient class."""

    BASE_URL = "https://school.iserv.de"
    LOGIN_URL = f"{BASE_URL}/iserv/auth/login"
    TIMETABLE_URL = f"{BASE_URL}/iserv/plan/show/raw"

    @pytest_asyncio.fixture
    async def session(self):
        """Create an aiohttp ClientSession for testing."""
        session = aiohttp.ClientSession()
        yield session
        await session.close()

    @pytest.fixture
    def client(self, session):
        """Create an IServClient instance for testing."""
        return IServClient(
            session=session,
            base_url=self.BASE_URL,
            username="testuser",
            password="testpass",
        )

    def test_init(self):
        """Client initializes with correct attributes."""
        # Use a mock session for sync test
        session = object()
        client = IServClient(session, self.BASE_URL, "user", "pass")  # type: ignore[arg-type]
        assert client._base_url == self.BASE_URL
        assert client._username == "user"
        assert client._password == "pass"
        assert client.is_authenticated is False

    def test_init_strips_trailing_slash(self):
        """Trailing slash is stripped from base_url."""
        session = object()
        client = IServClient(session, f"{self.BASE_URL}/", "user", "pass")  # type: ignore[arg-type]
        assert client._base_url == self.BASE_URL

    @pytest.mark.asyncio
    async def test_authenticate_success(self, client):
        """Successful authentication returns True and sets is_authenticated."""
        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=200)

            result = await client.authenticate()

            assert result is True
            assert client.is_authenticated is True

    @pytest.mark.asyncio
    async def test_authenticate_401(self, client):
        """HTTP 401 raises AuthenticationError."""
        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=401)

            with pytest.raises(AuthenticationError):
                await client.authenticate()

            assert client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_403(self, client):
        """HTTP 403 raises AuthenticationError."""
        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=403)

            with pytest.raises(AuthenticationError):
                await client.authenticate()

            assert client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_timeout(self, client):
        """Connection timeout raises CannotConnect."""
        with aioresponses() as mocked:
            import asyncio
            mocked.post(self.LOGIN_URL, exception=asyncio.TimeoutError())

            with pytest.raises(CannotConnect):
                await client.authenticate()

            assert client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_authenticate_connection_error(self, client):
        """Connection error raises CannotConnect."""
        with aioresponses() as mocked:
            mocked.post(
                self.LOGIN_URL,
                exception=aiohttp.ClientError("Connection refused"),
            )

            with pytest.raises(CannotConnect):
                await client.authenticate()

    @pytest.mark.asyncio
    async def test_fetch_timetable_success(self, client):
        """Successful timetable fetch returns response text."""
        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=200)
            mocked.get(self.TIMETABLE_URL, status=200, body="<html>timetable</html>")

            await client.authenticate()
            result = await client.fetch_timetable()

            assert result == "<html>timetable</html>"

    @pytest.mark.asyncio
    async def test_fetch_timetable_with_week(self, client):
        """Timetable fetch passes week parameter."""
        from yarl import URL

        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=200)
            # Register mock with full URL including query params
            mocked.get(
                URL(f"{self.TIMETABLE_URL}?week=42"),
                status=200,
                body="<html>week 42</html>",
            )

            await client.authenticate()
            result = await client.fetch_timetable(week=42)

            assert result == "<html>week 42</html>"

    @pytest.mark.asyncio
    async def test_fetch_timetable_session_expiry_reauth(self, client):
        """Session expiry triggers re-authentication and retry."""
        with aioresponses() as mocked:
            # Initial auth
            mocked.post(self.LOGIN_URL, status=200)
            # First fetch fails with 401 (session expired)
            mocked.get(self.TIMETABLE_URL, status=401)
            # Re-auth succeeds
            mocked.post(self.LOGIN_URL, status=200)
            # Retry fetch succeeds
            mocked.get(self.TIMETABLE_URL, status=200, body="<html>refreshed</html>")

            await client.authenticate()
            result = await client.fetch_timetable()

            assert result == "<html>refreshed</html>"

    @pytest.mark.asyncio
    async def test_fetch_timetable_reauth_failure(self, client):
        """If re-authentication fails after session expiry, raise AuthenticationError."""
        with aioresponses() as mocked:
            # Initial auth
            mocked.post(self.LOGIN_URL, status=200)
            # First fetch fails with 401
            mocked.get(self.TIMETABLE_URL, status=401)
            # Re-auth also fails
            mocked.post(self.LOGIN_URL, status=401)

            await client.authenticate()

            with pytest.raises(AuthenticationError):
                await client.fetch_timetable()

    @pytest.mark.asyncio
    async def test_fetch_timetable_timeout(self, client):
        """Timetable fetch timeout raises CannotConnect."""
        import asyncio

        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=200)
            mocked.get(self.TIMETABLE_URL, exception=asyncio.TimeoutError())

            await client.authenticate()

            with pytest.raises(CannotConnect):
                await client.fetch_timetable()

    @pytest.mark.asyncio
    async def test_is_authenticated_initially_false(self, session):
        """New client is not authenticated."""
        client = IServClient(session, self.BASE_URL, "user", "pass")
        assert client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_is_authenticated_after_login(self, client):
        """Client is authenticated after successful login."""
        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=200)
            await client.authenticate()
            assert client.is_authenticated is True

    @pytest.mark.asyncio
    async def test_is_authenticated_reset_on_401(self, client):
        """is_authenticated resets to False on 401 during fetch."""
        with aioresponses() as mocked:
            mocked.post(self.LOGIN_URL, status=200)
            await client.authenticate()
            assert client.is_authenticated is True

            # Now session expires on fetch, and re-auth also fails
            mocked.get(self.TIMETABLE_URL, status=401)
            mocked.post(self.LOGIN_URL, status=401)

            with pytest.raises(AuthenticationError):
                await client.fetch_timetable()

            assert client.is_authenticated is False
