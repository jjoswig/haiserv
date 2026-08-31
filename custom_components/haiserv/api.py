"""iServ API client for authentication and timetable fetching."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable
from html import unescape
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp

from .const import CONNECTION_TIMEOUT, REQUEST_TIMEOUT


class AuthenticationError(Exception):
    """Raised when iServ rejects credentials (HTTP 401/403)."""


class CannotConnect(Exception):
    """Raised when connection to iServ fails (timeout or refused)."""


def validate_url(url: str) -> bool:
    """Validate that a URL starts with https:// and has a valid host component.

    Args:
        url: The URL string to validate.

    Returns:
        True if the URL starts with "https://" and has a non-empty host with at
        least one dot (indicating a valid domain), False otherwise.
    """
    if not isinstance(url, str):
        return False

    if not url.startswith("https://"):
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    # Must have a non-empty hostname
    if not parsed.hostname:
        return False

    # Host must contain at least one dot (e.g., "school.iserv.de")
    # or be "localhost" for testing purposes
    host = parsed.hostname
    if "." not in host and host != "localhost":
        return False

    return True


class IServClient:
    """Async HTTP client for iServ communication."""

    APP_LOGIN_PATH = "/iserv/app/login"
    LOGIN_PATH = "/iserv/auth/login"
    TIMETABLE_PATH = "/iserv/plan/show/raw"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
        debug_callback: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the iServ client.

        Args:
            session: An aiohttp ClientSession for making HTTP requests.
            base_url: The base URL of the iServ server (e.g., "https://school.iserv.de").
            username: The iServ username.
            password: The iServ password.
        """
        self._session = session
        self._base_url = _normalize_base_url(base_url)
        self._username = username
        self._password = password
        self._debug_callback = debug_callback
        self._authenticated = False

    @property
    def is_authenticated(self) -> bool:
        """Whether the client holds a valid session."""
        return self._authenticated

    async def authenticate(self) -> bool:
        """Login to iServ via form POST, storing session cookies.

        Returns:
            True on successful authentication.

        Raises:
            AuthenticationError: If iServ rejects credentials (HTTP 401/403).
            CannotConnect: If the connection times out or is refused.
        """
        payload = {
            "_username": self._username,
            "_password": self._password,
        }

        try:
            login_url = await self._discover_login_url()
        except (AuthenticationError, CannotConnect):
            # Older installations and lightweight test doubles accept
            # credentials directly at auth/login.
            login_url = f"{self._base_url}{self.LOGIN_PATH}"

        return await self._authenticate_at(login_url, payload)

    async def _discover_login_url(self) -> str:
        """Discover the login URL containing the app-specific target path."""
        url = f"{self._base_url}{self.APP_LOGIN_PATH}"
        for _ in range(3):
            response_url, response_body = await self._get_page(url)
            if _is_login_page(response_body):
                return response_url
            refresh_url = _meta_refresh_url(response_body, response_url)
            if refresh_url is None:
                raise AuthenticationError(
                    "iServ did not provide an application login form"
                )
            url = refresh_url

        raise AuthenticationError("Too many iServ authentication redirects")

    async def _get_page(self, url: str) -> tuple[str, str]:
        """Fetch one authentication page and return its final URL and body."""
        try:
            timeout = aiohttp.ClientTimeout(total=CONNECTION_TIMEOUT)
            async with self._session.get(
                url,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                self._debug_response("GET", response)
                await _raise_for_status(response)
                return str(response.url), await _read_response_text(response)
        except asyncio.TimeoutError as err:
            raise CannotConnect(
                f"Connection to {self._base_url} timed out"
            ) from err
        except aiohttp.ClientError as err:
            raise CannotConnect(
                f"Connection error with {self._base_url}: {err}"
            ) from err

    async def _authenticate_at(
        self, url: str, payload: dict[str, str]
    ) -> bool:
        """Authenticate against one iServ login endpoint."""
        try:
            timeout = aiohttp.ClientTimeout(total=CONNECTION_TIMEOUT)
            async with self._session.post(
                url,
                data=payload,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                self._debug_response("POST", response)
                if response.status in (401, 403):
                    self._authenticated = False
                    raise AuthenticationError(
                        f"Authentication failed with status {response.status}"
                    )
                await _raise_for_status(response)
                response_url = str(response.url)
                response_body = await _read_response_text(response)
                if _is_login_page(response_body):
                    self._authenticated = False
                    raise AuthenticationError("iServ returned the login page")

                for _ in range(3):
                    refresh_url = _meta_refresh_url(response_body, response_url)
                    if refresh_url is None:
                        break
                    response_url, response_body = await self._get_page(refresh_url)
                    if _is_login_page(response_body):
                        self._authenticated = False
                        raise AuthenticationError("iServ returned the login page")

                if "/iserv/auth/auth" in response_url:
                    self._authenticated = False
                    raise AuthenticationError("iServ authentication did not complete")

                self._authenticated = True
                return True

        except AuthenticationError:
            raise
        except asyncio.TimeoutError as err:
            self._authenticated = False
            raise CannotConnect(
                f"Connection to {self._base_url} timed out"
            ) from err
        except aiohttp.ClientConnectorError as err:
            self._authenticated = False
            raise CannotConnect(
                f"Cannot connect to {self._base_url}: {err}"
            ) from err
        except aiohttp.ClientError as err:
            self._authenticated = False
            raise CannotConnect(
                f"Connection error with {self._base_url}: {err}"
            ) from err

    async def fetch_timetable(self, week: int | None = None) -> str:
        """Fetch raw timetable data for a given calendar week.

        If the session has expired (HTTP 401/403 on fetch), re-authenticates
        once and retries. On second failure, raises the exception.

        Args:
            week: The calendar week number to fetch. If None, fetches current week.

        Returns:
            Raw response text containing the timetable data.

        Raises:
            AuthenticationError: If re-authentication fails after session expiry.
            CannotConnect: If the connection times out or is refused.
        """
        url = f"{self._base_url}{self.TIMETABLE_PATH}"
        params: dict[str, str] = {}
        if week is not None:
            params["week"] = str(week)

        try:
            return await self._do_fetch_timetable(url, params)
        except AuthenticationError:
            # Session expired — re-authenticate once and retry
            await self.authenticate()
            return await self._do_fetch_timetable(url, params)

    async def _do_fetch_timetable(self, url: str, params: dict[str, str]) -> str:
        """Perform the actual timetable fetch request.

        Args:
            url: The full URL to fetch.
            params: Query parameters for the request.

        Returns:
            Raw response text.

        Raises:
            AuthenticationError: If the server responds with 401/403.
            CannotConnect: If the connection times out or fails.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with self._session.get(
                url,
                params=params,
                timeout=timeout,
            ) as response:
                self._debug_response("GET", response)
                if response.status in (401, 403):
                    self._authenticated = False
                    raise AuthenticationError(
                        "Session expired or authentication required"
                    )
                if _is_auth_redirect(response):
                    self._authenticated = False
                    raise AuthenticationError("iServ redirected to authentication")

                await _raise_for_status(response)
                response_body = await _read_response_text(response)
                if _is_login_page(response_body):
                    self._authenticated = False
                    raise AuthenticationError("iServ returned the login page")

                return response_body

        except AuthenticationError:
            raise
        except asyncio.TimeoutError as err:
            raise CannotConnect(
                f"Request to {url} timed out after {REQUEST_TIMEOUT}s"
            ) from err
        except aiohttp.ClientConnectorError as err:
            raise CannotConnect(
                f"Cannot connect to {url}: {err}"
            ) from err
        except aiohttp.ClientError as err:
            raise CannotConnect(
                f"Request error for {url}: {err}"
            ) from err


    def _debug_response(self, method: str, response: aiohttp.ClientResponse) -> None:
        """Report safe request diagnostics without credentials or query values."""
        if self._debug_callback is None:
            return

        history = ", ".join(
            f"{item.status} {_safe_url(item.url)}" for item in response.history
        ) or "none"
        cookies = sorted(cookie.key for cookie in self._session.cookie_jar)
        self._debug_callback(
            f"{method} {response.status} {_safe_url(response.url)}; "
            f"redirects={history}; content_type={response.headers.get('Content-Type', 'unknown')}; "
            f"cookies={cookies or 'none'}"
        )


def _normalize_base_url(base_url: str) -> str:
    """Normalize an iServ base URL, including URLs ending in ``/iserv``."""
    parsed = urlparse(base_url.rstrip("/"))
    path = parsed.path.rstrip("/")
    if path == "/iserv":
        path = ""
    return urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")


async def _raise_for_status(response: aiohttp.ClientResponse) -> None:
    """Raise for HTTP errors, tolerating asynchronous test doubles."""
    result = response.raise_for_status()
    if inspect.isawaitable(result):
        await result


async def _read_response_text(response: aiohttp.ClientResponse) -> str:
    """Read response text, tolerating lightweight test doubles."""
    response_text = response.text()
    if inspect.isawaitable(response_text):
        response_text = await response_text
    return response_text if isinstance(response_text, str) else ""


def _meta_refresh_url(response_body: str, base_url: str) -> str | None:
    """Extract and resolve an HTML meta-refresh URL."""
    match = re.search(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^;]+;\s*url=([^"\']+)["\']',
        response_body,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return urljoin(base_url, unescape(match.group(1)).strip(" '\""))


def _safe_url(url: object) -> str:
    """Return a URL without query parameters or fragments."""
    parsed = urlparse(str(url))
    return urlunparse(parsed._replace(query="", fragment=""))


def _is_auth_redirect(response: aiohttp.ClientResponse) -> bool:
    """Return whether a response redirects to an iServ auth endpoint."""
    urls = [response.url, *(item.url for item in response.history)]
    return any("/iserv/auth/auth" in str(url) for url in urls)


def _is_login_page(response_body: str) -> bool:
    """Return whether a response body is the iServ login form."""
    body = response_body.casefold()
    markers = (
        'name="_username"',
        'name="_password"',
        'id="loginbutton"',
        "login-form",
    )
    return sum(marker in body for marker in markers) >= 2
