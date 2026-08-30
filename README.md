# HAiServ

HAiServ is a custom [Home Assistant](https://www.home-assistant.io/) integration for retrieving timetable data from an [IServ](https://iserv.de/) server. It authenticates with an existing IServ account, fetches the current and following week's timetables, and exposes the next lesson and full timetable data as sensors.

> [!IMPORTANT]
> HAiServ is an early-stage, unofficial project and is not affiliated with or endorsed by IServ GmbH. IServ installations can differ, so compatibility with every server is not guaranteed.

## Features

- UI-based setup through Home Assistant's integration flow
- HTTPS URL validation before login
- Session-based IServ authentication
- Automatic re-authentication after an expired session
- Hourly timetable refresh
- Sensor state showing the next lesson for the current day
- Structured lesson data and a Markdown timetable in sensor attributes
- Retention of previously fetched data during temporary connection failures

## Requirements

- A working Home Assistant installation
- An IServ account with access to timetable data
- The HTTPS base URL of the IServ server, for example `https://school.iserv.de`

## Local CLI debugger

The repository also includes a standalone debugger at `cli.py`. It uses the
same API client and parser as the Home Assistant integration, but does not
require Home Assistant to be running.

From the repository root:

```bash
python cli.py --url https://school.iserv.de --username student
```

The password is requested through a hidden prompt. For non-interactive use,
set `ISERV_PASSWORD` instead:

```bash
ISERV_PASSWORD='your-password' python cli.py \
  --url https://school.iserv.de \
  --username student \
  --both
```

Useful options:

- `--week current|next` — fetch one week (default: `current`)
- `--both` — print the current and following week
- `--raw` — print the unparsed server response for debugging
- `--password` — pass the password directly; this may be visible in shell
  history or process listings and is therefore not recommended

The normal output is a Markdown timetable with lesson count and ISO week
number. Exit code `0` indicates success; `2` means invalid arguments, `3`
means authentication failure, and `4` means a connection or network failure.
Only use this tool on a trusted machine and never paste passwords or raw
responses containing private school data into public issue reports.

## Installation

### Manual installation

1. Copy `custom_components/haiserv` into the `custom_components` directory of your Home Assistant configuration:

   ```text
   <config>/custom_components/haiserv/
   ```

2. Restart Home Assistant.
3. Open **Settings → Devices & services**.
4. Select **Add integration** and search for **HAiServ**.

## Configuration

Enter the following values in the setup dialog:

- **URL:** HTTPS base URL of the IServ server
- **Username:** IServ username
- **Password:** IServ password

HAiServ validates the connection before creating the Home Assistant config entry. Accounts are distinguished by username and server URL.

## Entity

The integration creates two sensors:

- **iServ Timetable** — the current calendar week's timetable and next lesson
- **iServ Next Week Timetable** — the following Monday-to-Friday timetable

### State

The state is one of:

- `<subject> <start time>-<end time>` for the next lesson today
- `No upcoming lessons` when no later lesson exists today
- `No lessons` when no timetable data is available

Example:

```text
Mathematics 08:00-08:45
```

### Attributes

| Attribute | Description |
| --- | --- |
| `lessons` | List of lessons containing `day`, `start_time`, `end_time`, `subject`, and `room` |
| `timetable_table` | Full timetable formatted as a Markdown table |
| `last_updated` | ISO 8601 timestamp generated when the attributes are read |

The `timetable_table` attribute can be rendered with a Home Assistant Markdown card:

```yaml
type: markdown
content: "{{ state_attr('sensor.iserv_timetable', 'timetable_table') }}"
```

The actual entity ID may differ if Home Assistant has assigned another name.

The next-week sensor has the same `lessons` and `timetable_table` attributes,
so it can be rendered with a separate Markdown card:

```yaml
type: markdown
content: "{{ state_attr('sensor.iserv_next_week_timetable', 'timetable_table') }}"
```

Its state is the number of lessons in the following week, or `No lessons` if
the server returned an empty timetable.

## Updating

For a manual installation, replace `<config>/custom_components/haiserv` with the files from the newer release or revision and restart Home Assistant.

## Troubleshooting

- **Invalid URL:** The URL must use `https://` and include a valid hostname.
- **Authentication failed:** Verify the username and password by signing in to the same IServ server in a browser.
- **Cannot connect:** Verify the server URL and Home Assistant's network access.
- **No lessons:** Confirm that the account can access timetable data and that the server returns the expected timetable format.

Home Assistant logs for `custom_components.haiserv` can provide additional details. Passwords are not intentionally written to the integration's logs.

## Development

The repository contains unit, integration, and property-based tests under `tests/`.

A local development environment needs the dependencies imported by the test suite, including Home Assistant, pytest, pytest-asyncio, Hypothesis, aioresponses, aiohttp, and voluptuous. Run the tests from the repository root:

```bash
python -m pytest
```

Generated test caches such as `.hypothesis/` and `.pytest_cache/` are intentionally excluded from version control.

## Security

Do not include real credentials in bug reports, logs, fixtures, or commits. If you discover a security issue, contact the repository owner privately rather than opening a public issue containing sensitive data.

## License

This project is licensed under the [MIT License](LICENSE).
