# Requirements Document

## Introduction

This document defines the requirements for a Home Assistant custom integration that connects to iServ, a school management platform. The integration retrieves the student timetable/schedule from iServ and presents it as a table entity in Home Assistant, allowing it to be displayed on the Home Assistant dashboard. The goal is a lean implementation focused on the timetable feature, eliminating the need to use the iServ app or web interface separately.

## Glossary

- **Integration**: A Home Assistant custom component that connects to an external service and exposes data as entities within Home Assistant.
- **iServ**: A school management web application used by students, parents, and teachers to manage timetables, absences, assignments, and communication.
- **Timetable**: A weekly schedule showing lessons, subjects, times, and rooms for a student.
- **Dashboard**: The Home Assistant user interface where entities and cards are displayed.
- **Sensor_Entity**: A Home Assistant entity that exposes state and attributes, used here to hold timetable data.
- **Config_Flow**: The Home Assistant mechanism for configuring integrations through the UI, collecting credentials and settings from the user.
- **Coordinator**: A Home Assistant DataUpdateCoordinator that manages periodic data fetching and caching from an external service.

## Requirements

### Requirement 1: Authentication with iServ

**User Story:** As a parent, I want the integration to authenticate with iServ using my credentials, so that it can access my son's timetable data.

#### Acceptance Criteria

1. WHEN the user sets up the integration, THE Config_Flow SHALL prompt for the iServ server URL, username, and password, requiring all three fields to be non-empty before allowing submission.
2. WHEN the user submits credentials, THE Config_Flow SHALL validate that the iServ server URL begins with "https://" and is a well-formed URL before attempting connection.
3. WHEN valid credentials are submitted, THE Integration SHALL authenticate with the iServ server within a connection timeout of 10 seconds and store the session.
4. IF the iServ server rejects the credentials with an authentication error, THEN THE Config_Flow SHALL display an error message indicating authentication failure and allow the user to re-enter credentials.
5. IF the iServ server URL does not respond within 10 seconds or the connection is refused, THEN THE Config_Flow SHALL display an error message indicating a connection failure and allow the user to re-enter the URL.
6. THE Integration SHALL store credentials securely using the Home Assistant config entry storage.

### Requirement 2: Timetable Data Retrieval

**User Story:** As a parent, I want the integration to fetch the current week's timetable from iServ, so that I can see my son's schedule without opening the iServ app.

#### Acceptance Criteria

1. WHEN the integration is loaded, THE Coordinator SHALL fetch the timetable for the current calendar week (Monday through Friday) from iServ.
2. THE Coordinator SHALL update the timetable data every 60 minutes.
3. WHEN the timetable is fetched, THE Coordinator SHALL parse the response into a structured list of lessons containing day, start time, end time, subject, and room.
4. IF the timetable fetch fails due to a network error or a response timeout exceeding 30 seconds, THEN THE Coordinator SHALL retry on the next scheduled update interval and log a warning.
5. IF the authentication session expires, THEN THE Coordinator SHALL re-authenticate and retry the timetable fetch once. IF re-authentication fails, THEN THE Coordinator SHALL log an error and retry both authentication and fetch on the next scheduled update interval.
6. THE Coordinator SHALL enforce a request timeout of 30 seconds for each timetable fetch attempt.

### Requirement 3: Timetable Sensor Entity

**User Story:** As a parent, I want the timetable exposed as a sensor entity in Home Assistant, so that I can display it on my dashboard.

#### Acceptance Criteria

1. THE Integration SHALL create a Sensor_Entity named "iServ Timetable" that represents the student's weekly timetable.
2. THE Sensor_Entity SHALL expose the current day's next upcoming lesson as its state value, formatted as "{subject} {start_time}-{end_time}" and not exceeding 255 characters.
3. IF no upcoming lessons remain for the current day, THEN THE Sensor_Entity SHALL set its state value to "No upcoming lessons".
4. THE Sensor_Entity SHALL expose the full weekly timetable as a list of lesson objects in an attribute named "lessons".
5. WHEN the timetable data is updated by the Coordinator, THE Sensor_Entity SHALL reflect the new data within the same update cycle.
6. THE Sensor_Entity SHALL include an attribute named "last_updated" containing the last successful update timestamp in ISO 8601 format.

### Requirement 4: Timetable Data Structure

**User Story:** As a parent, I want the timetable data structured in a consistent format, so that it can be rendered as a table on the dashboard.

#### Acceptance Criteria

1. THE Sensor_Entity SHALL expose timetable entries as a list of objects, each containing the fields: day, start_time, end_time, subject, and room.
2. THE Sensor_Entity SHALL sort timetable entries by day in Monday-through-Friday order, and then by start_time in ascending order.
3. WHEN a lesson has no room assigned in iServ, THE Sensor_Entity SHALL set the room field to an empty string.
4. THE Sensor_Entity SHALL represent day values as weekday names matching the Home Assistant system locale (e.g., "Monday", "Montag").
5. THE Sensor_Entity SHALL represent start_time and end_time in 24-hour HH:MM format (e.g., "08:30", "14:15").
6. WHEN a lesson has no subject assigned in iServ, THE Sensor_Entity SHALL set the subject field to an empty string.

### Requirement 5: Dashboard Display Compatibility

**User Story:** As a parent, I want to display the timetable as a table on the Home Assistant dashboard, so that I can quickly see the weekly schedule at a glance.

#### Acceptance Criteria

1. THE Sensor_Entity SHALL expose a "timetable_table" attribute containing the timetable formatted as a Markdown table string with columns: Day, Time, Subject, and Room, where Time combines start_time and end_time in "HH:MM - HH:MM" format.
2. THE Sensor_Entity SHALL format the "timetable_table" attribute using pipe-and-dash Markdown table syntax with a header row and separator row, rendering correctly when accessed via Jinja2 template in a Home Assistant Markdown card.
3. WHEN the timetable is empty for the current week, THE Sensor_Entity SHALL set its state to "No lessons", expose an empty list in the timetable attributes, and set the "timetable_table" attribute to an empty string.
4. WHEN the Coordinator updates timetable data, THE Sensor_Entity SHALL regenerate the "timetable_table" attribute to reflect the latest timetable entries.

### Requirement 6: Integration Setup and Configuration

**User Story:** As a parent, I want to set up the integration through the Home Assistant UI, so that I do not need to edit configuration files manually.

#### Acceptance Criteria

1. THE Integration SHALL be installable as a custom component by placing it in the Home Assistant `custom_components/iserv/` directory, and Home Assistant SHALL discover it upon restart without additional YAML configuration.
2. THE Integration SHALL provide a Config_Flow that can be initiated from the Home Assistant Integrations page by searching for the integration by name.
3. THE Integration SHALL include a manifest.json file specifying the integration domain, name, version, documentation URL, dependencies, codeowners, and the config_flow flag set to true.
4. THE Integration SHALL declare aiohttp as a dependency in its manifest.json for HTTP communication with iServ.
5. WHEN the Config_Flow is completed successfully, THE Integration SHALL load and create its Sensor_Entity without requiring a Home Assistant restart.

### Requirement 7: Error Handling and Resilience

**User Story:** As a parent, I want the integration to handle errors gracefully, so that temporary iServ outages do not break my Home Assistant setup.

#### Acceptance Criteria

1. IF a timetable fetch fails and previous timetable data exists, THEN THE Sensor_Entity SHALL retain the last successfully fetched timetable data and its attributes unchanged until a successful fetch occurs.
2. IF a timetable fetch fails and no previous timetable data exists, THEN THE Sensor_Entity SHALL set its state to "Unavailable" and expose an empty list in attributes.
3. IF the integration cannot connect to iServ on startup, THEN THE Integration SHALL log an error and retry on the next update interval as defined by the Coordinator schedule.
4. IF three consecutive timetable fetch attempts fail, THEN THE Integration SHALL set the Sensor_Entity availability to unavailable.
5. WHEN a timetable fetch succeeds after the Sensor_Entity was marked unavailable, THE Integration SHALL reset the consecutive failure counter to zero and restore the Sensor_Entity availability to available.
6. IF a timetable fetch fails with fewer than three consecutive failures, THEN THE Integration SHALL log a warning including the current consecutive failure count.

### Requirement 8: Testability

**User Story:** As a developer, I want automated tests for the integration, so that I can verify correctness without manual testing.

#### Acceptance Criteria

1. THE Integration SHALL include unit tests that verify timetable data parsing from a mocked iServ HTTP response containing at least one full week of lessons covering all fields (day, start_time, end_time, subject, room).
2. THE Integration SHALL include unit tests that verify the Config_Flow rejects invalid credentials and displays an authentication error, and rejects an unreachable server URL and displays a connection error.
3. THE Integration SHALL include unit tests that verify the Sensor_Entity exposes the next upcoming lesson as state, the full weekly timetable list in attributes, and the last-updated timestamp attribute, consistent with the data structure defined in Requirement 4.
4. THE Integration SHALL include tests that verify error handling by mocking a network failure and asserting that the Sensor_Entity retains previous data, and that availability is set to unavailable after 3 consecutive failed fetch attempts.
5. THE Integration SHALL use mocked HTTP responses (via aiohttp test utilities or unittest.mock) for all tests, requiring no network access or running iServ instance.
6. THE Integration SHALL be testable by running `pytest` from the repository root with no additional configuration beyond installing test dependencies.
