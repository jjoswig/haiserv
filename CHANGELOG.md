# Changelog

## [0.1.0] — 2026-09-18

### Initial release

HAiServ is a Home Assistant custom integration for [iServ](https://iserv.de/) school platforms. It exposes timetable and parent letter data as Home Assistant sensor entities.

---

### Features

#### Timetable sensors

- **Current week timetable** (`sensor.iserv_timetable`) — state shows the next upcoming lesson as `{subject} {start}-{end}`; falls back to `No upcoming lessons` or `No lessons` when the week is empty.
- **Next week timetable** (`sensor.iserv_next_week_timetable`) — state shows total lesson count for the following week.
- Both sensors expose full attributes:
  - `lessons` — structured list of all lessons including cancellation status
  - `timetable_data` — raw JSON returned by the iServ API
  - `timetable_table` — pre-formatted Markdown table ready for Lovelace
  - `last_updated` — ISO 8601 timestamp of the last successful poll

#### Parent letter sensor

- **Parent letters** (`sensor.iserv_parent_letters`) — state shows `{N} unread` or `No unread letters`.
- Attributes include the full letter list (subject, sender, child, recipient, created_at, is_unread) sorted unread-first, plus `unread_count` and `total_count`.

#### Multi-generation timetable API support

Automatically detects which timetable endpoint the iServ instance exposes and selects the correct one:

1. DieSchulApp JSON API (`/iserv/public/timetable/current`) — newest installs
2. Timetable data endpoint (`/iserv/timetable/data`) — mid-generation installs
3. Legacy HTML endpoint (`/iserv/timetable`) — older installs

The detected endpoint is cached per session. Fallback proceeds automatically if the preferred endpoint becomes unavailable.

#### Session and authentication handling

- UI-based config flow — enter URL, username, and password; credentials are validated before the entry is created.
- Automatic session re-authentication on 401/403 responses.
- Entities remain available during transient failures by serving stale data. After 3 consecutive failures with no cached data the entity is marked unavailable.

#### Lovelace dashboard

A ready-made Lovelace dashboard (`dashboards/`) renders the timetable as a Markdown table with:
- Current week range in the heading
- Today's column header highlighted
- The currently active lesson row highlighted

#### Model Context Protocol (MCP) server

An optional MCP server (`mcp_server.py`) exposes the iServ timetable to LLM clients (e.g. Claude Desktop). Supports session reuse so the iServ login is performed once per process lifetime.

---

### Bug fixes

- Translation placeholder `{url}` in the config-flow success message is now correctly resolved.
- `_EndpointUnavailable` raised when all timetable endpoint variants are exhausted is now converted to `CannotConnect`, preventing an unhandled exception in the update coordinator.

---

### Requirements

- Home Assistant 2023.1 or newer
- `aiohttp` (declared as integration dependency)
- An iServ account with timetable access
