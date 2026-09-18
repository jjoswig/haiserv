# HAiServ

HAiServ is a custom [Home Assistant](https://www.home-assistant.io/) integration for retrieving timetable data and Elternbrief (parent letters) from an [IServ](https://iserv.de/) server. It authenticates with an existing IServ account, fetches the current and following week's timetables, monitors the Elternbrief inbox, and exposes the data as sensors.

> [!IMPORTANT]
> HAiServ is an early-stage, unofficial project and is not affiliated with or endorsed by IServ GmbH. IServ installations can differ, so compatibility with every server is not guaranteed.

## Support this project

As an independent software developer, I'm passionate about building useful tools and making them freely available to the community. Behind every project, there's more than just development work: servers, domains, APIs, hosting — the running costs add up quickly. I fund all of this out of my own pocket because I believe in the value these projects provide.

If you find my work useful or it saves you some time, I'd genuinely appreciate a coffee ☕ — it keeps me going and guarantees you some good karma. The universe doesn't forget these things! 😄

[![Buy Me A Coffee](https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=&slug=jjoswig&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff)](https://www.buymeacoffee.com/jjoswig)

## Features

- UI-based setup through Home Assistant's integration flow
- HTTPS URL validation before login
- Session-based IServ authentication
- Automatic re-authentication after an expired session
- Hourly timetable refresh
- Sensor state showing the next lesson for the current day
- Structured lesson data and a Markdown timetable in sensor attributes
- Elternbrief (parent letter) inbox monitoring with unread count
- Retention of previously fetched data during temporary connection failures

## Requirements

- A working Home Assistant installation
- An IServ account with access to timetable and Elternbrief data
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

Useful timetable options:

- `--week current|next` — fetch one week (default: `current`)
- `--both` — print the current and following week
- `--raw` — print only the exact, unparsed server response for debugging
- `--verbose` — print safe request/response diagnostics to stderr, including
  status, redirect paths, content types, cookie names, and response sizes
- `--password` — pass the password directly; this may be visible in shell
  history or process listings and is therefore not recommended

The normal output contains a Markdown timetable and the complete, structured
JSON response with lesson count and ISO week number.

### Elternbrief subcommand

List and read parent letters from the command line using the `elternbrief`
subcommand (also available as `parentletter`):

```bash
# List all letters
python cli.py --url https://school.iserv.de --username student elternbrief

# Read the full text of one letter
python cli.py --url https://school.iserv.de --username student \
  elternbrief --read LETTER_UUID/CHILD_UUID

# Mark a letter as read
python cli.py --url https://school.iserv.de --username student \
  elternbrief --mark-read LETTER_UUID/CHILD_UUID
```

The list output is a table with columns for unread status, date, sender, child,
and subject. UUIDs appear in the sensor attributes and can be copied from there.

Options:

- `--read LETTER_UUID/CHILD_UUID` — fetch and print the full letter text
- `--mark-read LETTER_UUID/CHILD_UUID` — submit the mark-as-read form
- `--verbose` — print safe diagnostics to stderr

Exit code `0` indicates success; `2` means invalid arguments, `3`
means authentication failure, and `4` means a connection or network failure.

### MCP server subcommand

The `mcp` subcommand starts an [MCP](https://modelcontextprotocol.io/) server
so any MCP-compatible LLM client (Claude Desktop, Cursor, the MCP Inspector,
…) can query the timetable and parent letters directly as tools.

```bash
python cli.py --url https://school.iserv.de --username student mcp
```

The server speaks the **stdio** transport by default (JSON-RPC over
stdin/stdout). A **Streamable HTTP** transport is also available:

```bash
python cli.py --url https://school.iserv.de --username student mcp \
  --transport streamable-http --host 127.0.0.1 --port 8000
```

Options:

| Flag | Default | Description |
| --- | --- | --- |
| `--transport` | `stdio` | Transport: `stdio` or `streamable-http` |
| `--host` | `127.0.0.1` | Bind host (streamable-http only) |
| `--port` | `8000` | Bind port (streamable-http only) |

#### Installing the MCP dependency

The MCP server requires the `mcp` package, which is not part of the Home
Assistant integration's dependencies. Install it alongside `aiohttp`:

```bash
pip install -r requirements-cli.txt
```

#### Available tools

| Tool | Description |
| --- | --- |
| `get_full_schedule` | Full timetable for `current` or `next` week as a Markdown table |
| `get_schedule_for_day` | Timetable filtered to a single weekday (e.g. `"Monday"`) |
| `get_parentletters` | Overview of all parent letters with UUIDs, sender, date, read status |
| `get_parentletter_detail` | Full text and metadata of one letter, identified by `letter_uuid` + `child_uuid` |

#### Registering with an MCP client

Most MCP clients (Claude Desktop, Cursor, Kiro, VS Code, etc.) accept a JSON
config that tells them how to launch the server. Use the venv's Python binary
directly so all dependencies are available without any activation step:

```json
{
  "mcpServers": {
    "haiserv": {
      "command": "/path/to/haiserv/.venv/bin/python",
      "args": [
        "/path/to/haiserv/cli.py",
        "--url", "https://school.iserv.de",
        "--username", "your-username",
        "--password", "your-password",
        "mcp"
      ]
    }
  }
}
```

Replace `/path/to/haiserv` with the absolute path to the repository and fill
in your iServ URL and credentials. Where to put this config depends on your
client:

| Client | Config file |
| --- | --- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Cursor | `.cursor/mcp.json` in the repo root, or the global Cursor config |
| Kiro | `~/.kiro/settings/mcp.json` |
| VS Code (Copilot) | `.vscode/mcp.json` in the repo root |

For HTTP-based clients, start the server with `--transport streamable-http`
and register `http://127.0.0.1:8000/mcp` as the endpoint URL.
Only use this tool on a trusted machine and never paste passwords or raw
responses containing private school data into public issue reports. Verbose
output deliberately omits passwords, query-string values, and response bodies.

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

## Entities

The integration creates three sensors:

- **iServ Timetable** — the current calendar week's timetable and next lesson
- **iServ Next Week Timetable** — the following Monday-to-Friday timetable
- **iServ Parent Letters** — unread Elternbrief count and full letter list

### iServ Timetable

#### State

The state is one of:

- `<subject> <start time>-<end time>` for the next lesson today
- `No upcoming lessons` when no later lesson exists today
- `No lessons` when no timetable data is available

Example:

```text
Mathematics 08:00-08:45
```

#### Attributes

| Attribute | Description |
| --- | --- |
| `lessons` | List of lessons containing `day`, `start_time`, `end_time`, `subject`, `room`, and the boolean `canceled` status |
| `timetable_data` | Complete structured JSON response from the selected timetable API |
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

### iServ Parent Letters

Polls `/iserv/parentletter/parent/index` on the same 60-minute interval as the
timetable sensors. If the Elternbrief endpoint is unavailable, this sensor
becomes unavailable while the timetable sensors continue to function normally.

#### State

The state is one of:

- `N unread` when at least one letter has not been read (e.g. `2 unread`)
- `No unread letters` when all letters have been read
- `No letters` when no letters are in the inbox

#### Attributes

| Attribute | Description |
| --- | --- |
| `letters` | List of letter objects (see keys below) |
| `unread_count` | Number of unread letters as an integer |
| `total_count` | Total number of letters fetched |
| `last_updated` | ISO 8601 timestamp generated when the attributes are read |

Each entry in the `letters` list contains:

| Key | Description |
| --- | --- |
| `letter_uuid` | UUID of the letter |
| `child_uuid` | UUID of the child the letter is addressed to |
| `subject` | Subject line of the letter |
| `sender` | Primary sender name |
| `additional_senders` | List of additional sender names (may be empty) |
| `child` | Name of the student |
| `recipient` | Recipient group label (e.g. `Klasse o12a`) |
| `created_at` | ISO 8601 timestamp or `null` |
| `is_unread` | Boolean — `true` if the letter has not yet been read |

The `body_html` field is intentionally excluded from attributes to keep
the attribute payload small. Use the CLI `--read` option to fetch the full
letter text on demand.

## Timetable dashboard

[`dashboards/timetable.yaml`](dashboards/timetable.yaml) provides a ready-to-use
single-card panel view for the current and following week. It generates a native
Markdown pipe table with Monday through Friday as columns and lesson times as
rows. Subjects are bold, canceled lessons use strikethrough, multiple lessons in
one cell are separated with ` / `, and the current weekday column is highlighted
cell by cell, including its header. The built-in Markdown card sanitizes inline
`style` attributes, so the dashboard uses the supported `<mark>` element; its
light background color is supplied by the active Home Assistant theme/browser
rather than being fixed to an exact gray. The dashboard intentionally contains
no raw `<table>` markup. It reads the `lessons` attributes of both timetable
sensors and does not require a custom card.

Open a Home Assistant dashboard, select **Edit dashboard → three-dot menu → Raw
configuration editor**, and paste the complete YAML file. Before saving, check
the timetable entities under **Settings → Devices & services → Entities**. If
Home Assistant assigned IDs other than `sensor.iserv_timetable` and
`sensor.iserv_next_week_timetable`, replace every occurrence of those two IDs
in the file. YAML-mode installations can instead copy the file into their Home
Assistant configuration directory and reference it from their existing
Lovelace dashboard configuration.

## Updating

For a manual installation, replace `<config>/custom_components/haiserv` with the files from the newer release or revision and restart Home Assistant.

## Troubleshooting

- **Invalid URL:** The URL must use `https://` and include a valid hostname.
- **Authentication failed:** Verify the username and password by signing in to the same IServ server in a browser.
- **Cannot connect:** Verify the server URL and Home Assistant's network access.
- **No lessons:** Confirm that the account can access timetable data and that the server returns the expected timetable format.
- **Parent letters unavailable:** Confirm that the IServ account has access to the Elternbrief module. The timetable sensors are unaffected.

Home Assistant logs for `custom_components.haiserv` can provide additional details. Passwords are not intentionally written to the integration's logs.

## Development

The repository contains unit, integration, and property-based tests under `tests/`.

A local development environment needs the dependencies imported by the test suite, including Home Assistant, pytest, pytest-asyncio, Hypothesis, aioresponses, aiohttp, and voluptuous. The CLI and MCP server additionally require the packages listed in `requirements-cli.txt`. Run the tests from the repository root:

```bash
python -m pytest
```

Generated test caches such as `.hypothesis/` and `.pytest_cache/` are intentionally excluded from version control.

## Security

Do not include real credentials in bug reports, logs, fixtures, or commits. If you discover a security issue, contact the repository owner privately rather than opening a public issue containing sensitive data.

## License

This project is licensed under the [MIT License](LICENSE).
