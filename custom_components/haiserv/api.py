"""iServ API client for authentication and timetable fetching."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp

from .const import CONNECTION_TIMEOUT, REQUEST_TIMEOUT


class AuthenticationError(Exception):
    """Raised when iServ rejects credentials (HTTP 401/403)."""


class CannotConnect(Exception):
    """Raised when connection to iServ fails (timeout or refused)."""


class _EndpointUnavailable(Exception):
    """Raised when an iServ generation does not provide an endpoint."""


class TimetableResult(str):
    """Parser-compatible timetable text with the complete server JSON attached."""

    raw_response: str
    timetable_data: object | None

    def __new__(
        cls, normalized_response: str, raw_response: str | None = None
    ) -> TimetableResult:
        result = super().__new__(cls, normalized_response)
        result.raw_response = (
            raw_response if raw_response is not None else normalized_response
        )
        try:
            result.timetable_data = json.loads(result.raw_response)
        except (json.JSONDecodeError, TypeError):
            result.timetable_data = None
        return result


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
    CURRENT_TIMETABLE_PATH = "/iserv/dieschulapp/api/1.0/current-timetable/"
    TIMETABLE_PATH = "/iserv/plan/show/raw"
    TIMETABLE_DATA_PATH = "/iserv/timetable/data"

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
        self._timetable_path: str | None = None
        self._course_ids: tuple[str, ...] = ()
        self._course_filter_required = False

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

    async def fetch_timetable(self, week: int | None = None) -> TimetableResult:
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
        try:
            return await self._fetch_timetable_once(week)
        except AuthenticationError:
            # Session expired — re-authenticate once and retry
            await self.authenticate()
            return await self._fetch_timetable_once(week)

    async def _fetch_timetable_once(self, week: int | None) -> TimetableResult:
        """Fetch from the detected timetable API generation."""
        if self._timetable_path == self.CURRENT_TIMETABLE_PATH:
            try:
                return await self._fetch_current_timetable(week)
            except _EndpointUnavailable:
                self._timetable_path = None

        if self._timetable_path == self.TIMETABLE_DATA_PATH:
            try:
                return await self._fetch_timetable_data(week)
            except _EndpointUnavailable:
                self._timetable_path = None

        if self._timetable_path is None:
            try:
                body = await self._fetch_current_timetable(week)
                self._timetable_path = self.CURRENT_TIMETABLE_PATH
                return body
            except _EndpointUnavailable:
                pass

        legacy_params = {"week": str(week)} if week is not None else {}
        try:
            body = await self._do_fetch_timetable(
                f"{self._base_url}{self.TIMETABLE_PATH}",
                legacy_params,
                unavailable_statuses=(403, 404),
            )
            self._timetable_path = self.TIMETABLE_PATH
            return TimetableResult(body)
        except _EndpointUnavailable:
            body = await self._fetch_timetable_data(week)
            self._timetable_path = self.TIMETABLE_DATA_PATH
            return body

    async def _fetch_current_timetable(self, week: int | None) -> TimetableResult:
        """Fetch DieSchulApp timetable data and convert it to legacy lessons."""
        monday, _ = _week_dates(week)
        params = {
            "date": monday.isoformat(),
            "week": "true",
            "substitutions": "true",
        }
        if self._course_filter_required and self._course_ids:
            params["filterBy"] = _course_filter(self._course_ids)
        body = await self._do_fetch_timetable(
            f"{self._base_url}{self.CURRENT_TIMETABLE_PATH}",
            params,
            unavailable_statuses=(403, 404),
        )
        normalized, course_ids, has_entries, recognized = (
            _normalize_current_timetable(body)
        )
        if not recognized:
            raise _EndpointUnavailable
        if course_ids:
            self._course_ids = course_ids

        # Some installations expose the pupil and main course without a
        # filter, but only populate entries when the course is requested.
        if not has_entries and self._course_ids and "filterBy" not in params:
            self._course_filter_required = True
            filtered_params = dict(params)
            filtered_params["filterBy"] = _course_filter(self._course_ids)
            filtered_body = await self._do_fetch_timetable(
                f"{self._base_url}{self.CURRENT_TIMETABLE_PATH}",
                filtered_params,
                unavailable_statuses=(403, 404),
            )
            normalized, filtered_ids, _, recognized = _normalize_current_timetable(
                filtered_body
            )
            if not recognized:
                raise _EndpointUnavailable
            if filtered_ids:
                self._course_ids = filtered_ids
        source_body = (
            filtered_body
            if self._course_filter_required and "filterBy" not in params
            else body
        )
        return TimetableResult(normalized, source_body)

    async def _fetch_timetable_data(self, week: int | None) -> TimetableResult:
        """Fetch and normalize the current iServ timetable JSON response."""
        start, end = _week_dates(week)
        timetable_filter = {
            "startDate": start.strftime("%d.%m.%Y"),
            "endDate": end.strftime("%d.%m.%Y"),
            "changesUntil": None,
            "classes": ["%"],
            "teachers": ["%"],
            "rooms": ["%"],
        }
        body = await self._do_fetch_timetable(
            f"{self._base_url}{self.TIMETABLE_DATA_PATH}",
            {"filter": json.dumps(timetable_filter, separators=(",", ":"))},
            unavailable_statuses=(404,),
        )
        return TimetableResult(_normalize_timetable_data(body), body)

    async def _do_fetch_timetable(
        self,
        url: str,
        params: dict[str, str],
        unavailable_statuses: tuple[int, ...] = (),
    ) -> str:
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
                if response.status in unavailable_statuses:
                    raise _EndpointUnavailable
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

        except (AuthenticationError, _EndpointUnavailable):
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


    # ------------------------------------------------------------------
    # Elternbrief (parent letter) methods
    # ------------------------------------------------------------------

    PARENTLETTER_LIST_PATH = "/iserv/parentletter/parent/index"
    PARENTLETTER_SHOW_PATH = "/iserv/parentletter/parent/show/{letter_uuid}/{child_uuid}"
    PARENTLETTER_MARK_READ_PATH = "/iserv/parentletter/parent/mark-as-read/{letter_uuid}/{child_uuid}"

    async def fetch_parentletter_list(self) -> str:
        """Fetch the Elternbrief list-view HTML page.

        Re-authenticates once on session expiry (HTTP 401/403) before raising.

        Returns:
            Raw HTML of ``/iserv/parentletter/parent/index``.

        Raises:
            AuthenticationError: If authentication fails.
            CannotConnect: If the connection times out or fails.
        """
        url = f"{self._base_url}{self.PARENTLETTER_LIST_PATH}"
        try:
            return await self._do_fetch_page(url)
        except AuthenticationError:
            await self.authenticate()
            return await self._do_fetch_page(url)

    async def fetch_parentletter_detail(
        self, letter_uuid: str, child_uuid: str
    ) -> str:
        """Fetch the detail HTML page for one Elternbrief.

        Re-authenticates once on session expiry before raising.

        Args:
            letter_uuid: UUID of the letter.
            child_uuid: UUID of the child the letter is addressed to.

        Returns:
            Raw HTML of the detail page.

        Raises:
            AuthenticationError: If authentication fails.
            CannotConnect: If the connection times out or fails.
        """
        path = self.PARENTLETTER_SHOW_PATH.format(
            letter_uuid=letter_uuid, child_uuid=child_uuid
        )
        url = f"{self._base_url}{path}"
        try:
            return await self._do_fetch_page(url)
        except AuthenticationError:
            await self.authenticate()
            return await self._do_fetch_page(url)

    async def mark_parentletter_read(
        self, letter_uuid: str, child_uuid: str, csrf_token: str
    ) -> bool:
        """Submit the mark-as-read form for one Elternbrief.

        Posts the CSRF-protected form extracted from the detail page.

        Args:
            letter_uuid: UUID of the letter.
            child_uuid: UUID of the child the letter is addressed to.
            csrf_token: CSRF token from the detail-page form.

        Returns:
            True if the server accepted the submission (HTTP 2xx/3xx).

        Raises:
            AuthenticationError: If the session is expired.
            CannotConnect: If the connection times out or fails.
        """
        path = self.PARENTLETTER_MARK_READ_PATH.format(
            letter_uuid=letter_uuid, child_uuid=child_uuid
        )
        url = f"{self._base_url}{path}"
        payload = {"_token": csrf_token, "submit": "1"}
        try:
            return await self._do_post_form(url, payload)
        except AuthenticationError:
            await self.authenticate()
            return await self._do_post_form(url, payload)

    async def _do_fetch_page(self, url: str) -> str:
        """GET a page and return its text, raising on auth/connect failures.

        Args:
            url: Full URL to fetch.

        Returns:
            Response body as a string.

        Raises:
            AuthenticationError: On HTTP 401/403 or login-page redirect.
            CannotConnect: On timeout or network error.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with self._session.get(url, timeout=timeout) as response:
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
                body = await _read_response_text(response)
                if _is_login_page(body):
                    self._authenticated = False
                    raise AuthenticationError("iServ returned the login page")
                return body
        except (AuthenticationError, _EndpointUnavailable):
            raise
        except asyncio.TimeoutError as err:
            raise CannotConnect(
                f"Request to {url} timed out after {REQUEST_TIMEOUT}s"
            ) from err
        except aiohttp.ClientConnectorError as err:
            raise CannotConnect(f"Cannot connect to {url}: {err}") from err
        except aiohttp.ClientError as err:
            raise CannotConnect(f"Request error for {url}: {err}") from err

    async def _do_post_form(self, url: str, payload: dict[str, str]) -> bool:
        """POST a form payload and return True on a 2xx/3xx response.

        Args:
            url: Full URL to post to.
            payload: Form fields to submit.

        Returns:
            True on success.

        Raises:
            AuthenticationError: On HTTP 401/403.
            CannotConnect: On timeout or network error.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with self._session.post(
                url, data=payload, timeout=timeout, allow_redirects=True
            ) as response:
                self._debug_response("POST", response)
                if response.status in (401, 403):
                    self._authenticated = False
                    raise AuthenticationError(
                        "Session expired during form POST"
                    )
                if _is_auth_redirect(response):
                    self._authenticated = False
                    raise AuthenticationError("iServ redirected to authentication")
                await _raise_for_status(response)
                return True
        except AuthenticationError:
            raise
        except asyncio.TimeoutError as err:
            raise CannotConnect(
                f"Request to {url} timed out after {REQUEST_TIMEOUT}s"
            ) from err
        except aiohttp.ClientConnectorError as err:
            raise CannotConnect(f"Cannot connect to {url}: {err}") from err
        except aiohttp.ClientError as err:
            raise CannotConnect(f"Request error for {url}: {err}") from err

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


def _week_dates(week: int | None) -> tuple[date, date]:
    """Return Monday and Friday for the requested ISO week."""
    today = date.today()
    if week is None:
        monday = today - timedelta(days=today.weekday())
    else:
        candidates = []
        for year in range(today.year - 1, today.year + 2):
            try:
                candidates.append(date.fromisocalendar(year, week, 1))
            except ValueError:
                continue
        monday = min(candidates, key=lambda candidate: abs(candidate - today))
    return monday, monday + timedelta(days=4)


def _normalize_timetable_data(response_body: str) -> str:
    """Convert the current timetable envelope to the legacy lesson list."""
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, TypeError):
        return response_body

    if isinstance(payload, list):
        return response_body
    if not isinstance(payload, dict):
        return response_body

    data = payload.get("data")
    entries = data.get("timetable") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return response_body

    period_times = _period_times(payload)
    lessons = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        change = entry.get("change")
        canceled = (
            isinstance(change, dict) and "0" in change.get("change_types", [])
        )

        start_time = _first_string(entry, "start_time", "startTime", "start")
        end_time = _first_string(entry, "end_time", "endTime", "end")
        if (not start_time or not end_time) and entry.get("period") is not None:
            start_time, end_time = period_times.get(
                str(entry["period"]), (start_time, end_time)
            )

        lesson_date = _first_string(entry, "date", "day", "lessonDate")
        day = _weekday_name(lesson_date) if lesson_date else None
        subject = _first_string(entry, "subject") or ""
        room = _first_string(entry, "room") or ""
        if isinstance(change, dict):
            subject = _first_string(change, "substitutionSubject") or subject
            room = _first_string(change, "substitutionRoom") or room

        if day and start_time and end_time:
            lessons.append(
                {
                    "day": day,
                    "start_time": start_time[:5],
                    "end_time": end_time[:5],
                    "subject": subject,
                    "room": room,
                    "canceled": canceled,
                }
            )
    return json.dumps(lessons)


def _normalize_current_timetable(
    response_body: str,
) -> tuple[str, tuple[str, ...], bool, bool]:
    """Convert a DieSchulApp response to legacy lessons and main course IDs."""
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, TypeError):
        return response_body, (), False, False
    if not isinstance(payload, dict):
        return response_body, (), False, False

    students = payload.get("students")
    if not isinstance(students, list):
        return response_body, (), False, False

    course_ids: list[str] = []
    payload_entries = payload.get("entries")
    entries: list[dict[str, object]] = (
        [entry for entry in payload_entries if isinstance(entry, dict)]
        if isinstance(payload_entries, list)
        else []
    )
    for student in students:
        if not isinstance(student, dict):
            continue
        main_course = student.get("mainCourse")
        if isinstance(main_course, dict):
            course_id = main_course.get("id")
            if isinstance(course_id, int) or (
                isinstance(course_id, str) and course_id.isdecimal()
            ):
                course_ids.append(str(course_id))
        student_entries = student.get("entries")
        if isinstance(student_entries, list):
            entries.extend(
                entry for entry in student_entries if isinstance(entry, dict)
            )

    lessons = []
    for entry in entries:
        slot = entry.get("timeTableSlot")
        if not isinstance(slot, dict):
            continue
        start = _first_string(slot, "start", "startTime", "start_time")
        end = _first_string(slot, "end", "endTime", "end_time")
        weekday = entry.get("weekday")
        if (
            not start
            or not end
            or not isinstance(weekday, int)
            or not 0 <= weekday <= 4
        ):
            continue

        lessons.append(
            {
                "day": (date(2024, 1, 1) + timedelta(days=weekday)).strftime("%A"),
                "start_time": _clock_time(start),
                "end_time": _clock_time(end),
                "subject": _course_subject(entry.get("courseSubject")),
                "room": _display_value(entry.get("room")),
                "canceled": _is_canceled_substitution(entry),
            }
        )

    return (
        json.dumps(lessons),
        tuple(dict.fromkeys(course_ids)),
        bool(entries),
        True,
    )


def _course_filter(course_ids: tuple[str, ...]) -> str:
    """Build the DieSchulApp course filter from discovered numeric IDs."""
    safe_ids = (course_id for course_id in course_ids if course_id.isdecimal())
    return "courseSubject.course:in(" + ",".join(safe_ids) + ")"


def _is_canceled_substitution(entry: dict[str, object]) -> bool:
    """Return whether a substitution explicitly cancels a lesson."""
    substitution_type = entry.get("substitutionType")
    values = [substitution_type]
    if isinstance(substitution_type, dict):
        values = list(substitution_type.values())
    return any(
        isinstance(value, str)
        and value.casefold() in {"canceled", "cancelled", "entfall", "ausfall"}
        for value in values
    )


def _course_subject(value: object) -> str:
    """Return the most useful display name from a course-subject object."""
    if not isinstance(value, dict):
        return _display_value(value)
    return _display_value(value.get("subject")) or _display_value(value.get("acronym"))


def _display_value(value: object) -> str:
    """Extract a readable name or acronym from a timetable value."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "displayName", "acronym", "shortName", "label"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return ""


def _clock_time(value: str) -> str:
    """Extract HH:MM from an API time or ISO date-time string."""
    match = re.search(r"(?:T|^)(\d{2}:\d{2})(?::\d{2})?", value)
    return match.group(1) if match else value[:5]


def _period_times(payload: dict[str, object]) -> dict[str, tuple[str, str]]:
    """Collect period start/end times from known timetable metadata shapes."""
    result: dict[str, tuple[str, str]] = {}
    containers = [payload.get("meta"), payload.get("data")]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("lessonTimes", "periods", "times"):
            values = container.get(key)
            if isinstance(values, dict):
                values = [
                    dict(value, period=period)
                    for period, value in values.items()
                    if isinstance(value, dict)
                ]
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                period = value.get("period", value.get("number", value.get("id")))
                start = _first_string(value, "start_time", "startTime", "start")
                end = _first_string(value, "end_time", "endTime", "end")
                if period is not None and start and end:
                    result[str(period)] = (start, end)
    return result


def _first_string(mapping: dict[str, object], *keys: str) -> str | None:
    """Return the first non-empty string under the given keys."""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _weekday_name(value: str) -> str:
    """Convert an iServ date to the English weekday expected by the parser."""
    for date_format in ("%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], date_format).strftime("%A")
        except ValueError:
            continue
    return value


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
