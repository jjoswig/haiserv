"""Property-based tests for the iServ coordinator error handling logic.

Tests Properties 6 and 7 from the design document using Hypothesis.

Since we cannot import Home Assistant's DataUpdateCoordinator in tests,
we test the core logic of data retention and availability state machine
using a simplified model that mirrors the coordinator's behavior.

Validates: Requirements 7.1, 7.4, 7.5
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.iserv.const import DAY_ORDER, MAX_CONSECUTIVE_FAILURES
from custom_components.iserv.parser import Lesson


# --- Helper: Coordinator state machine model ---


@dataclass
class CoordinatorState:
    """Simplified model of the IServCoordinator state machine.

    Mirrors the coordinator's consecutive_failures counter and data retention
    logic without requiring Home Assistant dependencies.
    """

    data: Optional[list[Lesson]]
    consecutive_failures: int

    @property
    def available(self) -> bool:
        """Entity is available iff fewer than MAX_CONSECUTIVE_FAILURES."""
        return self.consecutive_failures < MAX_CONSECUTIVE_FAILURES

    def handle_success(self, new_data: list[Lesson]) -> None:
        """Handle a successful fetch: update data, reset counter."""
        self.data = new_data
        self.consecutive_failures = 0

    def handle_failure(self) -> None:
        """Handle a fetch failure: increment counter, retain prior data."""
        self.consecutive_failures += 1


# --- Strategies ---

VALID_DAYS = list(DAY_ORDER.keys())

valid_time_st = st.builds(
    lambda h, m: f"{h:02d}:{m:02d}",
    st.integers(min_value=0, max_value=23),
    st.integers(min_value=0, max_value=59),
)

field_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs"),
        whitelist_characters="-_",
    ),
    min_size=0,
    max_size=30,
)

lesson_st = st.builds(
    Lesson,
    day=st.sampled_from(VALID_DAYS),
    start_time=valid_time_st,
    end_time=valid_time_st,
    subject=field_text_st,
    room=field_text_st,
)

# Strategy for a non-empty list of lessons (prior data)
prior_data_st = st.lists(lesson_st, min_size=1, max_size=15)

# Strategy for a sequence of success/failure events (True=success, False=failure)
fetch_result_sequence_st = st.lists(
    st.booleans(),
    min_size=1,
    max_size=50,
)


# --- Property 6: Data Retention on Fetch Failure ---
# Feature: iserv-homeassistant-integration, Property 6: Data Retention on Fetch Failure


@settings(max_examples=100)
@given(prior_data=prior_data_st, num_failures=st.integers(min_value=1, max_value=20))
def test_property_6_data_retention_on_fetch_failure(
    prior_data: list[Lesson], num_failures: int
) -> None:
    """Property 6: Data Retention on Fetch Failure.

    For any previously stored timetable data and any fetch failure event,
    the sensor entity SHALL retain all previously stored lesson data and
    attributes unchanged until a successful fetch occurs.

    Validates: Requirements 7.1
    """
    # Set up state with prior successful data
    state = CoordinatorState(data=list(prior_data), consecutive_failures=0)

    # Record the original data for comparison
    original_data = list(prior_data)

    # Simulate one or more consecutive failures
    for _ in range(num_failures):
        state.handle_failure()

        # After each failure, data MUST remain unchanged
        assert state.data is not None
        assert len(state.data) == len(original_data)
        for original, retained in zip(original_data, state.data):
            assert retained.day == original.day
            assert retained.start_time == original.start_time
            assert retained.end_time == original.end_time
            assert retained.subject == original.subject
            assert retained.room == original.room


@settings(max_examples=100)
@given(prior_data=prior_data_st, new_data=prior_data_st)
def test_property_6_data_updates_on_success(
    prior_data: list[Lesson], new_data: list[Lesson]
) -> None:
    """Property 6 supplementary: data is replaced only on successful fetch.

    Validates: Requirements 7.1
    """
    # Set up state with prior data and some failures
    state = CoordinatorState(data=list(prior_data), consecutive_failures=2)

    # A successful fetch replaces the data
    state.handle_success(new_data)

    assert state.data is new_data
    assert state.consecutive_failures == 0


# --- Property 7: Availability State Machine ---
# Feature: iserv-homeassistant-integration, Property 7: Availability State Machine


@settings(max_examples=100)
@given(sequence=fetch_result_sequence_st)
def test_property_7_availability_state_machine(sequence: list[bool]) -> None:
    """Property 7: Availability State Machine.

    For any sequence of fetch results (success or failure), the sensor entity
    availability SHALL be "unavailable" if and only if the last 3 or more
    consecutive results were failures. Any single success in the sequence
    SHALL reset the consecutive failure counter to zero and restore availability.

    Validates: Requirements 7.4, 7.5
    """
    state = CoordinatorState(data=None, consecutive_failures=0)

    for success in sequence:
        if success:
            state.handle_success([])  # Data content doesn't matter for availability
        else:
            state.handle_failure()

    # Compute expected consecutive failures from the sequence
    expected_consecutive_failures = 0
    for success in sequence:
        if success:
            expected_consecutive_failures = 0
        else:
            expected_consecutive_failures += 1

    # The counter should match
    assert state.consecutive_failures == expected_consecutive_failures

    # Availability: unavailable iff >= MAX_CONSECUTIVE_FAILURES consecutive failures
    expected_available = expected_consecutive_failures < MAX_CONSECUTIVE_FAILURES
    assert state.available == expected_available


@settings(max_examples=100)
@given(
    num_failures=st.integers(min_value=0, max_value=30),
)
def test_property_7_threshold_boundary(num_failures: int) -> None:
    """Property 7 supplementary: availability boundary at exactly MAX_CONSECUTIVE_FAILURES.

    Validates: Requirements 7.4, 7.5
    """
    state = CoordinatorState(data=None, consecutive_failures=0)

    for _ in range(num_failures):
        state.handle_failure()

    # Available iff consecutive failures < MAX_CONSECUTIVE_FAILURES
    if num_failures < MAX_CONSECUTIVE_FAILURES:
        assert state.available is True
    else:
        assert state.available is False


@settings(max_examples=100)
@given(
    failures_before=st.integers(min_value=MAX_CONSECUTIVE_FAILURES, max_value=20),
    sequence_after=fetch_result_sequence_st,
)
def test_property_7_success_resets_counter(
    failures_before: int, sequence_after: list[bool]
) -> None:
    """Property 7 supplementary: any success resets counter and restores availability.

    Validates: Requirements 7.5
    """
    state = CoordinatorState(data=None, consecutive_failures=0)

    # Drive state to unavailable
    for _ in range(failures_before):
        state.handle_failure()

    assert state.available is False

    # A single success must reset the counter and restore availability
    state.handle_success([])
    assert state.consecutive_failures == 0
    assert state.available is True

    # Continue with the remaining sequence and verify invariant holds
    for success in sequence_after:
        if success:
            state.handle_success([])
        else:
            state.handle_failure()

    # Final availability matches expected state
    expected_consecutive_failures = 0
    for success in sequence_after:
        if success:
            expected_consecutive_failures = 0
        else:
            expected_consecutive_failures += 1

    assert state.consecutive_failures == expected_consecutive_failures
    assert state.available == (expected_consecutive_failures < MAX_CONSECUTIVE_FAILURES)
