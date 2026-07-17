"""Sensor platform for the iServ integration."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_CONSECUTIVE_FAILURES
from .coordinator import IServCoordinator
from .parser import format_markdown_table, get_next_lesson


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iServ sensor entities from a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.
        async_add_entities: Callback to add entities to Home Assistant.
    """
    coordinator: IServCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IServTimetableSensor(coordinator, entry)])


class IServTimetableSensor(CoordinatorEntity[IServCoordinator], SensorEntity):
    """Sensor entity exposing timetable data."""

    _attr_name = "iServ Timetable"

    def __init__(
        self, coordinator: IServCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the timetable sensor.

        Args:
            coordinator: The IServCoordinator managing data fetching.
            entry: The config entry for this integration instance.
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_timetable"

    @property
    def native_value(self) -> str:
        """Return the next upcoming lesson or a status message.

        Returns:
            - "{subject} {start_time}-{end_time}" if a lesson is upcoming today
            - "No upcoming lessons" if no more lessons today
            - "No lessons" if the timetable is empty for the week
        """
        lessons = self.coordinator.data

        if not lessons:
            return "No lessons"

        next_lesson = get_next_lesson(lessons, datetime.now())

        if next_lesson is None:
            return "No upcoming lessons"

        state = f"{next_lesson.subject} {next_lesson.start_time}-{next_lesson.end_time}"
        # Truncate to 255 characters max per HA sensor state limit
        return state[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes.

        Returns:
            Dict with:
            - "lessons": list of lesson dicts (day, start_time, end_time, subject, room)
            - "timetable_table": Markdown table string
            - "last_updated": ISO 8601 timestamp of last successful update
        """
        lessons = self.coordinator.data or []

        return {
            "lessons": [asdict(lesson) for lesson in lessons],
            "timetable_table": format_markdown_table(lessons),
            "last_updated": datetime.now().isoformat(),
        }

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Returns False if consecutive failures >= MAX_CONSECUTIVE_FAILURES
        and no prior data exists. Stale data is better than no data.
        """
        if (
            self.coordinator.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
            and not self.coordinator.data
        ):
            return False
        return True
