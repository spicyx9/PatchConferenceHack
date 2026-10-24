"""make demo preflight: a plain Redis or a closed port stops with one line, no stack trace."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_demo(port: int, ui_port: int | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "FALKORDB_HOST": "127.0.0.1", "FALKORDB_PORT": str(port)}
    ui = str(ui_port if ui_port is not None else _free_port())
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "run_demo.py"), "--port", ui],
                          env=env, capture_output=True, text=True, timeout=60, cwd=ROOT)


def test_busy_ui_port_stops_before_collecting() -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        ui = busy.getsockname()[1]
        proc = _run_demo(_free_port(), ui)
    assert proc.returncode == 2
    assert f"port {ui} is already in use, run `make demo DEMO_PORT={ui + 1}`" in proc.stderr
    assert "Traceback" not in proc.stderr + proc.stdout and "assembled" not in proc.stdout


def _plain_redis(server: socket.socket) -> None:
    """Answer every command like a Redis without the FalkorDB module."""
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            while conn.recv(4096):
                conn.sendall(b"-ERR unknown command 'GRAPH.LIST', with args beginning with: \r\n")


def test_closed_port_stops_with_one_line() -> None:
    port = _free_port()
    proc = _run_demo(port)
    assert proc.returncode == 2
    assert f"nothing answers on 127.0.0.1:{port}" in proc.stderr
    assert "Traceback" not in proc.stderr + proc.stdout


def test_plain_redis_is_named_explicitly() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    threading.Thread(target=_plain_redis, args=(server,), daemon=True).start()
    try:
        proc = _run_demo(port)
    finally:
        server.close()
    assert proc.returncode == 2
    assert f"port {port} is a plain Redis, set FALKORDB_PORT to the FalkorDB port" in proc.stderr
    assert "Traceback" not in proc.stderr + proc.stdout
