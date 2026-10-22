"""Reusable HAiServ MCP tools and session lifecycle (no server transport)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Shared session — one authenticated IServClient for the server's lifetime.
# Created lazily on the first tool call and reused for all subsequent ones.
# ---------------------------------------------------------------------------
_client = None  # IServClient | None
_session = None  # aiohttp.ClientSession | None
_client_lock = asyncio.Lock()


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

    async with _client_lock:

        import aiohttp
        from custom_components.haiserv.api import IServClient
        from custom_components.haiserv.cache import ResponseCache, default_cache_dir

        if _client is not None and _client.is_authenticated:
            return _client

        # Close any stale session before opening a new one.
        if _session is not None:
            await _session.close()

        url, username, password = _get_credentials()
        _session = aiohttp.ClientSession()
        _client = IServClient(
            _session,
            url,
            username,
            password,
            cache=ResponseCache(default_cache_dir()),
        )
        try:
            await _client.authenticate()
        except BaseException:
            await _session.close()
            _session = None
            _client = None
            raise

        return _client


# ---------------------------------------------------------------------------
# Tool: get_full_schedule
# ---------------------------------------------------------------------------


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
    raw = await client.fetch_timetable(week=target_iso_week, cache_slot=week)
    lessons = sort_lessons(parse_timetable(str(raw), locale="en"))

    if not lessons:
        return f"No lessons found for the {week} week (ISO week {target_iso_week})."

    table = format_markdown_table(lessons)
    return f"## Timetable — {week.capitalize()} week (ISO week {target_iso_week})\n\n{table}"


# ---------------------------------------------------------------------------
# Tool: get_schedule_for_day
# ---------------------------------------------------------------------------

_VALID_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


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
    raw = await client.fetch_timetable(week=target_iso_week, cache_slot=week)
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


async def shutdown() -> None:
    """Close the shared HTTP session when the MCP host shuts down."""
    global _client, _session
    if _session is not None:
        await _session.close()
    _session = None
    _client = None


def setup(server: FastMCP, options: dict[str, Any]) -> None:
    """Register HAiServ tools; credentials retain their ISERV_* environment names."""
    if options:
        raise ValueError("HAiServ uses ISERV_* environment variables, not plugin options")
    for tool in (
        get_full_schedule,
        get_schedule_for_day,
        get_parentletters,
        get_parentletter_detail,
    ):
        server.add_tool(tool)
