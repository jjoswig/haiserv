"""Unit tests for IServTimetableSensor entity.

Tests verify:
- State with upcoming lesson, no upcoming lessons, empty timetable
- Attributes contain correct lessons list, markdown table, last_updated timestamp
- Availability based on consecutive failures and data presence
- Data retention on failure (previous data preserved)

Requirements: 8.3, 8.4
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# --- Mock homeassistant modules before importing sensor ---
#
# We use setdefault so we don't clobber mocks set by other test files
# (e.g., test_coordinator.py) that run in the same pytest session.
# The key modules we need for sensor.py are:
#   - homeassistant.helpers.update_coordinator.CoordinatorEntity
#   - homeassistant.components.sensor.SensorEntity
#   - homeassistant.config_entries.ConfigEntry
#   - homeassistant.helpers.entity_platform.AddEntitiesCallback


class _FakeCoordinatorEntity:
    """Minimal stub for CoordinatorEntity."""

    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeSensorEntity:
    """Minimal stub for SensorEntity."""

    pass


class _FakeDataUpdateCoordinator:
    """Minimal stub for DataUpdateCoordinator."""

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeUpdateFailed(Exception):
    """Stub for UpdateFailed exception."""


def _setup_ha_mocks():
    """Set up homeassistant module mocks, merging with any existing mocks."""
    # Core module
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = MagicMock()
    if "homeassistant.core" not in sys.modules:
        sys.modules["homeassistant.core"] = MagicMock()

    # helpers.update_coordinator — ensure CoordinatorEntity exists
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = MagicMock()

    uc_mod = sys.modules.get("homeassistant.helpers.update_coordinator")
    if uc_mod is None:
        uc_mod = MagicMock()
        sys.modules["homeassistant.helpers.update_coordinator"] = uc_mod
        uc_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
        uc_mod.UpdateFailed = _FakeUpdateFailed

    # Always ensure CoordinatorEntity is our real class (needed for sensor MRO)
    uc_mod.CoordinatorEntity = _FakeCoordinatorEntity

    # helpers.entity_platform
    if "homeassistant.helpers.entity_platform" not in sys.modules:
        sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()

    # components.sensor — ensure SensorEntity is a real class
    if "homeassistant.components" not in sys.modules:
        sys.modules["homeassistant.components"] = MagicMock()

    sensor_mod = sys.modules.get("homeassistant.components.sensor")
    if sensor_mod is None:
        sensor_mod = MagicMock()
        sys.modules["homeassistant.components.sensor"] = sensor_mod
    sensor_mod.SensorEntity = _FakeSensorEntity

    # config_entries
    if "homeassistant.config_entries" not in sys.modules:
        sys.modules["homeassistant.config_entries"] = MagicMock()


_setup_ha_mocks()

# Ensure fresh import of sensor module with our mocks
if "custom_components.haiserv.sensor" in sys.modules:
    del sys.modules["custom_components.haiserv.sensor"]

# Now import sensor module
from custom_components.haiserv.sensor import IServTimetableSensor  # noqa: E402
from custom_components.haiserv.parser import Lesson, format_markdown_table  # noqa: E402
from custom_components.haiserv.const import MAX_CONSECUTIVE_FAILURES  # noqa: E402


# --- Fixtures ---


@pytest.fixture
def sample_lessons() -> list[Lesson]:
    """Return a list of sample lessons for testing."""
    return [
        Lesson(day="Monday", start_time="08:00", end_time="08:45", subject="Math", room="A201"),
        Lesson(day="Monday", start_time="09:00", end_time="09:45", subject="English", room="B102"),
        Lesson(day="Tuesday", start_time="10:00", end_time="10:45", subject="Physics", room="C303"),
        Lesson(day="Wednesday", start_time="08:00", end_time="08:45", subject="History", room="D104"),
    ]


@pytest.fixture
def mock_coordinator(sample_lessons):
    """Create a mock coordinator with data and consecutive_failures."""
    coordinator = MagicMock()
    coordinator.data = sample_lessons
    coordinator.consecutive_failures = 0
    return coordinator


@pytest.fixture
def mock_entry():
    """Create a mock ConfigEntry with an entry_id."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    return entry


@pytest.fixture
def sensor(mock_coordinator, mock_entry):
    """Create an IServTimetableSensor instance."""
    return IServTimetableSensor(mock_coordinator, mock_entry)


# --- Test: Sensor state with upcoming lesson ---


class TestSensorState:
    """Tests verifying the sensor native_value in various conditions."""

    def test_state_with_upcoming_lesson(self, mock_coordinator, mock_entry):
        """State shows next lesson when one is upcoming today."""
        # Monday at 07:30 — the 08:00 Math lesson is upcoming
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday

        sensor = IServTimetableSensor(mock_coordinator, mock_entry)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value

        assert state == "Math 08:00-08:45"

    def test_state_with_second_lesson_upcoming(self, mock_coordinator, mock_entry):
        """State shows next upcoming lesson when first has already started."""
        # Monday at 08:30 — the 08:00 lesson already started, 09:00 is next
        frozen_now = datetime(2024, 1, 15, 8, 30)  # Monday

        sensor = IServTimetableSensor(mock_coordinator, mock_entry)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value

        assert state == "English 09:00-09:45"

    def test_state_no_upcoming_lessons_today(self, mock_coordinator, mock_entry):
        """State shows 'No upcoming lessons' when all lessons for today are past."""
        # Monday at 18:00 — all Monday lessons already passed
        frozen_now = datetime(2024, 1, 15, 18, 0)  # Monday

        sensor = IServTimetableSensor(mock_coordinator, mock_entry)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value

        assert state == "No upcoming lessons"

    def test_state_no_lessons_on_current_day(self, mock_coordinator, mock_entry):
        """State shows 'No upcoming lessons' when no lessons exist for today's weekday."""
        # Friday — no lessons exist for Friday in sample data
        frozen_now = datetime(2024, 1, 19, 8, 0)  # Friday

        sensor = IServTimetableSensor(mock_coordinator, mock_entry)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value

        assert state == "No upcoming lessons"

    def test_state_empty_timetable(self, mock_entry):
        """State shows 'No lessons' when timetable is completely empty."""
        coordinator = MagicMock()
        coordinator.data = []
        coordinator.consecutive_failures = 0

        sensor = IServTimetableSensor(coordinator, mock_entry)
        state = sensor.native_value

        assert state == "No lessons"

    def test_state_none_data(self, mock_entry):
        """State shows 'No lessons' when coordinator data is None."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.consecutive_failures = 0

        sensor = IServTimetableSensor(coordinator, mock_entry)
        state = sensor.native_value

        assert state == "No lessons"

    def test_state_truncated_to_255_chars(self, mock_entry):
        """State is truncated to 255 characters max."""
        # Create a lesson with a very long subject name
        long_subject = "A" * 300
        lessons = [
            Lesson(day="Monday", start_time="08:00", end_time="08:45", subject=long_subject, room="A1"),
        ]
        coordinator = MagicMock()
        coordinator.data = lessons
        coordinator.consecutive_failures = 0

        sensor = IServTimetableSensor(coordinator, mock_entry)

        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value

        assert len(state) <= 255


# --- Test: Sensor attributes ---


class TestSensorAttributes:
    """Tests verifying extra_state_attributes content."""

    def test_attributes_contain_lessons_list(self, sensor, sample_lessons):
        """Attributes include 'lessons' as a list of dicts."""
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 8, 0)
            attrs = sensor.extra_state_attributes

        assert "lessons" in attrs
        assert isinstance(attrs["lessons"], list)
        assert len(attrs["lessons"]) == len(sample_lessons)

        # Verify each lesson is a dict with correct fields
        for lesson_dict, original in zip(attrs["lessons"], sample_lessons):
            assert lesson_dict == asdict(original)

    def test_attributes_contain_timetable_table(self, sensor, sample_lessons):
        """Attributes include 'timetable_table' as a markdown string."""
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 8, 0)
            attrs = sensor.extra_state_attributes

        assert "timetable_table" in attrs
        expected_table = format_markdown_table(sample_lessons)
        assert attrs["timetable_table"] == expected_table

    def test_attributes_contain_last_updated_iso(self, sensor):
        """Attributes include 'last_updated' as ISO 8601 timestamp."""
        frozen_now = datetime(2024, 1, 15, 10, 30, 0)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            attrs = sensor.extra_state_attributes

        assert "last_updated" in attrs
        assert attrs["last_updated"] == frozen_now.isoformat()

    def test_attributes_empty_timetable(self, mock_entry):
        """Attributes with empty timetable have empty lessons and empty table."""
        coordinator = MagicMock()
        coordinator.data = []
        coordinator.consecutive_failures = 0

        sensor = IServTimetableSensor(coordinator, mock_entry)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 8, 0)
            attrs = sensor.extra_state_attributes

        assert attrs["lessons"] == []
        assert attrs["timetable_table"] == ""

    def test_attributes_none_data(self, mock_entry):
        """Attributes with None data default to empty lessons and table."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.consecutive_failures = 0

        sensor = IServTimetableSensor(coordinator, mock_entry)

        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 15, 8, 0)
            attrs = sensor.extra_state_attributes

        assert attrs["lessons"] == []
        assert attrs["timetable_table"] == ""


# --- Test: Sensor availability ---


class TestSensorAvailability:
    """Tests verifying the sensor availability property."""

    def test_available_when_no_failures(self, sensor):
        """Sensor is available when no consecutive failures."""
        assert sensor.available is True

    def test_available_with_failures_below_threshold(self, mock_coordinator, mock_entry):
        """Sensor is available when failures < MAX_CONSECUTIVE_FAILURES."""
        mock_coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1
        sensor = IServTimetableSensor(mock_coordinator, mock_entry)
        assert sensor.available is True

    def test_available_with_failures_at_threshold_but_data_exists(
        self, mock_coordinator, mock_entry
    ):
        """Sensor stays available with stale data even at failure threshold."""
        mock_coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        # Data exists (stale data is better than no data)
        sensor = IServTimetableSensor(mock_coordinator, mock_entry)
        assert sensor.available is True

    def test_unavailable_with_failures_at_threshold_and_no_data(self, mock_entry):
        """Sensor is unavailable when failures >= threshold AND no data."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES

        sensor = IServTimetableSensor(coordinator, mock_entry)
        assert sensor.available is False

    def test_unavailable_with_failures_at_threshold_and_empty_data(self, mock_entry):
        """Sensor is unavailable when failures >= threshold AND empty data."""
        coordinator = MagicMock()
        coordinator.data = []
        coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES

        sensor = IServTimetableSensor(coordinator, mock_entry)
        assert sensor.available is False

    def test_unavailable_with_many_failures_and_no_data(self, mock_entry):
        """Sensor is unavailable with failures well above threshold and no data."""
        coordinator = MagicMock()
        coordinator.data = None
        coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES + 5

        sensor = IServTimetableSensor(coordinator, mock_entry)
        assert sensor.available is False


# --- Test: Data retention on failure ---


class TestDataRetention:
    """Tests verifying data retention after coordinator failures."""

    def test_previous_data_preserved_after_failure(self, sample_lessons, mock_entry):
        """After a failure, sensor still shows previous lesson data."""
        coordinator = MagicMock()
        coordinator.data = sample_lessons
        coordinator.consecutive_failures = 1  # One failure, data still there

        sensor = IServTimetableSensor(coordinator, mock_entry)

        # State should still reflect existing data
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value
            attrs = sensor.extra_state_attributes

        assert state == "Math 08:00-08:45"
        assert len(attrs["lessons"]) == len(sample_lessons)

    def test_stale_data_preserved_after_multiple_failures(
        self, sample_lessons, mock_entry
    ):
        """After multiple failures, sensor retains stale data and stays available."""
        coordinator = MagicMock()
        coordinator.data = sample_lessons
        coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES

        sensor = IServTimetableSensor(coordinator, mock_entry)

        # Still available because data exists
        assert sensor.available is True

        # Data is still reflected
        frozen_now = datetime(2024, 1, 15, 7, 30)  # Monday
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            state = sensor.native_value
            attrs = sensor.extra_state_attributes

        assert state == "Math 08:00-08:45"
        assert len(attrs["lessons"]) == len(sample_lessons)
        assert attrs["timetable_table"] == format_markdown_table(sample_lessons)

    def test_attributes_unchanged_after_failure(self, sample_lessons, mock_entry):
        """Attributes remain the same after a failure — data is not cleared."""
        coordinator = MagicMock()
        coordinator.data = sample_lessons
        coordinator.consecutive_failures = 2

        sensor = IServTimetableSensor(coordinator, mock_entry)

        frozen_now = datetime(2024, 1, 15, 10, 0)
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen_now
            attrs = sensor.extra_state_attributes

        # Lessons should match the stale data
        expected_lessons = [asdict(lesson) for lesson in sample_lessons]
        assert attrs["lessons"] == expected_lessons
        assert attrs["timetable_table"] == format_markdown_table(sample_lessons)


# --- Test: Unique ID ---


class TestSensorIdentity:
    """Tests verifying sensor entity identity attributes."""

    def test_unique_id_format(self, sensor, mock_entry):
        """Sensor unique_id includes entry_id and 'timetable' suffix."""
        assert sensor._attr_unique_id == f"{mock_entry.entry_id}_timetable"

    def test_entity_name(self, sensor):
        """Sensor has the correct name."""
        assert sensor._attr_name == "iServ Timetable"
