# Implementation Plan: Setup Flow Improvements

## Overview

Update the HAiServ config flow to improve the setup experience: add a welcome description, fix field label capitalization, add a success message, update the entry title format to include the URL, and add duplicate-entry detection via `unique_id`.

## Tasks

- [x] 1. Update strings.json with new UI text
  - [x] 1.1 Add welcome description and update field labels
    - Replace `config.step.user.description` with the two-paragraph welcome text (welcome + iServ account requirement)
    - Update `config.step.user.data.url` from "Server URL" to "URL"
    - Confirm `username` and `password` labels remain "Username" and "Password"
    - Add `config.create_entry.default` key with the success message: "Successfully connected to {url}. Your credentials have been validated."
    - _Requirements: 1.4, 2.1, 2.2, 2.3, 3.1, 3.2_

- [x] 2. Update config_flow.py with new title format and duplicate detection
  - [x] 2.1 Update entry title format
    - Change `async_create_entry` title from `f"iServ ({username})"` to `f"iServ ({username} @ {url})"`
    - _Requirements: 4.1, 4.2_

  - [x] 2.2 Add unique_id-based duplicate detection
    - After trimming inputs but before calling `authenticate()`, set `unique_id` to `f"{username}_{url}"`
    - Call `self._abort_if_unique_id_configured()` to prevent duplicate entries
    - Add `await self.async_set_unique_id(f"{username}_{url}")` (requires making the stub support this)
    - _Requirements: 4.3_

- [x] 3. Checkpoint - Verify strings.json and config_flow.py changes
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Update and add tests for the new behavior
  - [x] 4.1 Update existing config flow tests for new title format
    - Update `test_successful_flow_creates_entry` assertion from `"iServ (student)"` to `"iServ (student @ https://school.iserv.de)"`
    - Update the `_FakeConfigFlow` stub to support `async_set_unique_id` and `_abort_if_unique_id_configured`
    - _Requirements: 4.1, 4.2_

  - [x] 4.2 Add test for duplicate entry detection
    - Test that when `unique_id` is already configured, the flow aborts with `already_configured`
    - Mock `_abort_if_unique_id_configured` to raise an abort exception
    - _Requirements: 4.3_

  - [x] 4.3 Add test for strings.json structure validation
    - Verify `config.step.user.description` key exists and contains both paragraphs
    - Verify `config.step.user.data.url` equals "URL"
    - Verify `config.step.user.data.username` equals "Username"
    - Verify `config.step.user.data.password` equals "Password"
    - Verify `config.create_entry.default` key exists and contains "{url}" placeholder
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2_

  - [x] 4.4 Add integration test for full happy-path with new title
    - Mock authentication, submit valid credentials, verify entry title matches new format
    - Verify data dict contains trimmed url, username, and password
    - _Requirements: 4.1, 4.2_

- [x] 5. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The design explicitly states property-based testing does not apply here (static text + simple string formatting)
- Existing tests in `tests/test_config_flow.py` use a `_FakeConfigFlow` stub that must be extended to support `async_set_unique_id` and `_abort_if_unique_id_configured`
- The `strings.json` description uses `\n\n` to separate paragraphs per Home Assistant conventions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 3, "tasks": ["4.4"] }
  ]
}
```
