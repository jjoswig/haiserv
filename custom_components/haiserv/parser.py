"""Timetable parsing logic for the iServ integration."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from .const import DAY_ORDER

_LOGGER = logging.getLogger(__name__)


@dataclass
class Lesson:
    """Represents a single lesson in the timetable."""

    day: str  # Localized weekday name ("Monday" / "Montag")
    start_time: str  # "HH:MM" format
    end_time: str  # "HH:MM" format
    subject: str  # Subject name or empty string
    room: str  # Room identifier or empty string
    canceled: bool = False  # Whether the lesson was canceled


def parse_timetable(raw_data: str, locale: str) -> list[Lesson]:
    """Parse raw iServ timetable response into structured lesson objects.

    Expects a JSON string containing a list of lesson objects with fields:
    day, start_time, end_time, subject, room, canceled.

    Entries missing day or start_time or end_time are skipped.
    Missing subject/room default to empty string.

    Args:
        raw_data: JSON string from iServ timetable response.
        locale: Locale string (e.g., "en", "de") for day name localization.

    Returns:
        List of Lesson objects parsed from the response.
    """
    if not raw_data or not raw_data.strip():
        return []

    try:
        data = json.loads(raw_data)
    except (json.JSONDecodeError, TypeError):
        _LOGGER.warning("Failed to parse timetable response as JSON")
        return []

    if not isinstance(data, list):
        _LOGGER.warning("Timetable response is not a list")
        return []

    lessons: list[Lesson] = []

    for entry in data:
        if not isinstance(entry, dict):
            continue

        day = entry.get("day")
        start_time = entry.get("start_time")
        end_time = entry.get("end_time")

        # Skip entries missing required fields (day or time)
        if not day or not start_time or not end_time:
            continue

        # Validate day is a non-empty string
        if not isinstance(day, str) or not day.strip():
            continue

        # Validate time format (HH:MM)
        if not _is_valid_time(start_time) or not _is_valid_time(end_time):
            _LOGGER.warning(
                "Skipping lesson with invalid time format: %s - %s",
                start_time,
                end_time,
            )
            continue

        # Default missing subject/room to empty string
        subject = entry.get("subject") or ""
        room = entry.get("room") or ""

        # Ensure subject and room are strings
        if not isinstance(subject, str):
            subject = str(subject)
        if not isinstance(room, str):
            room = str(room)

        lessons.append(
            Lesson(
                day=day.strip(),
                start_time=start_time.strip(),
                end_time=end_time.strip(),
                subject=subject.strip(),
                room=room.strip(),
                canceled=entry.get("canceled") is True,
            )
        )

    return lessons


def sort_lessons(lessons: list[Lesson]) -> list[Lesson]:
    """Sort lessons by day (Mon-Fri) then by start_time ascending.

    Days are ordered according to DAY_ORDER (Monday=0 through Friday=4).
    Days not found in DAY_ORDER are placed at the end.
    Within the same day, lessons are sorted by start_time in ascending order.

    Args:
        lessons: List of Lesson objects to sort.

    Returns:
        New sorted list of Lesson objects.
    """
    return sorted(
        lessons,
        key=lambda lesson: (
            DAY_ORDER.get(lesson.day, 99),
            lesson.start_time,
        ),
    )


def format_markdown_table(lessons: list[Lesson]) -> str:
    """Format lessons as a Markdown pipe-and-dash table string.

    Produces a table with columns: Day, Time, Subject, Room, Canceled.
    Time is formatted as "HH:MM - HH:MM".
    Returns empty string for an empty list.

    Args:
        lessons: List of Lesson objects to format.

    Returns:
        Markdown table string or empty string if no lessons.
    """
    if not lessons:
        return ""

    lines: list[str] = []

    # Header row
    lines.append("| Day | Time | Subject | Room | Canceled |")
    # Separator row
    lines.append("| --- | --- | --- | --- | --- |")

    # Data rows
    for lesson in lessons:
        time_str = f"{lesson.start_time} - {lesson.end_time}"
        lines.append(
            f"| {lesson.day} | {time_str} | {lesson.subject} | {lesson.room} | "
            f"{str(lesson.canceled).lower()} |"
        )

    return "\n".join(lines)


def get_next_lesson(lessons: list[Lesson], now: datetime) -> Lesson | None:
    """Find the next upcoming lesson for the current day.

    Looks through the provided lessons for today's date (matching by weekday name)
    and returns the first lesson whose start_time is after the current time.

    Args:
        lessons: List of Lesson objects (should be sorted).
        now: Current datetime to compare against.

    Returns:
        The next Lesson for today, or None if no upcoming lessons remain.
    """
    if not lessons:
        return None

    # Get the current weekday name in English
    current_day_name = now.strftime("%A")
    current_time_str = now.strftime("%H:%M")

    # Filter lessons for today and find the next one
    for lesson in lessons:
        if lesson.day == current_day_name and lesson.start_time > current_time_str:
            return lesson

    return None


def _is_valid_time(time_str: str) -> bool:
    """Validate that a string is in HH:MM 24-hour format.

    Args:
        time_str: String to validate.

    Returns:
        True if the string is a valid HH:MM time.
    """
    if not isinstance(time_str, str):
        return False

    time_str = time_str.strip()

    if len(time_str) != 5 or time_str[2] != ":":
        return False

    try:
        hours = int(time_str[:2])
        minutes = int(time_str[3:])
    except ValueError:
        return False

    return 0 <= hours <= 23 and 0 <= minutes <= 59
