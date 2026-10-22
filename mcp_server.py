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
from contextlib import asynccontextmanager
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
import haiserv_mcp


@asynccontextmanager
async def _lifespan(server: FastMCP):
    try:
        yield
    finally:
        await haiserv_mcp.shutdown()


mcp = FastMCP(
    "haiserv",
    lifespan=_lifespan,
    instructions=(
        "Access an iServ school portal. "
        "Tools: get_full_schedule (whole timetable), "
        "get_schedule_for_day (single day), "
        "get_parentletters (overview list), "
        "get_parentletter_detail (full text of one letter)."
    ),
)

haiserv_mcp.setup(mcp, {})

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
