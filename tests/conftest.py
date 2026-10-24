"""Test isolation: the suite never reads the developer's .env (keys, zones, FalkorDB port).

Opt-in live tests pass what they need through real environment variables
(e.g. CONFERGE_FALKORDB_TEST=1 FALKORDB_PORT=6380), which still take precedence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conferge.core import settings


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "ENV_PATH", tmp_path / "absent.env")
