"""Unit tests for IServCoordinator lifecycle.

Tests verify:
- 60-minute update interval configuration
- Session re-authentication on expiry
- Consecutive failure counter increments and resets
- Logging behavior on failures

Requirements: 8.4
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeDataUpdateCoordinator:
    """Minimal stub for DataUpdateCoordinator to test coordinator logic."""

    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval

    def __init_subclass__(cls, **kwargs):
        """Allow subclassing without issues."""
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        """Support generic subscript syntax (e.g., DataUpdateCoordinator[list[Lesson]])."""
        return cls


class _FakeUpdateFailed(Exception):
    """Stub for homeassistant UpdateFailed exception."""


# Install the fake classes into the already-mocked HA modules (from conftest.py).
# Use direct assignment (not setdefault) so they override whatever MagicMock attributes
# the conftest may have already set up.
_ha_update_coord_mod = sys.modules["homeassistant.helpers.update_coordinator"]
_ha_update_coord_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
_ha_update_coord_mod.UpdateFailed = _FakeUpdateFailed

_ha_core_mod = sys.modules["homeassistant.core"]
_ha_core_mod.HomeAssistant = MagicMock

# Force reimport the coordinator module so it picks up our fake classes
# (it may have been cached from earlier imports with generic MagicMock)
if "custom_components.iserv.coordinator" in sys.modules:
    del sys.modules["custom_components.iserv.coordinator"]

# Now import the coordinator module — it will find mocked HA modules
from custom_components.iserv.coordinator import IServCoordinator  # noqa: E402
from custom_components.iserv.api import AuthenticationError, CannotConnect  # noqa: E402
from custom_components.iserv.const import DEFAULT_UPDATE_INTERVAL  # noqa: E402
from custom_components.iserv.parser import Lesson  # noqa: E402


# --- Fixtures ---


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    return MagicMock()


@pytest.fixture
def mock_client():
    """Create a mock IServClient with async methods."""
    client = MagicMock()
    client.authenticate = AsyncMock()
    client.fetch_timetable = AsyncMock()
    return client


@pytest.fixture
def coordinator(mock_hass, mock_client):
    """Create an IServCoordinator instance with mocked dependencies."""
    return IServCoordinator(mock_hass, mock_client)


def _sample_timetable_json() -> str:
    """Return a valid JSON timetable response for testing."""
    import json

    return json.dumps([
        {
            "day": "Monday",
            "start_time": "08:00",
            "end_time": "08:45",
            "subject": "Math",
            "room": "A201",
        },
        {
            "day": "Monday",
            "start_time": "09:00",
            "end_time": "09:45",
            "subject": "English",
            "room": "B102",
        },
    ])


# --- Test: 60-minute update interval configuration ---


class TestUpdateInterval:
    """Tests verifying the coordinator uses a 60-minute update interval."""

    def test_update_interval_is_60_minutes(self, coordinator):
        """Coordinator should have a 60-minute update interval."""
        expected = timedelta(minutes=60)
        assert coordinator.update_interval == expected

    def test_update_interval_matches_constant(self, coordinator):
        """Update interval should match DEFAULT_UPDATE_INTERVAL constant."""
        expected = timedelta(minutes=DEFAULT_UPDATE_INTERVAL)
        assert coordinator.update_interval == expected


# --- Test: Session re-authentication on expiry ---


class TestReAuthentication:
    """Tests verifying the coordinator re-authenticates on session expiry."""

    async def test_reauth_on_auth_error_then_success(self, coordinator, mock_client):
        """On AuthenticationError, coordinator re-authenticates and retries fetch."""
        # First fetch raises AuthenticationError (session expired)
        # After re-auth, second fetch succeeds
        mock_client.fetch_timetable.side_effect = [
            AuthenticationError("Session expired"),
            _sample_timetable_json(),
        ]
        mock_client.authenticate.return_value = True

        result = await coordinator._async_update_data()

        # Should have called authenticate once for re-auth
        mock_client.authenticate.assert_called_once()
        # Should have called fetch_timetable twice (initial + retry)
        assert mock_client.fetch_timetable.call_count == 2
        # Should return parsed lessons
        assert len(result) == 2
        assert result[0].subject == "Math"

    async def test_reauth_failure_raises_update_failed(self, coordinator, mock_client):
        """If re-auth also fails, coordinator raises UpdateFailed."""
        # First fetch fails with AuthenticationError
        mock_client.fetch_timetable.side_effect = [
            AuthenticationError("Session expired"),
            AuthenticationError("Still expired"),
        ]
        # Re-authentication succeeds but second fetch still fails
        mock_client.authenticate.return_value = True

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

    async def test_reauth_authenticate_raises_error(self, coordinator, mock_client):
        """If authenticate() itself raises, coordinator raises UpdateFailed."""
        # First fetch fails with AuthenticationError
        mock_client.fetch_timetable.side_effect = AuthenticationError("Session expired")
        # Re-authentication also fails
        mock_client.authenticate.side_effect = AuthenticationError("Bad credentials")

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

    async def test_reauth_connect_error_raises_update_failed(
        self, coordinator, mock_client
    ):
        """If re-auth succeeds but retry fetch gets CannotConnect, raises UpdateFailed."""
        mock_client.fetch_timetable.side_effect = [
            AuthenticationError("Session expired"),
            CannotConnect("Network error"),
        ]
        mock_client.authenticate.return_value = True

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()


# --- Test: Consecutive failure counter increments and resets ---


class TestConsecutiveFailures:
    """Tests verifying the consecutive failure counter behavior."""

    def test_initial_failure_count_is_zero(self, coordinator):
        """Coordinator starts with zero consecutive failures."""
        assert coordinator.consecutive_failures == 0

    async def test_increment_on_cannot_connect(self, coordinator, mock_client):
        """Counter increments on CannotConnect errors."""
        mock_client.fetch_timetable.side_effect = CannotConnect("Network error")

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 1

    async def test_increment_multiple_failures(self, coordinator, mock_client):
        """Counter increments on each consecutive failure."""
        mock_client.fetch_timetable.side_effect = CannotConnect("Network error")

        for expected_count in range(1, 4):
            with pytest.raises(_FakeUpdateFailed):
                await coordinator._async_update_data()
            assert coordinator.consecutive_failures == expected_count

    async def test_increment_on_auth_retry_failure(self, coordinator, mock_client):
        """Counter increments when re-auth + retry also fails."""
        mock_client.fetch_timetable.side_effect = [
            AuthenticationError("Session expired"),
            AuthenticationError("Still expired"),
        ]
        mock_client.authenticate.return_value = True

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 1

    async def test_reset_on_success(self, coordinator, mock_client):
        """Counter resets to zero on successful fetch."""
        # First, accumulate some failures
        mock_client.fetch_timetable.side_effect = CannotConnect("Network error")

        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()
        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 2

        # Now succeed
        mock_client.fetch_timetable.side_effect = None
        mock_client.fetch_timetable.return_value = _sample_timetable_json()

        await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 0

    async def test_reset_after_reauth_success(self, coordinator, mock_client):
        """Counter resets when re-auth + retry succeeds."""
        # Accumulate a failure first
        mock_client.fetch_timetable.side_effect = CannotConnect("Network error")
        with pytest.raises(_FakeUpdateFailed):
            await coordinator._async_update_data()
        assert coordinator.consecutive_failures == 1

        # Next call: auth error then successful retry
        mock_client.fetch_timetable.side_effect = [
            AuthenticationError("Session expired"),
            _sample_timetable_json(),
        ]
        mock_client.authenticate.return_value = True

        await coordinator._async_update_data()

        assert coordinator.consecutive_failures == 0


# --- Test: Logging behavior on failures ---


class TestLoggingOnFailures:
    """Tests verifying appropriate logging on coordinator failures."""

    async def test_warning_logged_on_cannot_connect(
        self, coordinator, mock_client, caplog
    ):
        """Warning is logged when fetch fails with CannotConnect."""
        mock_client.fetch_timetable.side_effect = CannotConnect("Connection refused")

        with caplog.at_level(logging.WARNING):
            with pytest.raises(_FakeUpdateFailed):
                await coordinator._async_update_data()

        assert "Failed to connect to iServ" in caplog.text
        assert "consecutive failures: 1" in caplog.text

    async def test_error_logged_on_auth_retry_failure(
        self, coordinator, mock_client, caplog
    ):
        """Error is logged when re-authentication and retry both fail."""
        mock_client.fetch_timetable.side_effect = [
            AuthenticationError("Session expired"),
            AuthenticationError("Still expired"),
        ]
        mock_client.authenticate.return_value = True

        with caplog.at_level(logging.ERROR):
            with pytest.raises(_FakeUpdateFailed):
                await coordinator._async_update_data()

        assert "Failed to fetch timetable after re-authentication" in caplog.text
        assert "consecutive failures: 1" in caplog.text

    async def test_warning_includes_failure_count(
        self, coordinator, mock_client, caplog
    ):
        """Log message includes the current consecutive failure count."""
        mock_client.fetch_timetable.side_effect = CannotConnect("Timeout")

        # First failure
        with caplog.at_level(logging.WARNING):
            with pytest.raises(_FakeUpdateFailed):
                await coordinator._async_update_data()

        assert "consecutive failures: 1" in caplog.text
        caplog.clear()

        # Second failure
        with caplog.at_level(logging.WARNING):
            with pytest.raises(_FakeUpdateFailed):
                await coordinator._async_update_data()

        assert "consecutive failures: 2" in caplog.text

    async def test_no_logging_on_success(self, coordinator, mock_client, caplog):
        """No warning or error is logged on successful fetch."""
        mock_client.fetch_timetable.return_value = _sample_timetable_json()

        with caplog.at_level(logging.WARNING):
            await coordinator._async_update_data()

        # No warnings or errors in log output
        assert caplog.text == ""
