from __future__ import annotations

from pathlib import Path

import pytest

from conferge.core import settings


def test_env_value_prefers_environment_then_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nFALKORDB_PORT=6380\nexport FALKORDB_HOST='db.local'\n", encoding="utf-8")
    monkeypatch.delenv("FALKORDB_PORT", raising=False)
    monkeypatch.delenv("FALKORDB_HOST", raising=False)
    assert settings.env_value("FALKORDB_PORT", path=env) == "6380"
    assert settings.env_value("FALKORDB_HOST", path=env) == "db.local"
    assert settings.env_value("MISSING", "dflt", path=env) == "dflt"
    monkeypatch.setenv("FALKORDB_PORT", "7000")
    assert settings.env_value("FALKORDB_PORT", path=env) == "7000"


def test_falkordb_address_defaults_to_6379(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FALKORDB_HOST", raising=False)
    monkeypatch.delenv("FALKORDB_PORT", raising=False)
    monkeypatch.setattr(settings, "ENV_PATH", tmp_path / "absent.env")
    monkeypatch.setattr(settings.env_value, "__kwdefaults__", {"path": tmp_path / "absent.env"})
    assert settings.falkordb_address() == ("127.0.0.1", 6379)
