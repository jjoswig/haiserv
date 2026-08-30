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
    parser.add_argument(
        "--week",
        choices=("current", "next"),
        default="current",
        help="Week to fetch (default: current)",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="Fetch and print both the current and following week",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the raw server response instead of the parsed table",
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
        print(raw_data)
        return

    print(f"Lessons: {len(lessons)}")
    print(format_markdown_table(lessons) or "No lessons")


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
    import aiohttp

    async with aiohttp.ClientSession() as session:
        client = IServClient(session, args.url, args.username, password)
        try:
            await client.authenticate()
            offsets = (0, 1) if args.both else (0 if args.week == "current" else 1,)
            for index, week_offset in enumerate(offsets):
                week_number, raw_data, lessons = await _fetch_week(client, week_offset)
                if index:
                    print()
                label = "Current" if week_offset == 0 else "Next"
                _print_week(label, week_number, raw_data, lessons, args.raw)
        except AuthenticationError:
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
