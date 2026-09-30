#!/usr/bin/env python3
"""MCP server for HAiServ — exposes iServ timetable and parent-letter data as MCP tools.

Run via the CLI wrapper (recommended):
    python cli.py --url https://school.iserv.de --username student mcp

Or directly (credentials come from environment variables):
    ISERV_URL=https://school.iserv.de \\
    ISERV_USERNAME=student \\
    ISERV_PASSWORD=secret \\
    python mcp_server.py

The server speaks stdio (JSON-RPC over stdin/stdout) by default and is
compatible with any MCP 1.x client such as Claude Desktop, Cursor, or the MCP
Inspector. A Streamable HTTP transport is also available:

    python mcp_server.py --transport streamable-http --host 127.0.0.1 --port 8000

Systemd:
    python mcp_server.py --print-systemd-unit
    sudo python mcp_server.py --install-systemd-unit --url … --username …

IMPORTANT: All diagnostic output must go to stderr — stdout is the MCP wire.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import pwd
import shutil
import string
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Make custom_components importable when the file is run directly.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Route all logging to stderr so it never pollutes the MCP stdio stream.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    stream=sys.stderr,
    format="[haiserv-mcp] %(levelname)s %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("haiserv.mcp")

# ---------------------------------------------------------------------------
# Server / systemd defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
SERVICE_NAME = "haiserv-mcp"
DEFAULT_UNIT_DIR = "/etc/systemd/system"
DEFAULT_ENV_FILE = "/etc/haiserv/mcp.env"
UNIT_TEMPLATE_PATH = _REPO_ROOT / "systemd" / "haiserv-mcp.service.in"

# Keys written to the systemd environment file, in this order.
CREDENTIAL_ENV_KEYS = (
    "ISERV_URL",
    "ISERV_USERNAME",
    "ISERV_PASSWORD",
    "ISERV_CHILD_ID",
)

# ---------------------------------------------------------------------------
# MCP server bootstrap
# ---------------------------------------------------------------------------
from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]

mcp = FastMCP(
    "haiserv",
    instructions=(
        "Access an iServ school portal. "
        "Tools: get_full_schedule (whole timetable), "
        "get_schedule_for_day (single day), "
        "get_parentletters (overview list), "
        "get_parentletter_detail (full text of one letter)."
    ),
)

# ---------------------------------------------------------------------------
# Shared session — one authenticated IServClient for the server's lifetime.
# Created lazily on the first tool call and reused for all subsequent ones.
# ---------------------------------------------------------------------------
_client = None  # IServClient | None
_session = None  # aiohttp.ClientSession | None


def _get_credentials() -> tuple[str, str, str]:
    """Read connection credentials from environment variables.

    Returns:
        Tuple of (url, username, password).

    Raises:
        ValueError: If any required variable is missing or empty.
    """
    url = os.environ.get("ISERV_URL", "").strip()
    username = os.environ.get("ISERV_USERNAME", "").strip()
    password = os.environ.get("ISERV_PASSWORD", "").strip()

    missing = [
        name
        for name, val in (
            ("ISERV_URL", url),
            ("ISERV_USERNAME", username),
            ("ISERV_PASSWORD", password),
        )
        if not val
    ]
    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set ISERV_URL, ISERV_USERNAME, and ISERV_PASSWORD before starting the server."
        )

    return url, username, password


async def _get_client():
    """Return the shared IServClient, creating and authenticating it if needed.

    The session and client are module-level singletons so that the cookie jar
    survives across tool calls. IServClient already handles transparent
    re-authentication when a session expires.

    Returns:
        An authenticated IServClient instance.

    Raises:
        ValueError: When credentials are missing.
        AuthenticationError: When login fails.
        CannotConnect: When the server is unreachable.
    """
    global _client, _session

    import aiohttp
    from custom_components.haiserv.api import AuthenticationError, CannotConnect, IServClient

    if _client is not None and _client.is_authenticated:
        return _client

    # Close any stale session before opening a new one.
    if _session is not None:
        await _session.close()

    url, username, password = _get_credentials()
    _session = aiohttp.ClientSession()
    _client = IServClient(_session, url, username, password)
    try:
        await _client.authenticate()
    except (AuthenticationError, CannotConnect):
        await _session.close()
        _session = None
        _client = None
        raise

    return _client


# ---------------------------------------------------------------------------
# Tool: get_full_schedule
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_full_schedule(week: str = "current") -> str:
    """Return the complete timetable for the requested week as a Markdown table.

    Args:
        week: Which week to fetch. Accepted values:
              "current" — the current ISO calendar week (default),
              "next"    — the following ISO calendar week.

    Returns:
        A Markdown table with columns Day, Time, Subject, Room, Canceled.
        Returns a plain-text message if no lessons were found.
    """
    from custom_components.haiserv.parser import format_markdown_table, parse_timetable, sort_lessons

    if week not in ("current", "next"):
        return f"Invalid week value '{week}'. Use 'current' or 'next'."

    week_offset = 0 if week == "current" else 1
    target_iso_week = (datetime.now() + timedelta(weeks=week_offset)).isocalendar()[1]

    client = await _get_client()
    raw = await client.fetch_timetable(week=target_iso_week)
    lessons = sort_lessons(parse_timetable(str(raw), locale="en"))

    if not lessons:
        return f"No lessons found for the {week} week (ISO week {target_iso_week})."

    table = format_markdown_table(lessons)
    return f"## Timetable — {week.capitalize()} week (ISO week {target_iso_week})\n\n{table}"


# ---------------------------------------------------------------------------
# Tool: get_schedule_for_day
# ---------------------------------------------------------------------------

_VALID_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


@mcp.tool()
async def get_schedule_for_day(day: str, week: str = "current") -> str:
    """Return the timetable filtered to a single weekday as a Markdown table.

    Args:
        day: Weekday name in English, e.g. "Monday", "Tuesday", …, "Friday".
             Case-insensitive.
        week: Which week to fetch — "current" (default) or "next".

    Returns:
        A Markdown table for the requested day, or a message if no lessons exist.
    """
    from custom_components.haiserv.parser import format_markdown_table, parse_timetable, sort_lessons

    normalised_day = day.strip().capitalize()
    if normalised_day not in _VALID_DAYS:
        return (
            f"Unknown day '{day}'. "
            f"Please use one of: {', '.join(_VALID_DAYS)}."
        )

    if week not in ("current", "next"):
        return f"Invalid week value '{week}'. Use 'current' or 'next'."

    week_offset = 0 if week == "current" else 1
    target_iso_week = (datetime.now() + timedelta(weeks=week_offset)).isocalendar()[1]

    client = await _get_client()
    raw = await client.fetch_timetable(week=target_iso_week)
    all_lessons = sort_lessons(parse_timetable(str(raw), locale="en"))

    day_lessons = [lesson for lesson in all_lessons if lesson.day == normalised_day]

    if not day_lessons:
        return (
            f"No lessons found for {normalised_day} "
            f"in the {week} week (ISO week {target_iso_week})."
        )

    table = format_markdown_table(day_lessons)
    return (
        f"## Timetable — {normalised_day}, "
        f"{week.capitalize()} week (ISO week {target_iso_week})\n\n{table}"
    )


# ---------------------------------------------------------------------------
# Tool: get_parentletters
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_parentletters() -> str:
    """Return an overview of all Elternbrief (parent letters) from iServ.

    Lists every available parent letter with its index, read status, date,
    sender, child name, and subject. Use get_parentletter_detail to fetch the
    full text of a specific letter.

    Returns:
        A Markdown table of all letters, followed by a summary line.
        Returns a plain-text message if no letters were found.
    """
    from custom_components.haiserv.parentletter_parser import parse_parentletter_list

    client = await _get_client()
    html = await client.fetch_parentletter_list()
    letters = parse_parentletter_list(html)

    if not letters:
        return "No parent letters (Elternbrief) found."

    lines: list[str] = [
        "## Parent Letters (Elternbrief) Overview",
        "",
        "| # | Unread | Date | Sender | Child | Subject | letter_uuid | child_uuid |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for idx, letter in enumerate(letters, start=1):
        date_str = (
            letter.created_at.strftime("%d.%m.%Y %H:%M") if letter.created_at else "—"
        )
        unread_flag = "●" if letter.is_unread else " "
        sender = (letter.sender or "").replace("|", "\\|")
        child = (letter.child or "").replace("|", "\\|")
        subject = (letter.subject or "").replace("|", "\\|")
        lines.append(
            f"| {idx} | {unread_flag} | {date_str} | {sender} | {child} | {subject} "
            f"| `{letter.letter_uuid}` | `{letter.child_uuid}` |"
        )

    unread_count = sum(1 for letter in letters if letter.is_unread)
    lines.append("")
    lines.append(f"**Total:** {len(letters)}  |  **Unread:** {unread_count}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: get_parentletter_detail
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_parentletter_detail(letter_uuid: str, child_uuid: str) -> str:
    """Return the full text and metadata of a single parent letter (Elternbrief).

    Use get_parentletters first to obtain the letter_uuid and child_uuid values.

    Args:
        letter_uuid: UUID of the letter (visible in the overview table).
        child_uuid:  UUID of the child the letter is addressed to.

    Returns:
        Formatted Markdown with letter metadata (subject, sender, date, child)
        followed by the full letter body as plain text.
    """
    from custom_components.haiserv.parentletter_parser import (
        ParentLetter,
        parse_parentletter_detail,
    )

    letter_uuid = letter_uuid.strip()
    child_uuid = child_uuid.strip()

    if not letter_uuid or not child_uuid:
        return "Both letter_uuid and child_uuid are required."

    stub = ParentLetter(
        letter_uuid=letter_uuid,
        child_uuid=child_uuid,
        subject="",
        sender="",
    )

    client = await _get_client()
    html = await client.fetch_parentletter_detail(letter_uuid, child_uuid)
    enriched = parse_parentletter_detail(html, stub)

    body_plain = _html_to_text(enriched.body_html or html)

    date_str = (
        enriched.created_at.strftime("%d.%m.%Y %H:%M") if enriched.created_at else "—"
    )
    additional = (
        (", ".join(enriched.additional_senders)) if enriched.additional_senders else "—"
    )

    lines: list[str] = [
        f"## {enriched.subject or '(no subject)'}",
        "",
        f"**Sender:** {enriched.sender or '—'}",
        f"**Additional senders:** {additional}",
        f"**Child:** {enriched.child or '—'}",
        f"**Recipient:** {enriched.recipient or '—'}",
        f"**Date:** {date_str}",
        f"**Read:** {'No' if enriched.is_unread else 'Yes'}",
        "",
        "---",
        "",
        body_plain.strip() or "(no body text)",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML → plain-text helper
# ---------------------------------------------------------------------------


def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace into readable plain text.

    Args:
        html: Raw HTML string.

    Returns:
        Clean plain-text representation of the HTML content.
    """
    import re
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._parts: list[str] = []
            self._skip = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("script", "style"):
                self._skip = True
            elif tag in ("p", "br", "li", "div", "tr", "h1", "h2", "h3", "h4"):
                self._parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            if tag in ("script", "style"):
                self._skip = False

        def handle_data(self, data: str) -> None:
            if not self._skip:
                self._parts.append(data)

        def get_text(self) -> str:
            raw = "".join(self._parts)
            raw = re.sub(r"[ \t]+", " ", raw)
            raw = re.sub(r"\n{3,}", "\n\n", raw)
            return raw.strip()

    stripper = _Stripper()
    stripper.feed(html)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# systemd integration
# ---------------------------------------------------------------------------


def _default_service_user(workdir: Path) -> str:
    """Pick the service user: the checkout owner, else SUDO_USER/invoking user.

    The service must be able to read the checkout (code, venv), so the owner of
    the working directory is the safe default even when the installer runs under
    sudo from a different account.
    """
    try:
        return pwd.getpwuid(workdir.stat().st_uid).pw_name
    except (OSError, KeyError):
        return os.environ.get("SUDO_USER") or getpass.getuser()


def _access_hint(workdir: Path, service_user: str) -> str | None:
    """Return a warning when the service user cannot traverse the checkout.

    systemd changes into ``WorkingDirectory`` before dropping privileges, so a
    service user without search permission on any parent directory fails with
    ``status=200/CHDIR``.
    """
    try:
        target = pwd.getpwnam(service_user)
    except KeyError:
        return f"user '{service_user}' does not exist on this system"

    groups = set(os.getgrouplist(service_user, target.pw_gid))
    for path in (workdir, *workdir.parents):
        try:
            status = path.stat()
        except OSError:
            continue
        if status.st_uid == target.pw_uid:
            allowed = bool(status.st_mode & 0o100)
        elif status.st_gid in groups:
            allowed = bool(status.st_mode & 0o010)
        else:
            allowed = bool(status.st_mode & 0o001)
        if not allowed:
            owner = pwd.getpwuid(status.st_uid).pw_name
            return (
                f"'{service_user}' cannot enter {path} (owner {owner}, mode "
                f"{oct(status.st_mode & 0o777)}), so the service would fail with "
                f"'Changing to the requested working directory failed'. Run the "
                f"checkout from a directory {service_user} can read, or install "
                f"with --service-user {owner}."
            )
    return None


def render_systemd_unit(
    *,
    service_user: str,
    workdir: Path,
    python: str,
    host: str,
    port: int,
    env_file: Path,
) -> str:
    """Render the systemd unit template for this checkout."""
    template = string.Template(UNIT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(
        SERVICE_USER=service_user,
        WORKDIR=str(workdir),
        PYTHON=python,
        HOST=host,
        PORT=port,
        ENV_FILE=str(env_file),
    )


def _run(command: list[str]) -> None:
    """Run a system command, reporting failures without aborting."""
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as err:
        print(f"Warning: {' '.join(command)} failed: {err}", file=sys.stderr)


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from an existing environment file, if present."""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def install_systemd_unit(args: argparse.Namespace) -> int:
    """Install the systemd unit and its environment file.

    Returns:
        Process exit code.
    """
    unit_dir = Path(args.unit_dir)
    unit_path = unit_dir / f"{SERVICE_NAME}.service"
    env_path = Path(args.env_file)

    if unit_dir == Path(DEFAULT_UNIT_DIR) and os.geteuid() != 0:
        print(
            f"Error: writing to {unit_dir} needs root; run this with sudo.",
            file=sys.stderr,
        )
        return 2

    # Credentials: CLI flag, then an existing env file, then the environment.
    existing = _read_env_file(env_path)
    supplied = {
        "ISERV_URL": args.url,
        "ISERV_USERNAME": args.username,
        "ISERV_PASSWORD": args.password,
        "ISERV_CHILD_ID": args.child_id,
    }
    credentials: dict[str, str] = {}
    for key in CREDENTIAL_ENV_KEYS:
        value = supplied.get(key) or existing.get(key) or os.environ.get(key, "")
        if value:
            credentials[key] = value

    missing = [
        key
        for key in ("ISERV_URL", "ISERV_USERNAME", "ISERV_PASSWORD")
        if key not in credentials
    ]
    if missing:
        print(
            f"No {', '.join(missing)} given; the service will fail at startup "
            f"until they are set in {env_path}.",
            file=sys.stderr,
        )

    service_user = args.service_user or _default_service_user(_REPO_ROOT)

    unit = render_systemd_unit(
        service_user=service_user,
        workdir=_REPO_ROOT,
        python=sys.executable,
        host=args.host,
        port=args.port,
        env_file=env_path.resolve(),
    )

    hint = _access_hint(_REPO_ROOT, service_user)
    if hint:
        print(f"Warning: {hint}", file=sys.stderr)

    if unit_path.exists():
        backup = unit_path.with_suffix(".service.bak")
        shutil.copy2(unit_path, backup)
        print(f"Existing unit backed up to {backup}", file=sys.stderr)

    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(unit, encoding="utf-8")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text(
        "".join(f"{key}={value}\n" for key, value in credentials.items()),
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)

    print(f"Wrote {unit_path}")
    print(f"Wrote {env_path} (mode 0600, holds the iServ credentials)")

    if unit_dir == Path(DEFAULT_UNIT_DIR):
        _run(["systemctl", "daemon-reload"])
        _run(["systemctl", "enable", "--now", SERVICE_NAME])
        print(f"Service {SERVICE_NAME} enabled and started.")
    else:
        print("Custom unit dir: skipping systemctl.", file=sys.stderr)
        print("  systemctl daemon-reload")
        print(f"  systemctl enable --now {SERVICE_NAME}")

    print("\nManage the daemon:")
    print(f"  systemctl status {SERVICE_NAME}")
    print(f"  systemctl restart {SERVICE_NAME}")
    print(f"  journalctl -u {SERVICE_NAME} -f")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Expose HAiServ timetables and parent letters as an MCP server."
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Bind host for streamable-http (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port for streamable-http (default: {DEFAULT_PORT})",
    )
    parser.add_argument("--url", help="iServ base URL (or set ISERV_URL)")
    parser.add_argument("--username", help="iServ username (or set ISERV_USERNAME)")
    parser.add_argument("--password", help="iServ password (or set ISERV_PASSWORD)")
    parser.add_argument(
        "--child-id", help="Child UUID for parent accounts (or set ISERV_CHILD_ID)"
    )
    parser.add_argument(
        "--print-systemd-unit",
        action="store_true",
        help="Print the rendered systemd unit and exit",
    )
    parser.add_argument(
        "--install-systemd-unit",
        action="store_true",
        help="Install the systemd unit and environment file (run with sudo)",
    )
    parser.add_argument(
        "--unit-dir",
        default=DEFAULT_UNIT_DIR,
        help=f"Directory for the unit file (default: {DEFAULT_UNIT_DIR})",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_FILE,
        help=f"Environment file holding the iServ credentials (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--service-user",
        help="User the service runs as (default: owner of the checkout)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the MCP server or manage its systemd unit."""
    args = build_parser().parse_args(argv)

    if args.print_systemd_unit:
        print(
            render_systemd_unit(
                service_user=args.service_user or _default_service_user(_REPO_ROOT),
                workdir=_REPO_ROOT,
                python=sys.executable,
                host=args.host,
                port=args.port,
                env_file=Path(args.env_file).resolve(),
            )
        )
        return 0

    if args.install_systemd_unit:
        return install_systemd_unit(args)

    # Running: any CLI credentials override the environment.
    for key, value in (
        ("ISERV_URL", args.url),
        ("ISERV_USERNAME", args.username),
        ("ISERV_PASSWORD", args.password),
        ("ISERV_CHILD_ID", args.child_id),
    ):
        if value:
            os.environ[key] = value

    # FastMCP reads host/port from its settings when serving HTTP.
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    if args.transport == "stdio":
        print("Serving HAiServ MCP over stdio.", file=sys.stderr)
    else:
        print(
            f"Serving HAiServ MCP on http://{args.host}:{args.port}/mcp.",
            file=sys.stderr,
        )

    mcp.run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
