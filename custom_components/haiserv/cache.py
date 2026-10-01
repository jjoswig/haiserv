"""Small on-disk cache for iServ responses.

The cache keeps the last successful response per key so a temporary failure
(for example an HTTP 403 while a school has the timetable disabled for parents)
can be served from the previous data instead of failing.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Environment variable overriding the cache directory for the CLI/MCP server.
CACHE_DIR_ENV = "ISERV_CACHE_DIR"


def default_cache_dir() -> str:
    """Return the cache directory used by the CLI and MCP server.

    Uses ``ISERV_CACHE_DIR`` when set, otherwise ``~/.cache/haiserv``.
    """
    return os.environ.get(CACHE_DIR_ENV) or os.path.join(
        os.path.expanduser("~"), ".cache", "haiserv"
    )


class ResponseCache:
    """JSON file cache storing the last successful response per key."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        """Initialize the cache with its storage directory."""
        self._directory = Path(directory)

    def _path(self, key: str) -> Path:
        """Return the file path for a cache key, sanitized for the filesystem."""
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_") or "cache"
        return self._directory / f"{safe}.json"

    def load(self, key: str) -> Any | None:
        """Return the cached value for ``key``, or None when absent/unreadable."""
        path = self._path(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as err:
            _LOGGER.warning("Ignoring unreadable iServ cache %s: %s", path, err)
            return None

    def store(self, key: str, value: Any) -> None:
        """Atomically write ``value`` as the cached entry for ``key``."""
        path = self._path(key)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as err:
            _LOGGER.warning("Could not write iServ cache %s: %s", path, err)
