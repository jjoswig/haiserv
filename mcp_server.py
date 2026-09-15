#!/usr/bin/env python3
"""MCP server for HAiServ — exposes iServ timetable and parent-letter data as MCP tools.

Run via the CLI wrapper (recommended):
    python cli.py --url https://school.iserv.de --username student mcp

Or directly (credentials come from environment variables):
    ISERV_URL=https://school.iserv.de \\
    ISERV_USERNAME=student \\
    ISERV_PASSWORD=secret \\
    python mcp_server.py

The server speaks stdio (JSON-RPC over stdin/stdout) and is compatible with any
MCP 1.x client such as Claude Desktop, Cursor, or the MCP Inspector.

IMPORTANT: All diagnostic output must go to stderr — stdout is the MCP wire.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
# Shared async helpers
# ---------------------------------------------------------------------------


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

    missing = [name for name, val in (
        ("ISERV_URL", url),
        ("ISERV_USERNAME", username),
        ("ISERV_PASSWORD", password),
    ) if not val]

    if missing:
        raise ValueError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set ISERV_URL, ISERV_USERNAME, and ISERV_PASSWORD before starting the server."
        )

    return url, username, password


async def _make_authenticated_client() -> tuple[Any, Any]:
    """Create an aiohttp session and an authenticated IServClient.

    Returns:
        Tuple of (aiohttp.ClientSession, IServClient). The caller is
        responsible for closing the session after use.

    Raises:
        ValueError: When credentials are missing.
        AuthenticationError: When login fails.
        CannotConnect: When the server is unreachable.
    """
    import aiohttp

    from custom_components.haiserv.api import AuthenticationError, CannotConnect, IServClient

    url, username, password = _get_credentials()
    session = aiohttp.ClientSession()
    try:
        client = IServClient(session, url, username, password)
        await client.authenticate()
    except (AuthenticationError, CannotConnect):
        await session.close()
        raise

    return session, client


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

    session, client = await _make_authenticated_client()
    try:
        raw = await client.fetch_timetable(week=target_iso_week)
        lessons = sort_lessons(parse_timetable(str(raw), locale="en"))
    finally:
        await session.close()

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

    session, client = await _make_authenticated_client()
    try:
        raw = await client.fetch_timetable(week=target_iso_week)
        all_lessons = sort_lessons(parse_timetable(str(raw), locale="en"))
    finally:
        await session.close()

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

    session, client = await _make_authenticated_client()
    try:
        html = await client.fetch_parentletter_list()
    finally:
        await session.close()

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

    # Create a stub ParentLetter so the detail parser has something to enrich.
    stub = ParentLetter(
        letter_uuid=letter_uuid,
        child_uuid=child_uuid,
        subject="",
        sender="",
    )

    session, client = await _make_authenticated_client()
    try:
        html = await client.fetch_parentletter_detail(letter_uuid, child_uuid)
    finally:
        await session.close()

    enriched = parse_parentletter_detail(html, stub)

    # Convert HTML body to plain text for LLM consumption.
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
            # Collapse runs of whitespace while preserving single newlines.
            raw = re.sub(r"[ \t]+", " ", raw)
            raw = re.sub(r"\n{3,}", "\n\n", raw)
            return raw.strip()

    stripper = _Stripper()
    stripper.feed(html)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()  # defaults to stdio transport
