"""Aggregated property-based test module for the iServ integration.

Collects all 7 property tests from their individual modules into a single
entry point. Running this file executes the complete property test suite.

Properties:
- Property 1: URL Validation Correctness (test_url_validation_property.py)
- Property 2: Timetable Parsing Round-Trip (test_parser_properties.py)
- Property 3: Lesson Sorting Invariant (test_parser_properties.py)
- Property 4: Next Lesson State Format (test_sensor_state_property.py)
- Property 5: Markdown Table Structure (test_parser_properties.py)
- Property 6: Data Retention on Fetch Failure (test_coordinator_properties.py)
- Property 7: Availability State Machine (test_coordinator_properties.py)

Validates: Requirements 8.5, 8.6
"""

# Property 1: URL Validation Correctness
from tests.test_url_validation_property import (
    test_validate_url_accepts_valid_https_urls,
    test_validate_url_rejects_invalid_inputs,
    test_validate_url_matches_reference_for_arbitrary_strings,
)

# Property 2: Timetable Parsing Round-Trip
from tests.test_parser_properties import (
    test_property_2_timetable_parsing_round_trip,
    test_property_2_empty_fields_default_to_empty_string,
)

# Property 3: Lesson Sorting Invariant
from tests.test_parser_properties import (
    test_property_3_lesson_sorting_invariant,
    test_property_3_sort_preserves_all_elements,
)

# Property 4: Next Lesson State Format
from tests.test_sensor_state_property import (
    test_property_4_next_lesson_state_format,
    test_property_4_state_length_never_exceeds_255,
    test_property_4_matching_day_produces_valid_state,
)

# Property 5: Markdown Table Structure
from tests.test_parser_properties import (
    test_property_5_markdown_table_structure,
    test_property_5_markdown_table_row_count,
)

# Property 6: Data Retention on Fetch Failure
from tests.test_coordinator_properties import (
    test_property_6_data_retention_on_fetch_failure,
    test_property_6_data_updates_on_success,
)

# Property 7: Availability State Machine
from tests.test_coordinator_properties import (
    test_property_7_availability_state_machine,
    test_property_7_threshold_boundary,
    test_property_7_success_resets_counter,
)
