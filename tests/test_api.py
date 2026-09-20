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
        """Create a client pinned to the legacy endpoint under test."""
        client = IServClient(
            session=session,
            base_url=self.BASE_URL,
            username="testuser",
            password="testpass",
        )
        client._timetable_path = client.TIMETABLE_PATH
        return client

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


# --- Time-table module (issue #2) ---


class TestTimeTableModule:
    """Tests for the newer /iserv/time-table/data module and child selection.

    Covers: 403 handling on data paths (not reported as session expiry),
    fallback order between the classic and the new data endpoint, and the
    child/childId parameters sent for parent accounts.
    """

    BASE_URL = "https://school.iserv.de"
    LOGIN_URL = f"{BASE_URL}/iserv/auth/login"

    @pytest_asyncio.fixture
    async def session(self):
        """Create an aiohttp ClientSession for testing."""
        session = aiohttp.ClientSession()
        yield session
        await session.close()

    @pytest.fixture
    def client(self, session):
        """Create a client pinned to the classic data endpoint."""
        client = IServClient(
            session=session,
            base_url=self.BASE_URL,
            username="testuser",
            password="testpass",
        )
        client._timetable_path = client.TIMETABLE_DATA_PATH
        return client

    @pytest.mark.asyncio
    async def test_child_id_stored_on_client(self, session):
        """child_id is stored on the client for parent accounts."""
        client = IServClient(
            session, self.BASE_URL, "user", "pass", child_id="child-123"
        )
        assert client._child_id == "child-123"

    @pytest.mark.asyncio
    async def test_403_on_data_path_is_not_auth_error(self, client):
        """403 on the data path is treated as endpoint unavailable.

        A permissions/parameter problem must not be reported as an expired
        session: no AuthenticationError and no spurious re-authentication.
        All endpoints fail here, so the final result is CannotConnect and
        the session stays authenticated.
        """
        import re

        with aioresponses() as mocked:
            mocked.post(re.compile(r".*/iserv/auth/login"), status=200)
            mocked.get(re.compile(r".*current-timetable/.*"), status=403)
            mocked.get(re.compile(r".*plan/show/raw.*"), status=403)
            mocked.get(re.compile(r".*time-table/data.*"), status=403)
            mocked.get(re.compile(r".*timetable/data.*"), status=403)

            await client.authenticate()
            with pytest.raises(CannotConnect):
                await client.fetch_timetable()

            assert client.is_authenticated is True

    @pytest.mark.asyncio
    async def test_403_on_old_data_path_falls_back_to_new(self, session):
        """Old data path 403 (permission/child issue) falls back to the new module."""
        import re

        body = (
            '[{"day":"Monday","start_time":"08:00","end_time":"08:45",'
            '"subject":"Math","room":"A1"}]'
        )
        client = IServClient(session, self.BASE_URL, "user", "pass")
        client._timetable_path = client.TIMETABLE_DATA_PATH

        with aioresponses() as mocked:
            mocked.get(re.compile(r".*current-timetable/.*"), status=403)
            mocked.get(re.compile(r".*plan/show/raw.*"), status=403)
            mocked.get(
                re.compile(r".*time-table/data.*"), status=200, body=body
            )
            mocked.get(re.compile(r".*timetable/data.*"), status=403)

            result = await client.fetch_timetable(week=42)

            assert "Math" in result
            assert client._timetable_path == client.TIME_TABLE_DATA_PATH

    @pytest.mark.asyncio
    async def test_new_module_used_without_child_when_legacy_fails(self, session):
        """New module is discovered when the classic endpoints are unavailable."""
        import re

        body = (
            '[{"day":"Tuesday","start_time":"09:00","end_time":"09:45",'
            '"subject":"Physics","room":"B2"}]'
        )
        client = IServClient(session, self.BASE_URL, "user", "pass")

        with aioresponses() as mocked:
            mocked.get(re.compile(r".*current-timetable/.*"), status=404)
            mocked.get(re.compile(r".*plan/show/raw.*"), status=404)
            mocked.get(
                re.compile(r".*time-table/data.*"), status=200, body=body
            )
            mocked.get(re.compile(r".*timetable/data.*"), status=404)

            result = await client.fetch_timetable(week=42)

            assert "Physics" in result
            assert client._timetable_path == client.TIME_TABLE_DATA_PATH

    @pytest.mark.asyncio
    async def test_child_and_childid_params_sent(self, session):
        """Parent accounts send child in the filter and a childId query param."""
        import json
        import re
        from yarl import URL

        client = IServClient(
            session, self.BASE_URL, "user", "pass", child_id="child-123"
        )
        client._timetable_path = client.TIME_TABLE_DATA_PATH

        with aioresponses() as mocked:
            mocked.get(re.compile(r".*time-table/data.*"), status=200, body="[]")

            await client.fetch_timetable(week=42)

        new_module_urls = [
            url
            for (method, url) in mocked.requests
            if "/iserv/time-table/data" in str(url)
        ]
        assert new_module_urls, "expected a request to the time-table module"
        url = URL(new_module_urls[0])
        assert url.query.get("childId") == "child-123"
        filter_payload = json.loads(url.query["filter"])
        assert filter_payload["child"] == "child-123"
        assert filter_payload["classes"] == []
        assert filter_payload["teachers"] == []
        assert filter_payload["rooms"] == []

    @pytest.mark.asyncio
    async def test_no_child_params_without_child_id(self, session):
        """Without child_id, no child/childId parameters are sent."""
        import json
        import re
        from yarl import URL

        client = IServClient(session, self.BASE_URL, "user", "pass")
        client._timetable_path = client.TIME_TABLE_DATA_PATH

        with aioresponses() as mocked:
            mocked.get(re.compile(r".*time-table/data.*"), status=200, body="[]")

            await client.fetch_timetable(week=42)

        new_module_urls = [
            url
            for (method, url) in mocked.requests
            if "/iserv/time-table/data" in str(url)
        ]
        url = URL(new_module_urls[0])
        assert "childId" not in url.query
        filter_payload = json.loads(url.query["filter"])
        assert "child" not in filter_payload

    @pytest.mark.asyncio
    async def test_falls_back_to_old_data_when_new_unavailable(self, session):
        """Classic data endpoint is used when the new module is unavailable."""
        import re

        body = (
            '[{"day":"Wednesday","start_time":"10:00",')
        body += '"end_time":"10:45","subject":"English","room":"C3"}]'
        client = IServClient(session, self.BASE_URL, "user", "pass")

        with aioresponses() as mocked:
            mocked.get(re.compile(r".*current-timetable/.*"), status=403)
            mocked.get(re.compile(r".*plan/show/raw.*"), status=403)
            mocked.get(re.compile(r".*time-table/data.*"), status=404)
            mocked.get(
                re.compile(r".*timetable/data.*"), status=200, body=body
            )

            result = await client.fetch_timetable(week=42)

            assert "English" in result
            assert client._timetable_path == client.TIMETABLE_DATA_PATH

    @pytest.mark.asyncio
    async def test_all_data_endpoints_unavailable_raises_cannot_connect(
        self, session
    ):
        """CannotConnect (not AuthenticationError) when no data endpoint works."""
        import re

        client = IServClient(session, self.BASE_URL, "user", "pass")

        with aioresponses() as mocked:
            mocked.get(re.compile(r".*current-timetable/.*"), status=404)
            mocked.get(re.compile(r".*plan/show/raw.*"), status=404)
            mocked.get(re.compile(r".*time-table/data.*"), status=404)
            mocked.get(re.compile(r".*timetable/data.*"), status=404)

            with pytest.raises(CannotConnect):
                await client.fetch_timetable(week=42)
