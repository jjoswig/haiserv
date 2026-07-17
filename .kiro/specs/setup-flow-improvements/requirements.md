# Requirements Document

## Introduction

This feature improves the HAiServ config flow setup experience in Home Assistant. Changes include a welcome description above the form fields, corrected field label capitalization, an enhanced success message confirming connection, and an updated integration entry title that includes both username and URL.

## Glossary

- **Config_Flow**: The Home Assistant setup wizard that guides users through configuring an integration via form steps.
- **Setup_Form**: The user-facing form displayed during the `user` step of the Config_Flow, containing input fields for URL, username, and password.
- **Integration_Entry**: The record shown under "Integration entries" in the Home Assistant integration details page after successful setup.
- **strings.json**: The localization file that defines all UI-visible text for the integration (titles, descriptions, labels, errors).
- **Entry_Title**: The title string shown for an Integration_Entry, set at creation time via `async_create_entry(title=...)`.

## Requirements

### Requirement 1: Welcome Description Above Form Fields

**User Story:** As a user setting up HAiServ, I want to see a welcoming description above the input fields, so that I understand what the integration does and what prerequisites are needed.

#### Acceptance Criteria

1. WHEN the Setup_Form is displayed, THE Config_Flow SHALL show a description text above all input fields, including when the form is re-displayed after validation errors.
2. THE Config_Flow description SHALL contain a first paragraph that welcomes the user to HAiServ and explains that HAiServ is a Home Assistant custom integration supporting retrieval of timetables and files for students and classes using iServ.
3. THE Config_Flow description SHALL contain a second paragraph, separated from the first by a blank line, stating that an iServ account is necessary to use the integration and that users should contact their class teacher if they do not have one.
4. THE Config_Flow description text SHALL be defined in the strings.json localization file under the key path `config.step.user.description`.

### Requirement 2: Input Field Label Capitalization

**User Story:** As a user, I want the input field labels to use consistent and correct capitalization, so that the form looks polished and professional.

#### Acceptance Criteria

1. THE Setup_Form SHALL display the URL field label as the exact string "URL".
2. THE Setup_Form SHALL display the username field label as the exact string "Username".
3. THE Setup_Form SHALL display the password field label as the exact string "Password".
4. WHEN the Setup_Form is rendered, THE Setup_Form SHALL display exactly 3 input field labels: "URL", "Username", and "Password", in that order.

### Requirement 3: Success Message With Connection Confirmation

**User Story:** As a user, I want the success message to confirm that the connection was established, so that I know the credentials were validated and the server is reachable.

#### Acceptance Criteria

1. WHEN authentication succeeds, THE Config_Flow SHALL display a success message that includes the text confirming that the connection to the iServ server was established and credentials were validated.
2. THE Config_Flow success message SHALL include the server URL that was connected to, so the user can confirm the correct server was reached.
3. IF the `create_entry` message key is missing from strings.json, THEN THE Config_Flow SHALL fall back to a default success message that still indicates successful connection.

### Requirement 4: Integration Entry Title Includes URL

**User Story:** As a user, I want the integration entry title to show both the username and the URL, so that I can distinguish between multiple iServ accounts on different servers.

#### Acceptance Criteria

1. WHEN a config entry is created, THE Config_Flow SHALL set the Entry_Title using the trimmed username and trimmed URL values provided by the user during configuration.
2. THE Entry_Title SHALL follow the format `iServ ({username} @ {url})`, where `{username}` is the trimmed username and `{url}` is the trimmed URL exactly as entered by the user (including scheme if provided).
3. WHEN a config entry already exists with the same username and URL combination, THE Config_Flow SHALL abort the flow and indicate that the account is already configured.
