"""Property-based tests for the iServ timetable parser module.

Tests Properties 2, 3, and 5 from the design document using Hypothesis.

Validates: Requirements 2.3, 4.1, 4.2, 4.3, 4.5, 4.6, 5.1, 5.2
"""

from __future__ import annotations

import json
import re

from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.haiserv.const import DAY_ORDER
from custom_components.haiserv.parser import (
    Lesson,
    format_markdown_table,
    parse_timetable,
    sort_lessons,
)

# --- Strategies ---

VALID_DAYS = list(DAY_ORDER.keys())

# Strategy for valid HH:MM time strings
valid_time_st = st.builds(
    lambda h, m: f"{h:02d}:{m:02d}",
    st.integers(min_value=0, max_value=23),
    st.integers(min_value=0, max_value=59),
)

# Strategy for subject/room strings (printable text, no pipes/newlines to avoid markdown issues)
field_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        whitelist_characters="-_",
    ),
    min_size=0,
    max_size=30,
)

# Strategy for a single lesson dict (iServ JSON format)
lesson_dict_st = st.fixed_dictionaries(
    {
        "day": st.sampled_from(VALID_DAYS),
        "start_time": valid_time_st,
        "end_time": valid_time_st,
        "subject": field_text_st,
        "room": field_text_st,
        "canceled": st.booleans(),
    }
)

# Strategy for a single Lesson object
lesson_st = st.builds(
    Lesson,
    day=st.sampled_from(VALID_DAYS),
    start_time=valid_time_st,
    end_time=valid_time_st,
    subject=field_text_st,
    room=field_text_st,
    canceled=st.booleans(),
)


# --- Property 2: Timetable Parsing Round-Trip ---
# Feature: iserv-homeassistant-integration, Property 2: Timetable Parsing Round-Trip


@settings(max_examples=100)
@given(lessons=st.lists(lesson_dict_st, min_size=1, max_size=20))
def test_property_2_timetable_parsing_round_trip(lessons: list[dict]) -> None:
    """Property 2: Timetable Parsing Round-Trip.

    Generate random lesson structures, serialize to iServ JSON format,
    parse back with parse_timetable, and assert field-level equivalence
    with HH:MM times and empty-string defaults.

    Validates: Requirements 2.3, 4.1, 4.3, 4.5, 4.6
    """
    # Serialize to JSON (the iServ response format)
    raw_data = json.dumps(lessons)

    # Parse back using the parser
    parsed = parse_timetable(raw_data, locale="en")

    # The number of parsed lessons should match the input
    # (all generated lessons have valid required fields)
    assert len(parsed) == len(lessons)

    for original, parsed_lesson in zip(lessons, parsed):
        # Day is preserved
        assert parsed_lesson.day == original["day"].strip()

        # Times are in HH:MM format
        assert re.match(r"^\d{2}:\d{2}$", parsed_lesson.start_time)
        assert re.match(r"^\d{2}:\d{2}$", parsed_lesson.end_time)

        # Times match the original values
        assert parsed_lesson.start_time == original["start_time"].strip()
        assert parsed_lesson.end_time == original["end_time"].strip()

        # Subject defaults to empty string if empty/whitespace
        expected_subject = original["subject"].strip() if original["subject"].strip() else ""
        assert parsed_lesson.subject == expected_subject

        # Room defaults to empty string if empty/whitespace
        expected_room = original["room"].strip() if original["room"].strip() else ""
        assert parsed_lesson.room == expected_room

        assert parsed_lesson.canceled is original["canceled"]


@settings(max_examples=100)
@given(lessons=st.lists(lesson_dict_st, min_size=0, max_size=10))
def test_property_2_empty_fields_default_to_empty_string(lessons: list[dict]) -> None:
    """Property 2 supplementary: missing subject/room defaults to empty string.

    Validates: Requirements 4.3, 4.6
    """
    # Force some entries to have empty subject/room
    for lesson in lessons:
        lesson["subject"] = ""
        lesson["room"] = ""

    raw_data = json.dumps(lessons)
    parsed = parse_timetable(raw_data, locale="en")

    for parsed_lesson in parsed:
        # Both should default to empty string
        assert parsed_lesson.subject == ""
        assert parsed_lesson.room == ""


# --- Property 3: Lesson Sorting Invariant ---
# Feature: iserv-homeassistant-integration, Property 3: Lesson Sorting Invariant


@settings(max_examples=100)
@given(lessons=st.lists(lesson_st, min_size=1, max_size=30))
def test_property_3_lesson_sorting_invariant(lessons: list[Lesson]) -> None:
    """Property 3: Lesson Sorting Invariant.

    Generate random unsorted lesson lists, assert sorted output respects
    day order Mon-Fri and ascending start_time within each day.

    Validates: Requirements 4.2
    """
    sorted_lessons = sort_lessons(lessons)

    # The sorted list should have the same number of elements
    assert len(sorted_lessons) == len(lessons)

    # Verify ordering: for each consecutive pair, the sort key should be non-decreasing
    for i in range(len(sorted_lessons) - 1):
        current = sorted_lessons[i]
        next_lesson = sorted_lessons[i + 1]

        current_day_order = DAY_ORDER.get(current.day, 99)
        next_day_order = DAY_ORDER.get(next_lesson.day, 99)

        # Day order must be non-decreasing
        assert current_day_order <= next_day_order, (
            f"Day order violated: {current.day} (order {current_day_order}) "
            f"should come before {next_lesson.day} (order {next_day_order})"
        )

        # Within the same day, start_time must be non-decreasing
        if current_day_order == next_day_order:
            assert current.start_time <= next_lesson.start_time, (
                f"Time order violated on {current.day}: "
                f"{current.start_time} should come before {next_lesson.start_time}"
            )


@settings(max_examples=100)
@given(lessons=st.lists(lesson_st, min_size=0, max_size=20))
def test_property_3_sort_preserves_all_elements(lessons: list[Lesson]) -> None:
    """Property 3 supplementary: sorting preserves all elements (no data loss).

    Validates: Requirements 4.2
    """
    sorted_lessons = sort_lessons(lessons)

    # Same length
    assert len(sorted_lessons) == len(lessons)

    # Same multiset of lessons (sort is stable, content preserved)
    original_tuples = sorted(
        (l.day, l.start_time, l.end_time, l.subject, l.room, l.canceled)
        for l in lessons
    )
    sorted_tuples = sorted(
        (l.day, l.start_time, l.end_time, l.subject, l.room, l.canceled)
        for l in sorted_lessons
    )
    assert original_tuples == sorted_tuples


# --- Property 5: Markdown Table Structure ---
# Feature: iserv-homeassistant-integration, Property 5: Markdown Table Structure


@settings(max_examples=100)
@given(lessons=st.lists(lesson_st, min_size=1, max_size=20))
def test_property_5_markdown_table_structure(lessons: list[Lesson]) -> None:
    """Property 5: Markdown Table Structure.

    Generate non-empty lesson lists, assert output contains header row with
    Day|Time|Subject|Room|Canceled, separator row, one data row per lesson with
    "HH:MM - HH:MM" time format.

    Validates: Requirements 5.1, 5.2
    """
    result = format_markdown_table(lessons)

    # Result should be a non-empty string
    assert isinstance(result, str)
    assert len(result) > 0

    lines = result.split("\n")

    # Must have at least: header + separator + 1 data row
    assert len(lines) >= 3

    # First line: header row with Day, Time, Subject, Room
    header = lines[0]
    assert "Day" in header
    assert "Time" in header
    assert "Subject" in header
    assert "Room" in header
    assert "Canceled" in header
    assert header.startswith("|")
    assert header.endswith("|")

    # Second line: separator row with dashes
    separator = lines[1]
    assert "---" in separator
    assert separator.startswith("|")
    assert separator.endswith("|")

    # Data rows: one per lesson
    data_rows = lines[2:]
    assert len(data_rows) == len(lessons)

    # Each data row has the correct time format "HH:MM - HH:MM"
    time_pattern = re.compile(r"\d{2}:\d{2} - \d{2}:\d{2}")
    for i, row in enumerate(data_rows):
        # Row uses pipe-and-dash markdown syntax
        assert row.startswith("|")
        assert row.endswith("|")

        # Row contains a time in "HH:MM - HH:MM" format
        assert time_pattern.search(row), (
            f"Data row {i} missing HH:MM - HH:MM time format: {row}"
        )

        # Row contains the lesson's time values
        lesson = lessons[i]
        expected_time = f"{lesson.start_time} - {lesson.end_time}"
        assert expected_time in row, (
            f"Data row {i} missing expected time '{expected_time}': {row}"
        )


@settings(max_examples=100)
@given(lessons=st.lists(lesson_st, min_size=1, max_size=15))
def test_property_5_markdown_table_row_count(lessons: list[Lesson]) -> None:
    """Property 5 supplementary: table has exactly header + separator + N data rows.

    Validates: Requirements 5.1, 5.2
    """
    result = format_markdown_table(lessons)
    lines = result.split("\n")

    # Exactly 2 (header + separator) + len(lessons) data rows
    assert len(lines) == 2 + len(lessons)
