"""Integration tests for end-to-end flow.

Tests verify the full lifecycle:
- Config entry creation → coordinator start → sensor entity with correct state
  and attributes
- Mocked HTTP responses for: login → fetch timetable → parse → sensor update

Requirements: 8.1
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- Ensure homeassistant module mocks are in place ---
# This must happen before any custom_components imports.
# Other test files (test_coordinator, test_sensor) set up their own mocks;
# we ensure the necessary modules exist so our imports succeed regardless
# of test execution order.

_REQUIRED_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.data_entry_flow",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
]

for _mod in _REQUIRED_HA_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Ensure the top-level homeassistant mock has submodule attributes
_ha = sys.modules["homeassistant"]
if not hasattr(_ha, "config_entries") or not hasattr(
    getattr(_ha, "config_entries", None), "ConfigFlow"
):
    _ha.config_entries = sys.modules["homeassistant.config_entries"]
if not hasattr(_ha, "data_entry_flow"):
    _ha.data_entry_flow = sys.modules["homeassistant.data_entry_flow"]


# Now import integration modules (safe after mocks)
from custom_components.haiserv.api import (  # noqa: E402
    AuthenticationError,
    CannotConnect,
    IServClient,
    validate_url,
)
from custom_components.haiserv.const import (  # noqa: E402
    DOMAIN,
    MAX_CONSECUTIVE_FAILURES,
)
from custom_components.haiserv.parser import (  # noqa: E402
    Lesson,
    format_markdown_table,
    get_next_lesson,
    parse_timetable,
    sort_lessons,
)


# --- Sample data for mocked HTTP responses ---


def _sample_timetable_json() -> str:
    """Return a JSON timetable response simulating a full week of lessons."""
    return json.dumps([
        {"day": "Monday", "start_time": "08:00", "end_time": "08:45",
         "subject": "Mathematics", "room": "A101"},
        {"day": "Monday", "start_time": "09:00", "end_time": "09:45",
         "subject": "English", "room": "B202"},
        {"day": "Tuesday", "start_time": "10:00", "end_time": "10:45",
         "subject": "Physics", "room": "C303"},
        {"day": "Wednesday", "start_time": "08:00", "end_time": "08:45",
         "subject": "History", "room": "D404"},
        {"day": "Thursday", "start_time": "11:00", "end_time": "11:45",
         "subject": "Biology", "room": ""},
        {"day": "Friday", "start_time": "14:00", "end_time": "14:45",
         "subject": "Art", "room": "E505"},
    ])


def _expected_lessons() -> list[Lesson]:
    """Return the expected parsed and sorted lessons from the sample data."""
    return [
        Lesson("Monday", "08:00", "08:45", "Mathematics", "A101"),
        Lesson("Monday", "09:00", "09:45", "English", "B202"),
        Lesson("Tuesday", "10:00", "10:45", "Physics", "C303"),
        Lesson("Wednesday", "08:00", "08:45", "History", "D404"),
        Lesson("Thursday", "11:00", "11:45", "Biology", ""),
        Lesson("Friday", "14:00", "14:45", "Art", "E505"),
    ]


def _make_mock_entry(entry_id: str, data: dict):
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = data
    return entry


def _create_coordinator(mock_client):
    """Create an IServCoordinator with a mock client.

    Ensures coordinator.data is initialized to None regardless of which
    test-file stub provides the DataUpdateCoordinator base class.
    """
    from custom_components.haiserv.coordinator import IServCoordinator

    mock_hass = MagicMock()
    coordinator = IServCoordinator(mock_hass, mock_client)
    if not hasattr(coordinator, "data"):
        coordinator.data = None
    return coordinator


def _create_sensor(coordinator, entry_id="test_entry", data=None):
    """Create a sensor entity from a coordinator."""
    from custom_components.haiserv.sensor import IServTimetableSensor

    if data is None:
        data = {
            "url": "https://school.iserv.de",
            "username": "student",
            "password": "pass",
        }
    mock_entry = _make_mock_entry(entry_id, data)
    return IServTimetableSensor(coordinator, mock_entry)


def _get_sensor_state(sensor, frozen_now: datetime) -> str:
    """Get sensor native_value with a frozen datetime."""
    with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
        mock_dt.now.return_value = frozen_now
        return sensor.native_value


def _get_sensor_attrs(sensor, frozen_now: datetime) -> dict:
    """Get sensor extra_state_attributes with a frozen datetime."""
    with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
        mock_dt.now.return_value = frozen_now
        return sensor.extra_state_attributes


def _get_update_failed():
    """Get the UpdateFailed exception class."""
    from homeassistant.helpers.update_coordinator import UpdateFailed
    return UpdateFailed


# --- Integration Tests: Config Entry → Coordinator → Sensor ---


class TestEndToEndConfigToSensor:
    """Integration tests: config entry data → coordinator → sensor entity.

    These tests simulate what happens after a config entry is created by the
    config flow: the coordinator is instantiated with credentials from the
    entry, fetches timetable data, and the sensor reflects that data.
    """

    @pytest.mark.asyncio
    async def test_full_lifecycle_login_fetch_parse_sensor(self):
        """Test full lifecycle: login → fetch timetable → parse → sensor.

        Simulates:
        1. Config entry data is used to create API client
        2. Client authenticates and fetches timetable
        3. Coordinator parses and sorts the data
        4. Sensor exposes correct state and attributes
        """
        # Simulate what async_setup_entry does: create client, coordinator
        config_data = {
            "url": "https://school.iserv.de",
            "username": "student",
            "password": "secret123",
        }

        # Validate URL (as config flow does before creating entry)
        assert validate_url(config_data["url"]) is True

        # Mock the API client (simulates successful HTTP interactions)
        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(
            return_value=_sample_timetable_json()
        )
        mock_client._base_url = config_data["url"]
        mock_client._username = config_data["username"]

        # Create coordinator and trigger initial fetch
        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()

        # Verify coordinator fetched and parsed data correctly
        assert coordinator.data is not None
        assert len(coordinator.data) == 6
        assert coordinator.consecutive_failures == 0

        # Verify lessons are sorted correctly (Mon→Fri, by time)
        expected = _expected_lessons()
        for i, lesson in enumerate(coordinator.data):
            assert lesson.day == expected[i].day
            assert lesson.start_time == expected[i].start_time
            assert lesson.end_time == expected[i].end_time
            assert lesson.subject == expected[i].subject
            assert lesson.room == expected[i].room

        # Create sensor entity (as async_setup_entry → sensor platform does)
        sensor = _create_sensor(coordinator, "test_entry_001", config_data)

        # Verify sensor identity
        assert sensor._attr_name == "iServ Timetable"
        assert sensor._attr_unique_id == "test_entry_001_timetable"

        # Verify sensor state (Monday morning before 08:00)
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday
        state = _get_sensor_state(sensor, frozen_now)
        attrs = _get_sensor_attrs(sensor, frozen_now)

        assert state == "Mathematics 08:00-08:45"

        # Verify attributes
        assert "lessons" in attrs
        assert len(attrs["lessons"]) == 6
        assert attrs["lessons"][0] == {
            "day": "Monday", "start_time": "08:00", "end_time": "08:45",
            "subject": "Mathematics", "room": "A101", "canceled": False,
        }

        # Verify timetable_table markdown
        assert "timetable_table" in attrs
        table = attrs["timetable_table"]
        assert "| Day | Time | Subject | Room | Canceled |" in table
        assert "| --- | --- | --- | --- | --- |" in table
        assert "| Monday | 08:00 - 08:45 | Mathematics | A101 | false |" in table
        assert "| Friday | 14:00 - 14:45 | Art | E505 | false |" in table

        # Verify last_updated ISO timestamp
        assert "last_updated" in attrs
        assert attrs["last_updated"] == frozen_now.isoformat()

        # Verify sensor is available
        assert sensor.available is True

    @pytest.mark.asyncio
    async def test_lifecycle_with_session_reauth(self):
        """Coordinator re-authenticates on session expiry and retries fetch."""
        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(side_effect=[
            AuthenticationError("Session expired"),
            _sample_timetable_json(),
        ])

        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()

        # Coordinator retried successfully
        assert coordinator.data is not None
        assert len(coordinator.data) == 6
        assert coordinator.consecutive_failures == 0
        mock_client.authenticate.assert_called_once()

        # Sensor shows correct data for Tuesday
        sensor = _create_sensor(coordinator, "reauth_entry")
        state = _get_sensor_state(sensor, datetime(2024, 1, 16, 9, 30))
        assert state == "Physics 10:00-10:45"

    @pytest.mark.asyncio
    async def test_lifecycle_fetch_failure_then_recovery(self):
        """Fetch failure increments counter; recovery resets and shows data."""
        UpdateFailed = _get_update_failed()

        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(
            side_effect=CannotConnect("Network error")
        )

        coordinator = _create_coordinator(mock_client)

        # First fetch fails
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 1
        assert coordinator.data is None

        # Sensor with no data shows "No lessons"
        sensor = _create_sensor(coordinator, "recovery_entry")
        assert sensor.native_value == "No lessons"
        assert sensor.available is True  # < 3 failures

        # Recovery: second fetch succeeds
        mock_client.fetch_timetable = AsyncMock(
            return_value=_sample_timetable_json()
        )
        coordinator.data = await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 0
        assert len(coordinator.data) == 6

        # Sensor shows correct state for Wednesday
        state = _get_sensor_state(sensor, datetime(2024, 1, 17, 7, 30))
        assert state == "History 08:00-08:45"
        assert sensor.available is True

    @pytest.mark.asyncio
    async def test_lifecycle_unavailable_after_three_failures(self):
        """Sensor becomes unavailable after 3 failures, recovers on success."""
        UpdateFailed = _get_update_failed()

        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(
            side_effect=CannotConnect("Network error")
        )

        coordinator = _create_coordinator(mock_client)

        # Three consecutive failures
        for _ in range(MAX_CONSECUTIVE_FAILURES):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

        assert coordinator.consecutive_failures == MAX_CONSECUTIVE_FAILURES

        # Sensor with no data is unavailable
        sensor = _create_sensor(coordinator, "unavail_entry")
        assert sensor.available is False
        assert sensor.native_value == "No lessons"

        # Recovery: fetch succeeds
        mock_client.fetch_timetable = AsyncMock(
            return_value=_sample_timetable_json()
        )
        coordinator.data = await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 0
        assert sensor.available is True

        # Sensor shows data for Friday
        state = _get_sensor_state(sensor, datetime(2024, 1, 19, 13, 0))
        assert state == "Art 14:00-14:45"


# --- Integration Tests: Config Flow Validation ---


class TestEndToEndConfigFlowValidation:
    """Integration tests verifying config flow validation logic.

    Tests the URL validation and credential handling that config_flow.py
    performs before creating a config entry. Uses the api module directly
    to test the same logic without depending on the ConfigFlow class mock
    environment.
    """

    @pytest.mark.asyncio
    async def test_valid_credentials_flow(self):
        """Successful authentication creates a usable config entry."""
        # Validate URL (config flow step 1)
        url = "https://school.iserv.de"
        assert validate_url(url) is True

        # Authenticate (config flow step 2)
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)

        client = IServClient(mock_session, url, "student", "secret123")
        result = await client.authenticate()
        assert result is True
        assert client.is_authenticated is True

        # Entry data would be stored
        config_data = {"url": url, "username": "student", "password": "secret123"}

        # Then coordinator can use those credentials
        mock_fetch_client = MagicMock()
        mock_fetch_client.authenticate = AsyncMock(return_value=True)
        mock_fetch_client.fetch_timetable = AsyncMock(
            return_value=_sample_timetable_json()
        )

        coordinator = _create_coordinator(mock_fetch_client)
        coordinator.data = await coordinator._async_update_data()
        assert len(coordinator.data) == 6

    @pytest.mark.asyncio
    async def test_invalid_credentials_prevent_setup(self):
        """Authentication error prevents coordinator creation.

        Simulates: config flow calls authenticate() → raises AuthenticationError
        → flow shows error, no entry created, no coordinator instantiated.
        """
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 401
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)

        client = IServClient(
            mock_session, "https://school.iserv.de", "student", "wrong"
        )

        with pytest.raises(AuthenticationError):
            await client.authenticate()

        assert client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_connection_failure_prevents_setup(self):
        """Connection failure prevents coordinator creation.

        Simulates: config flow calls authenticate() → raises CannotConnect
        → flow shows error, no entry created.
        """
        import asyncio

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.__aenter__ = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)

        client = IServClient(
            mock_session, "https://unreachable.school.de", "student", "pass"
        )

        with pytest.raises(CannotConnect):
            await client.authenticate()

        assert client.is_authenticated is False

    def test_url_validation_rejects_invalid_urls(self):
        """Config flow validates URL format before attempting connection."""
        # Invalid URLs that config flow would reject
        assert validate_url("http://school.iserv.de") is False  # not https
        assert validate_url("school.iserv.de") is False  # no scheme
        assert validate_url("https://") is False  # no host
        assert validate_url("") is False  # empty
        assert validate_url("ftp://school.iserv.de") is False  # wrong scheme

        # Valid URLs that config flow would accept
        assert validate_url("https://school.iserv.de") is True
        assert validate_url("https://my.school.example.com/path") is True


# --- Integration Tests: Sensor State Updates ---


class TestEndToEndSensorUpdates:
    """Integration tests: sensor state updates as coordinator refreshes."""

    @pytest.mark.asyncio
    async def test_sensor_reflects_updated_timetable(self):
        """Sensor updates when coordinator fetches new data."""
        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)

        # Initial timetable (one lesson)
        initial_data = json.dumps([
            {"day": "Monday", "start_time": "08:00", "end_time": "08:45",
             "subject": "Mathematics", "room": "A101"},
        ])
        mock_client.fetch_timetable = AsyncMock(return_value=initial_data)

        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()
        sensor = _create_sensor(coordinator, "update_entry")

        # Verify initial state
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday
        assert _get_sensor_state(sensor, frozen_now) == "Mathematics 08:00-08:45"
        assert len(_get_sensor_attrs(sensor, frozen_now)["lessons"]) == 1

        # Update with new timetable data
        updated_data = json.dumps([
            {"day": "Monday", "start_time": "08:00", "end_time": "08:45",
             "subject": "Chemistry", "room": "F601"},
            {"day": "Monday", "start_time": "09:00", "end_time": "09:45",
             "subject": "German", "room": "G702"},
        ])
        mock_client.fetch_timetable = AsyncMock(return_value=updated_data)
        coordinator.data = await coordinator._async_update_data()

        # Sensor reflects updated data
        assert _get_sensor_state(sensor, frozen_now) == "Chemistry 08:00-08:45"
        attrs = _get_sensor_attrs(sensor, frozen_now)
        assert len(attrs["lessons"]) == 2
        assert attrs["lessons"][1]["subject"] == "German"

    @pytest.mark.asyncio
    async def test_sensor_retains_data_on_update_failure(self):
        """Sensor retains previous data when a refresh fails."""
        UpdateFailed = _get_update_failed()

        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(
            return_value=_sample_timetable_json()
        )

        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()
        assert len(coordinator.data) == 6

        sensor = _create_sensor(coordinator, "retain_entry")

        # Second fetch fails — data preserved
        mock_client.fetch_timetable = AsyncMock(
            side_effect=CannotConnect("Server down")
        )
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 1

        # Sensor still shows previous data
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday
        assert _get_sensor_state(sensor, frozen_now) == "Mathematics 08:00-08:45"
        assert len(_get_sensor_attrs(sensor, frozen_now)["lessons"]) == 6
        assert sensor.available is True

    @pytest.mark.asyncio
    async def test_full_parse_pipeline_preserves_data_structure(self):
        """Full pipeline: raw JSON → parse → sort → sensor attributes.

        Verifies data structure: sorted lessons, empty string defaults,
        HH:MM format, all fields present, correct markdown table.
        """
        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)

        raw_json = json.dumps([
            {"day": "Wednesday", "start_time": "10:00", "end_time": "10:45",
             "subject": "Music", "room": ""},
            {"day": "Monday", "start_time": "14:00", "end_time": "14:45",
             "subject": "", "room": "Z999"},
            {"day": "Monday", "start_time": "08:00", "end_time": "08:45",
             "subject": "Math", "room": "A1"},
        ])
        mock_client.fetch_timetable = AsyncMock(return_value=raw_json)

        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()

        # Verify sort order: Monday first (by time), then Wednesday
        assert coordinator.data[0].day == "Monday"
        assert coordinator.data[0].start_time == "08:00"
        assert coordinator.data[0].subject == "Math"
        assert coordinator.data[1].day == "Monday"
        assert coordinator.data[1].start_time == "14:00"
        assert coordinator.data[1].subject == ""  # empty string default
        assert coordinator.data[2].day == "Wednesday"
        assert coordinator.data[2].room == ""  # empty room default

        # Verify sensor attributes
        sensor = _create_sensor(coordinator, "parse_entry")
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday
        attrs = _get_sensor_attrs(sensor, frozen_now)

        # Each lesson dict has all required fields
        for lesson_dict in attrs["lessons"]:
            assert "day" in lesson_dict
            assert "start_time" in lesson_dict
            assert "end_time" in lesson_dict
            assert "subject" in lesson_dict
            assert "room" in lesson_dict
            assert lesson_dict["canceled"] is False

        # Markdown table
        table = attrs["timetable_table"]
        assert "| Day | Time | Subject | Room | Canceled |" in table
        assert "| Monday | 08:00 - 08:45 | Math | A1 | false |" in table
        assert "| Monday | 14:00 - 14:45 |  | Z999 | false |" in table
        assert "| Wednesday | 10:00 - 10:45 | Music |  | false |" in table

    @pytest.mark.asyncio
    async def test_no_upcoming_lessons_shows_correct_state(self):
        """Sensor shows 'No upcoming lessons' when all today's lessons passed."""
        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(
            return_value=_sample_timetable_json()
        )

        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()
        sensor = _create_sensor(coordinator, "no_upcoming_entry")

        # Monday at 18:00 — all Monday lessons have passed
        state = _get_sensor_state(sensor, datetime(2024, 1, 15, 18, 0))
        assert state == "No upcoming lessons"

    @pytest.mark.asyncio
    async def test_empty_timetable_shows_no_lessons(self):
        """Sensor shows 'No lessons' when timetable is empty."""
        mock_client = MagicMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.fetch_timetable = AsyncMock(return_value="[]")

        coordinator = _create_coordinator(mock_client)
        coordinator.data = await coordinator._async_update_data()
        sensor = _create_sensor(coordinator, "empty_entry")

        assert sensor.native_value == "No lessons"
        attrs = _get_sensor_attrs(sensor, datetime(2024, 1, 15, 8, 0))
        assert attrs["lessons"] == []
        assert attrs["timetable_table"] == ""
