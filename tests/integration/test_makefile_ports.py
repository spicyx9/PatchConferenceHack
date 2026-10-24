"""Makefile: one FALKORDB_PORT for every target; make up fails fast on a busy port."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "FALKORDB_PORT"}
    return {**env, **extra}


def test_up_demo_predemo_e2e_share_one_falkordb_port() -> None:
    out = subprocess.run(["make", "-n", "up", "demo", "predemo", "e2e", "FALKORDB_PORT=6431"],
                         cwd=ROOT, env=_env(), capture_output=True, text=True, timeout=30).stdout
    assert "/dev/tcp/127.0.0.1/6431" in out  # make up checks the same port it starts
    assert "6380" not in out  # no target keeps its own default
    from_env = subprocess.run(["make", "-n", "up"], cwd=ROOT, env=_env(FALKORDB_PORT="6432"),
                              capture_output=True, text=True, timeout=30).stdout
    assert "/dev/tcp/127.0.0.1/6432" in from_env  # the environment is honoured
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert makefile.count("FALKORDB_PORT ?=") == 1 and "export FALKORDB_PORT" in makefile


def test_make_up_on_a_busy_port_fails_fast_with_the_exact_message() -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        t0 = time.monotonic()
        proc = subprocess.run(["make", "up", f"FALKORDB_PORT={port}"], cwd=ROOT, env=_env(),
                              capture_output=True, text=True, timeout=30)
        elapsed = time.monotonic() - t0
    assert proc.returncode != 0 and elapsed < 5
    assert (f"Port {port} busy: run make up FALKORDB_PORT=6402 && make demo FALKORDB_PORT=6402"
            in proc.stdout)
