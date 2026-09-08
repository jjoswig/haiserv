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
from .coordinator import IServCoordinator, IServParentLetterCoordinator
from .parser import format_markdown_table, get_next_lesson
from .parentletter_parser import ParentLetter


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
    entities: list[SensorEntity] = [IServTimetableSensor(coordinator, entry)]

    next_week_coordinator = hass.data[DOMAIN].get(
        f"{entry.entry_id}_next_week"
    )
    if next_week_coordinator is not None:
        entities.append(IServNextWeekTimetableSensor(next_week_coordinator, entry))

    parentletter_coordinator: IServParentLetterCoordinator | None = hass.data[DOMAIN].get(
        f"{entry.entry_id}_parentletter"
    )
    if parentletter_coordinator is not None:
        entities.append(IServParentLetterSensor(parentletter_coordinator, entry))

    async_add_entities(entities)


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
            - "lessons": list of lesson dicts including the canceled status
            - "timetable_data": complete JSON data returned by the timetable API
            - "timetable_table": Markdown table string
            - "last_updated": ISO 8601 timestamp of last successful update
        """
        lessons = self.coordinator.data or []

        return {
            "lessons": [asdict(lesson) for lesson in lessons],
            "timetable_data": getattr(self.coordinator, "timetable_data", None),
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


class IServNextWeekTimetableSensor(IServTimetableSensor):
    """Sensor exposing the complete timetable for the following week."""

    _attr_name = "iServ Next Week Timetable"

    def __init__(
        self, coordinator: IServCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the next-week timetable sensor."""
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_week_timetable"

    @property
    def native_value(self) -> str:
        """Return the number of lessons in the following week's timetable."""
        lessons = self.coordinator.data
        if not lessons:
            return "No lessons"
        return f"{len(lessons)} lessons"


class IServParentLetterSensor(
    CoordinatorEntity[IServParentLetterCoordinator], SensorEntity
):
    """Sensor entity exposing unread Elternbrief (parent letter) count and list."""

    _attr_name = "iServ Parent Letters"

    def __init__(
        self, coordinator: IServParentLetterCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the parent-letter sensor.

        Args:
            coordinator: The IServParentLetterCoordinator managing data fetching.
            entry: The config entry for this integration instance.
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_parentletter"

    @property
    def native_value(self) -> str:
        """Return the number of unread Elternbriefe as a human-readable string.

        Returns:
            - "N unread" when there is at least one unread letter
            - "No unread letters" when all letters have been read
            - "No letters" when no letters are available
        """
        letters: list[ParentLetter] = self.coordinator.data or []
        if not letters:
            return "No letters"
        unread = sum(1 for letter in letters if letter.is_unread)
        if unread == 0:
            return "No unread letters"
        return f"{unread} unread"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return letter list and metadata as state attributes.

        Returns:
            Dict with:
            - "letters": list of letter dicts (without body_html to keep size small)
            - "unread_count": integer count of unread letters
            - "total_count": total number of letters fetched
            - "last_updated": ISO 8601 timestamp of last successful update
        """
        letters: list[ParentLetter] = self.coordinator.data or []

        def _letter_to_dict(letter: ParentLetter) -> dict[str, Any]:
            return {
                "letter_uuid": letter.letter_uuid,
                "child_uuid": letter.child_uuid,
                "subject": letter.subject,
                "sender": letter.sender,
                "additional_senders": letter.additional_senders,
                "child": letter.child,
                "recipient": letter.recipient,
                "created_at": (
                    letter.created_at.isoformat() if letter.created_at else None
                ),
                "is_unread": letter.is_unread,
            }

        return {
            "letters": [_letter_to_dict(letter) for letter in letters],
            "unread_count": sum(1 for letter in letters if letter.is_unread),
            "total_count": len(letters),
            "last_updated": datetime.now().isoformat(),
        }

    @property
    def available(self) -> bool:
        """Return True unless too many consecutive failures with no cached data.

        Returns False only when consecutive failures >= MAX_CONSECUTIVE_FAILURES
        AND no prior data exists.
        """
        if (
            self.coordinator.consecutive_failures >= MAX_CONSECUTIVE_FAILURES
            and not self.coordinator.data
        ):
            return False
        return True
