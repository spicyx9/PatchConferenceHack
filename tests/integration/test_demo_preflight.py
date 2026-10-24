"""make demo preflight: a plain Redis or a closed port stops with one line, no stack trace."""

from __future__ import annotations

import json
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


def test_unreachable_falkordb_serves_anyway_with_failed_status_and_reason() -> None:
    import time
    import urllib.request

    port, ui = _free_port(), _free_port()
    env = {**os.environ, "FALKORDB_HOST": "127.0.0.1", "FALKORDB_PORT": str(port),
           "BRIGHTDATA_API_KEY": ""}
    proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "run_demo.py"), "--port", str(ui),
                             "--graph", "conferge_w2_test"], env=env, cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        body = None
        for _ in range(240):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{ui}/api/v1/pipeline", timeout=2) as r:
                    body = json.loads(r.read())
                    break
            except OSError:
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
        assert body is not None, proc.stderr.read() if proc.poll() is not None else "no answer"
        first = body["rows"][0]
        assert first["provider"] == "falkordb" and first["status"] == "failed"
        assert first["reason"] == f"FalkorDB unreachable on 127.0.0.1:{port}"
    finally:
        proc.terminate()
        out, err = proc.communicate(timeout=20)
    assert "Traceback" not in out + err


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
