"""Local settings: process environment first, then the repo-root ``.env``.

``.env`` is read lazily and never copied into ``os.environ``, so importing
Conferge cannot switch tests or providers to live credentials by side effect.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


@lru_cache(maxsize=4)
def _dotenv(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def env_value(name: str, default: str | None = None, *, path: Path = ENV_PATH) -> str | None:
    """Value of ``name`` from the environment, else from ``.env``, else ``default``."""
    if name in os.environ:
        return os.environ[name]
    return _dotenv(path).get(name, default)


def falkordb_address() -> tuple[str, int]:
    """FalkorDB host and port (FALKORDB_HOST, FALKORDB_PORT; default 127.0.0.1:6379)."""
    return (env_value("FALKORDB_HOST", "127.0.0.1") or "127.0.0.1",
            int(env_value("FALKORDB_PORT", "6379") or "6379"))
