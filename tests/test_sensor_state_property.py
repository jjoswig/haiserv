"""Property-based tests for the iServ sensor state format.

Tests Property 4 from the design document using Hypothesis.

For any non-empty list of lessons and any current datetime, the sensor state
value SHALL either be a string matching format "{subject} {start_time}-{end_time}"
not exceeding 255 characters (when an upcoming lesson exists for the current day),
or the string "No upcoming lessons" (when no lessons remain for the current day).

Validates: Requirements 3.2, 3.3
"""

from __future__ import annotations

import re
from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.iserv.const import DAY_ORDER
from custom_components.iserv.parser import Lesson, get_next_lesson

# --- Strategies ---

VALID_DAYS = list(DAY_ORDER.keys())

# Strategy for valid HH:MM time strings
valid_time_st = st.builds(
    lambda h, m: f"{h:02d}:{m:02d}",
    st.integers(min_value=0, max_value=23),
    st.integers(min_value=0, max_value=59),
)

# Strategy for subject/room strings (printable text, no pipes/newlines)
field_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        whitelist_characters="-_",
    ),
    min_size=0,
    max_size=30,
)

# Strategy for a single Lesson object
lesson_st = st.builds(
    Lesson,
    day=st.sampled_from(VALID_DAYS),
    start_time=valid_time_st,
    end_time=valid_time_st,
    subject=field_text_st,
    room=field_text_st,
)

# Strategy for datetimes (covering all weekdays)
datetime_st = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)


def compute_sensor_state(lessons: list[Lesson], now: datetime) -> str:
    """Replicate the sensor's native_value logic for testing.

    This mirrors the IServTimetableSensor.native_value property:
    - If lessons is empty -> "No lessons"
    - If get_next_lesson returns None -> "No upcoming lessons"
    - Otherwise -> f"{subject} {start_time}-{end_time}" truncated to 255 chars
    """
    if not lessons:
        return "No lessons"

    next_lesson = get_next_lesson(lessons, now)

    if next_lesson is None:
        return "No upcoming lessons"

    state = f"{next_lesson.subject} {next_lesson.start_time}-{next_lesson.end_time}"
    return state[:255]


# --- Property 4: Next Lesson State Format ---
# Feature: iserv-homeassistant-integration, Property 4: Next Lesson State Format


@settings(max_examples=100)
@given(
    lessons=st.lists(lesson_st, min_size=1, max_size=20),
    now=datetime_st,
)
def test_property_4_next_lesson_state_format(
    lessons: list[Lesson], now: datetime
) -> None:
    """Property 4: Next Lesson State Format.

    For any non-empty list of lessons and any current datetime, the sensor state
    value SHALL either be:
    1. A string matching "{subject} {start_time}-{end_time}" (≤255 chars), OR
    2. The string "No upcoming lessons"

    Validates: Requirements 3.2, 3.3
    """
    state = compute_sensor_state(lessons, now)

    # State must be one of two valid forms
    if state == "No upcoming lessons":
        # Valid: no lessons remain for the current day
        # Verify that get_next_lesson indeed returns None
        assert get_next_lesson(lessons, now) is None
    else:
        # Valid: must match "{subject} {start_time}-{end_time}" format
        # Must not exceed 255 characters
        assert len(state) <= 255

        # Must match the expected format: {subject} {start_time}-{end_time}
        # where subject can be empty (resulting in a leading space),
        # and start_time/end_time are HH:MM
        pattern = re.compile(r"^.* \d{2}:\d{2}-\d{2}:\d{2}$")
        assert pattern.match(state), (
            f"State '{state}' does not match expected format "
            f"'{{subject}} {{start_time}}-{{end_time}}'"
        )

        # Verify it corresponds to an actual lesson returned by get_next_lesson
        next_lesson = get_next_lesson(lessons, now)
        assert next_lesson is not None
        expected = f"{next_lesson.subject} {next_lesson.start_time}-{next_lesson.end_time}"
        assert state == expected[:255]


@settings(max_examples=100)
@given(
    lessons=st.lists(lesson_st, min_size=1, max_size=20),
    now=datetime_st,
)
def test_property_4_state_length_never_exceeds_255(
    lessons: list[Lesson], now: datetime
) -> None:
    """Property 4 supplementary: state value never exceeds 255 characters.

    Validates: Requirements 3.2
    """
    state = compute_sensor_state(lessons, now)
    assert len(state) <= 255


@settings(max_examples=100)
@given(
    lessons=st.lists(
        st.builds(
            Lesson,
            day=st.sampled_from(VALID_DAYS),
            start_time=valid_time_st,
            end_time=valid_time_st,
            subject=field_text_st,
            room=field_text_st,
        ),
        min_size=1,
        max_size=10,
    ),
    now=st.datetimes(
        min_value=datetime(2020, 1, 6),  # A Monday
        max_value=datetime(2020, 1, 10, 23, 59),  # Through Friday
    ),
)
def test_property_4_matching_day_produces_valid_state(
    lessons: list[Lesson], now: datetime
) -> None:
    """Property 4 supplementary: when lessons exist for the current weekday
    and time is before a lesson, state shows that lesson.

    Forces lessons to include the current weekday to increase coverage
    of the "upcoming lesson found" branch.

    Validates: Requirements 3.2, 3.3
    """
    # Force at least one lesson to be on the current weekday with a future time
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    # Add a lesson on the current day that's in the future (23:59 is almost always after now)
    future_lesson = Lesson(
        day=current_day,
        start_time="23:59",
        end_time="23:59",
        subject="FutureSubject",
        room="Room1",
    )
    lessons_with_future = lessons + [future_lesson]

    state = compute_sensor_state(lessons_with_future, now)

    # Since we added a future lesson for today, state should NOT be "No upcoming lessons"
    # unless the time is already 23:59 or later
    if current_time < "23:59":
        assert state != "No upcoming lessons"
        # It must match the format
        assert len(state) <= 255
        # Subject can be empty, so pattern uses .* (zero or more chars before space)
        pattern = re.compile(r"^.* \d{2}:\d{2}-\d{2}:\d{2}$")
        assert pattern.match(state), (
            f"State '{state}' does not match expected format"
        )
