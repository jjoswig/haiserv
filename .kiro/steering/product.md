# HAiServ — Product Summary

HAiServ is a Home Assistant custom integration that connects to iServ, a German school portal platform. It retrieves student timetable data and exposes it as a sensor entity within Home Assistant.

## Core Functionality

- Authenticates against an iServ server using username/password credentials
- Fetches weekly timetable data via iServ's internal API
- Parses timetable into structured lesson objects (day, time, subject, room)
- Exposes a sensor showing the next upcoming lesson
- Provides full timetable as entity attributes (list of lessons + markdown table)
- Polls on a configurable interval (default: 60 minutes)

## Domain Context

- iServ is widely used in German schools for scheduling, file sharing, and communication
- Users configure the integration via a UI config flow (URL + credentials)
- The integration uses cloud polling (no local network access needed)
- Timetable data is organized by weekday (Monday–Friday) with time slots

## iServ API Reference

iServ has no official public API documentation. Endpoint paths, authentication flow, and response formats can be derived from these community projects:

- **IServAPI** (Python): https://pypi.org/project/IServAPI/ — Python wrapper covering login, timetable, mail, notifications, and file access. Useful reference for auth flow and endpoint naming conventions.
- **IServ (Node.js)**: https://github.com/dunklesToast/IServ — Node.js client with endpoints for exercises, mail, badges, notifications, and files. Shows session cookie handling and response parsing.
- **iserv (Python)**: https://github.com/RoRo160/iserv — Lightweight Python client. Covers authentication, timetable parsing, and file downloads.

### Known iServ Endpoints (derived from community projects)

| Purpose | Method | Path |
|---------|--------|------|
| Login | POST | `/iserv/auth/login` (form fields: `_username`, `_password`) |
| Timetable (raw) | GET | `/iserv/plan/show/raw` (query param: `week`) |
| Exercises | GET | `/iserv/exercise` |
| Mail (inbox) | GET | `/iserv/mail/api/message/list` |
| Notifications | GET | `/iserv/user/api/notifications` |
| Files | GET | `/iserv/file/-/Files/` |
| Badges | GET | `/iserv/user/api/badge` |

### Notes on Authentication

- iServ uses session-cookie-based authentication (form POST login, then cookies for subsequent requests).
- A successful login typically returns HTTP 302 redirect followed by 200.
- Sessions can expire; the client should detect 401/403 on data fetch and re-authenticate transparently.
- All iServ instances share the same endpoint structure — only the base URL differs per school.
