#!/usr/bin/env python3
"""Command-line debugger for the HAiServ timetable client.

Run from the repository root, for example:
    python cli.py --url https://school.iserv.de --username student

The password is requested securely unless supplied through ISERV_PASSWORD.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

# Make the custom component importable when this file is run directly.
REPOSITORY_ROOT = Path(__file__).resolve().parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.haiserv.api import IServClient
    from custom_components.haiserv.parser import Lesson


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Fetch and print iServ timetables for local debugging."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="HTTPS base URL of the iServ server, e.g. https://school.iserv.de",
    )
    parser.add_argument("--username", required=True, help="iServ username")
    parser.add_argument(
        "--password",
        help="iServ password (prefer a hidden prompt or ISERV_PASSWORD)",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = False  # default command is timetable

    # --- timetable subcommand (legacy / default) ---
    tt_parser = subparsers.add_parser(
        "timetable", help="Fetch and print the iServ timetable (default)"
    )
    tt_parser.add_argument(
        "--week",
        choices=("current", "next"),
        default="current",
        help="Week to fetch (default: current)",
    )
    tt_parser.add_argument(
        "--both",
        action="store_true",
        help="Fetch and print both the current and following week",
    )
    tt_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw server response instead of the parsed table",
    )
    tt_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print safe request, redirect, cookie, and response diagnostics",
    )

    # --- elternbrief / parentletter subcommand ---
    el_parser = subparsers.add_parser(
        "elternbrief",
        aliases=["parentletter"],
        help="List and read Elternbrief (parent letters) from iServ",
    )
    el_parser.add_argument(
        "--read",
        metavar="LETTER_UUID/CHILD_UUID",
        help=(
            "Fetch and print the full detail of one letter. "
            "Pass the two UUIDs separated by a slash, e.g. "
            "abc123…/def456…"
        ),
    )
    el_parser.add_argument(
        "--mark-read",
        metavar="LETTER_UUID/CHILD_UUID",
        help="Mark a letter as read (requires the detail page CSRF token).",
    )
    el_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print safe request, redirect, cookie, and response diagnostics",
    )

    return parser


def _password_from_args(args: argparse.Namespace) -> str:
    """Read the password without exposing it in normal process arguments."""
    if args.password is not None:
        return args.password
    if password := os.environ.get("ISERV_PASSWORD"):
        return password
    return getpass.getpass("iServ password: ")


async def _fetch_week(
    client: IServClient, week_offset: int
) -> tuple[int, str, list[Lesson]]:
    """Authenticate and fetch one relative week."""
    from custom_components.haiserv.parser import parse_timetable, sort_lessons

    target_week = (datetime.now() + timedelta(weeks=week_offset)).isocalendar()[1]
    raw_data = await client.fetch_timetable(week=target_week)
    lessons = sort_lessons(parse_timetable(raw_data, locale="en"))
    return target_week, raw_data, lessons


def _print_week(
    week_label: str,
    week_number: int,
    raw_data: str,
    lessons: list[Lesson],
    raw: bool,
) -> None:
    """Print one fetched timetable."""
    from custom_components.haiserv.parser import format_markdown_table

    print(f"=== {week_label} week (ISO week {week_number}) ===")
    if raw:
        print(getattr(raw_data, "raw_response", raw_data))
        return

    print(f"Lessons: {len(lessons)}")
    print(format_markdown_table(lessons) or "No lessons")
    timetable_data = getattr(raw_data, "timetable_data", None)
    print("\nTimetable JSON:")
    if timetable_data is None:
        print(getattr(raw_data, "raw_response", raw_data))
    else:
        print(json.dumps(timetable_data, ensure_ascii=False, indent=2))


def _debug(message: str) -> None:
    """Print a verbose diagnostic message to stderr."""
    print(f"[debug] {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Elternbrief helpers
# ---------------------------------------------------------------------------


async def _cmd_elternbrief(
    client: IServClient, args: argparse.Namespace
) -> int:
    """Handle the ``elternbrief`` / ``parentletter`` subcommand."""
    from custom_components.haiserv.parentletter_parser import (
        parse_parentletter_list,
        parse_parentletter_detail,
        extract_csrf_token,
    )

    # --- detail / mark-as-read ---
    if args.read or args.mark_read:
        raw_uuids = args.read or args.mark_read
        parts = raw_uuids.strip().split("/", 1)
        if len(parts) != 2:
            print(
                "Error: expected LETTER_UUID/CHILD_UUID separated by '/'.",
                file=sys.stderr,
            )
            return 2
        letter_uuid, child_uuid = parts

        html = await client.fetch_parentletter_detail(letter_uuid, child_uuid)

        if args.read:
            # Print the detail page as plain text
            from html.parser import HTMLParser

            class _StripParser(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self._chunks: list[str] = []

                def handle_data(self, data: str) -> None:
                    self._chunks.append(data)

                def get_text(self) -> str:
                    import re
                    return re.sub(r"\s+", " ", "".join(self._chunks)).strip()

            p = _StripParser()
            p.feed(html)
            print(p.get_text())
            return 0

        # mark-as-read
        csrf = extract_csrf_token(html)
        if not csrf:
            print(
                "Error: could not find CSRF token in the detail page.",
                file=sys.stderr,
            )
            return 2
        await client.mark_parentletter_read(letter_uuid, child_uuid, csrf)
        print("Letter marked as read.")
        return 0

    # --- default: list all letters ---
    html = await client.fetch_parentletter_list()
    letters = parse_parentletter_list(html)

    if not letters:
        print("No Elternbrief found.")
        return 0

    # Print a simple table
    print(f"{'#':<4}  {'UNREAD':<7}  {'DATE':<17}  {'SENDER':<25}  {'CHILD':<20}  SUBJECT")
    print("-" * 100)
    for idx, letter in enumerate(letters, start=1):
        date_str = (
            letter.created_at.strftime("%d.%m.%Y %H:%M") if letter.created_at else "—"
        )
        unread_flag = "●" if letter.is_unread else " "
        sender = (letter.sender or "")[:25]
        child = (letter.child or "")[:20]
        subject = letter.subject or ""
        print(f"{idx:<4}  {unread_flag:<7}  {date_str:<17}  {sender:<25}  {child:<20}  {subject}")

    unread_count = sum(1 for letter in letters if letter.is_unread)
    print(f"\nTotal: {len(letters)}  |  Unread: {unread_count}")
    return 0


async def async_main(args: argparse.Namespace) -> int:
    """Run the CLI workflow and return a process exit code."""
    from custom_components.haiserv.api import (
        AuthenticationError,
        CannotConnect,
        IServClient,
        validate_url,
    )
    if not validate_url(args.url):
        print(
            "Error: --url must be an HTTPS URL with a valid hostname.",
            file=sys.stderr,
        )
        return 2

    password = _password_from_args(args)
    verbose = getattr(args, "verbose", False)
    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = IServClient(
            session,
            args.url,
            args.username,
            password,
            debug_callback=_debug if verbose else None,
        )
        try:
            await client.authenticate()

            command = getattr(args, "command", None)
            if command in ("elternbrief", "parentletter"):
                return await _cmd_elternbrief(client, args)

            # Default / timetable command
            week = getattr(args, "week", "current")
            both = getattr(args, "both", False)
            raw = getattr(args, "raw", False)
            offsets = (0, 1) if both else (0 if week == "current" else 1,)
            for index, week_offset in enumerate(offsets):
                week_number, raw_data, lessons = await _fetch_week(client, week_offset)
                if index:
                    print()
                label = "Current" if week_offset == 0 else "Next"
                _print_week(label, week_number, raw_data, lessons, raw)

        except AuthenticationError as err:
            if verbose:
                _debug(f"authentication failed: {err}")
            print("Error: authentication failed; check URL, username, and password.", file=sys.stderr)
            return 3
        except CannotConnect as err:
            print(f"Error: could not connect to iServ: {err}", file=sys.stderr)
            return 4
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            print(f"Error: network request failed: {err}", file=sys.stderr)
            return 4

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the synchronous CLI entry point."""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
