# Implementation Plan: iServ Home Assistant Integration

## Overview

This plan implements a Home Assistant custom integration that authenticates with iServ, fetches the student timetable on a 60-minute cycle using a DataUpdateCoordinator, and exposes it as a sensor entity with structured attributes and a Markdown table for dashboard display. Tasks are ordered to build foundational components first (constants, API client, parser), then layer the coordinator, sensor, and config flow on top, finishing with integration wiring and tests.

## Tasks

- [x] 1. Set up project structure, constants, and manifest
  - [x] 1.1 Create the custom component directory and manifest.json
    - Create `custom_components/iserv/` directory structure
    - Create `manifest.json` with domain "iserv", name, version, documentation URL, codeowners, dependencies including aiohttp, and config_flow set to true
    - Create `const.py` with DOMAIN, DEFAULT_UPDATE_INTERVAL (60), CONNECTION_TIMEOUT (10), REQUEST_TIMEOUT (30), MAX_CONSECUTIVE_FAILURES (3), and DAY_ORDER mapping
    - _Requirements: 6.1, 6.3, 6.4_

  - [x] 1.2 Create the Lesson data model and parser module
    - Create `parser.py` with the `Lesson` dataclass (day, start_time, end_time, subject, room)
    - Implement `parse_timetable(raw_data, locale)` to extract lessons from iServ response, defaulting missing subject/room to empty string, skipping entries missing day/time
    - Implement `sort_lessons(lessons)` to sort by DAY_ORDER then start_time ascending
    - Implement `format_markdown_table(lessons)` producing pipe-and-dash Markdown with Day, Time, Subject, Room columns; Time formatted "HH:MM - HH:MM"; return empty string for empty list
    - Implement `get_next_lesson(lessons, now)` returning the next lesson for the current day or None
    - _Requirements: 2.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3_

  - [x] 1.3 Write property tests for parser (Properties 2, 3, 5)
    - **Property 2: Timetable Parsing Round-Trip** — generate random lesson structures, serialize to iServ format, parse back, assert field-level equivalence with HH:MM times and empty-string defaults
    - **Property 3: Lesson Sorting Invariant** — generate random unsorted lesson lists, assert sorted output respects day order Mon–Fri and ascending start_time within each day
    - **Property 5: Markdown Table Structure** — generate non-empty lesson lists, assert output contains header row with Day|Time|Subject|Room, separator row, one data row per lesson with "HH:MM - HH:MM" time format
    - Each test tagged: `# Feature: iserv-homeassistant-integration, Property {N}: {title}`
    - Minimum 100 iterations per property
    - _Requirements: 4.2, 5.1, 5.2_
    - **Validates: Requirements 2.3, 4.1, 4.2, 4.3, 4.5, 4.6, 5.1, 5.2**

- [x] 2. Implement the iServ API client
  - [x] 2.1 Create the IServClient class in api.py
    - Implement `__init__` accepting aiohttp.ClientSession, base_url, username, password
    - Implement `authenticate()` performing form POST login to iServ, storing session cookies, returning True on success; raise on HTTP 401/403
    - Implement `fetch_timetable(week)` fetching the timetable page for a given calendar week with REQUEST_TIMEOUT; handle session expiry by re-authenticating once
    - Implement `is_authenticated` property checking current session validity
    - Add URL validation helper that checks "https://" prefix and valid host component
    - _Requirements: 1.2, 1.3, 2.1, 2.4, 2.5, 2.6_

  - [x] 2.2 Write property test for URL validation (Property 1)
    - **Property 1: URL Validation Correctness** — generate random strings including valid https URLs and invalid inputs, assert function accepts iff string starts with "https://" and has a valid host
    - Tagged: `# Feature: iserv-homeassistant-integration, Property 1: URL Validation Correctness`
    - Minimum 100 iterations
    - **Validates: Requirements 1.2**

  - [x] 2.3 Write unit tests for IServClient
    - Mock aiohttp responses for successful login, failed login (401/403), connection timeout, successful timetable fetch, session expiry + re-auth
    - _Requirements: 8.5_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement the DataUpdateCoordinator
  - [x] 4.1 Create IServCoordinator in coordinator.py
    - Subclass `DataUpdateCoordinator[list[Lesson]]` with 60-minute update interval
    - Implement `_async_update_data`: call `client.fetch_timetable()`, parse with `parse_timetable`, sort with `sort_lessons`
    - Handle auth expiry: re-authenticate once, retry fetch; on second failure raise `UpdateFailed`
    - Handle network errors / timeouts: raise `UpdateFailed` to let coordinator handle retry
    - Track consecutive failure count; log warnings with count on failure
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 2.6, 7.3, 7.6_

  - [x] 4.2 Write property tests for coordinator error handling (Properties 6, 7)
    - **Property 6: Data Retention on Fetch Failure** — generate random prior lesson data, simulate fetch failure, assert sensor data unchanged
    - **Property 7: Availability State Machine** — generate random sequences of success/failure results, assert unavailable iff last ≥3 consecutive failures, any success resets counter
    - Each test tagged: `# Feature: iserv-homeassistant-integration, Property {N}: {title}`
    - Minimum 100 iterations per property
    - **Validates: Requirements 7.1, 7.4, 7.5**

  - [x] 4.3 Write unit tests for coordinator lifecycle
    - Test 60-minute update interval configuration
    - Test session re-authentication on expiry
    - Test consecutive failure counter increments and resets
    - Test logging behavior on failures
    - _Requirements: 8.4_

- [x] 5. Implement the sensor entity
  - [x] 5.1 Create IServTimetableSensor in sensor.py
    - Subclass `CoordinatorEntity[IServCoordinator]` and `SensorEntity`
    - Implement `native_value`: use `get_next_lesson` to return "{subject} {start_time}-{end_time}" (max 255 chars), "No upcoming lessons" if none today, "No lessons" if empty timetable
    - Implement `extra_state_attributes`: return dict with "lessons" (list of dicts), "timetable_table" (markdown string from `format_markdown_table`), "last_updated" (ISO 8601 timestamp)
    - Implement `available` property: return False if consecutive failures >= MAX_CONSECUTIVE_FAILURES and no prior data
    - Set entity name to "iServ Timetable"
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.3, 5.4, 7.1, 7.2, 7.4, 7.5_

  - [x] 5.2 Write property test for sensor state format (Property 4)
    - **Property 4: Next Lesson State Format** — generate non-empty lesson lists and random datetimes, assert state matches "{subject} {start_time}-{end_time}" (≤255 chars) or "No upcoming lessons"
    - Tagged: `# Feature: iserv-homeassistant-integration, Property 4: Next Lesson State Format`
    - Minimum 100 iterations
    - **Validates: Requirements 3.2, 3.3**

  - [x] 5.3 Write unit tests for sensor entity
    - Test state with upcoming lesson, no upcoming lessons, empty timetable, unavailable state
    - Test attributes contain correct lessons list, markdown table, last_updated timestamp
    - Test data retention on failure (previous data preserved)
    - _Requirements: 8.3, 8.4_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement config flow and integration setup
  - [x] 7.1 Create the ConfigFlow in config_flow.py
    - Implement `async_step_user` handling user-initiated configuration
    - Validate all three fields (url, username, password) are non-empty
    - Validate URL starts with "https://" and is well-formed
    - Attempt login using IServClient; on success create config entry
    - On HTTP 401/403: show "Authentication failed" error, allow re-entry
    - On connection timeout/refused: show "Cannot connect" error, allow re-entry
    - Create `strings.json` with UI strings for the config flow steps and errors
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 6.2, 6.5_

  - [x] 7.2 Create integration setup in __init__.py
    - Implement `async_setup_entry`: create aiohttp session, instantiate IServClient, create IServCoordinator, trigger first refresh, store coordinator in hass.data, forward sensor platform setup
    - Implement `async_unload_entry`: unload platforms, clean up hass.data
    - _Requirements: 6.1, 6.5, 7.3_

  - [x] 7.3 Write unit tests for config flow
    - Test successful flow with valid credentials creates entry
    - Test invalid credentials shows authentication error
    - Test unreachable URL shows connection error
    - Test empty fields show validation error
    - _Requirements: 8.2_

- [x] 8. Wire everything together and create test infrastructure
  - [x] 8.1 Create test conftest.py and shared fixtures
    - Create `tests/conftest.py` with shared fixtures: mock IServClient, sample Lesson data, mock aiohttp session, mock coordinator
    - Create `tests/test_properties.py` collecting all 7 property tests in one module
    - Ensure `pytest` runs from repo root with installed dependencies (pytest, pytest-asyncio, aioresponses, hypothesis)
    - _Requirements: 8.5, 8.6_

  - [x] 8.2 Write integration tests for end-to-end flow
    - Test config entry creation → coordinator start → sensor entity with correct state and attributes
    - Mock HTTP responses for full lifecycle: login → fetch timetable → parse → sensor update
    - _Requirements: 8.1_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (7 properties total)
- Unit tests validate specific examples and edge cases
- All HTTP interactions are mocked — no network access or running iServ instance needed
- The integration uses Python with aiohttp, following Home Assistant custom component conventions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "2.3"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "7.1", "7.2"] },
    { "id": 6, "tasks": ["7.3", "8.1"] },
    { "id": 7, "tasks": ["8.2"] }
  ]
}
```
