"""DataUpdateCoordinator for the iServ integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, CannotConnect, IServClient
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from .parser import Lesson, parse_timetable, sort_lessons

_LOGGER = logging.getLogger(__name__)


class IServCoordinator(DataUpdateCoordinator[list[Lesson]]):
    """Coordinator to manage iServ timetable data fetching."""

    def __init__(self, hass: HomeAssistant, client: IServClient) -> None:
        """Initialize the coordinator.

        Args:
            hass: The Home Assistant instance.
            client: An authenticated IServClient instance.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_UPDATE_INTERVAL),
        )
        self.client = client
        self.consecutive_failures: int = 0

    async def _async_update_data(self) -> list[Lesson]:
        """Fetch and parse timetable. Handle auth expiry and retries.

        Returns:
            Sorted list of Lesson objects for the current week.

        Raises:
            UpdateFailed: If the fetch fails due to network errors or
                repeated authentication failures.
        """
        # Get the current calendar week number
        current_week = datetime.now().isocalendar()[1]

        try:
            raw_data = await self.client.fetch_timetable(week=current_week)
        except AuthenticationError:
            # Session expired — try re-authenticating once and retry
            try:
                await self.client.authenticate()
                raw_data = await self.client.fetch_timetable(week=current_week)
            except (AuthenticationError, CannotConnect) as err:
                self.consecutive_failures += 1
                _LOGGER.error(
                    "Failed to fetch timetable after re-authentication attempt "
                    "(consecutive failures: %d): %s",
                    self.consecutive_failures,
                    err,
                )
                raise UpdateFailed(
                    f"Authentication failed after retry: {err}"
                ) from err
        except CannotConnect as err:
            self.consecutive_failures += 1
            _LOGGER.warning(
                "Failed to connect to iServ (consecutive failures: %d): %s",
                self.consecutive_failures,
                err,
            )
            raise UpdateFailed(
                f"Cannot connect to iServ: {err}"
            ) from err

        # Parse and sort the timetable data
        lessons = parse_timetable(raw_data, locale="en")
        sorted_lessons = sort_lessons(lessons)

        # Success — reset consecutive failure counter
        self.consecutive_failures = 0

        return sorted_lessons
