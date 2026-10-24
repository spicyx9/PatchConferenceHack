"""Tests for the pre-demo check (scripts/predemo.sh, scripts/predemo_check.py)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("predemo_check", ROOT / "scripts" / "predemo_check.py")
predemo = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(predemo)

EXP = {"top3": ["Ryan Hecht", "Camila Maia", "Nick Liffen"], "stays_bd": 21, "flights_bd": 34,
       "linkedin_min": 9}


def _data(**over):
    pipeline = {"rows": [
        {"source": "stays", "kind": "brightdata", "brightdata_api": "dataset", "records": 15, "status": "ok"},
        {"source": "stays", "kind": "brightdata", "brightdata_api": "unlocker", "records": 6, "status": "ok"},
        {"source": "stays", "kind": "direct", "brightdata_api": None, "records": 40, "status": "ok"},
        {"source": "flights", "kind": "brightdata", "brightdata_api": "unlocker", "records": 34, "status": "ok"},
        {"source": "flights", "kind": "brightdata", "brightdata_api": "dataset", "records": 5, "status": "failed"},
    ]}
    names = EXP["top3"] + [f"P{i}" for i in range(7)]
    people = {"items": [{"person": {"name": n}, "linkedin": {"url": "x"}} for n in names]}
    data = {"graph": (704, 2237), "pipeline": pipeline, "people": people, "antifomo_seconds": 1.4}
    data.update(over)
    return data


def test_all_ok():
    rows = predemo.evaluate(_data(), EXP)
    assert len(rows) == 6 and all(ok for _, ok, _ in rows)


def test_each_failure_is_reported():
    bad = _data(graph=(10, 5), antifomo_seconds=2.5,
                people={"items": [{"person": {"name": "Someone Else"}}]})
    by_name = {name: ok for name, ok, _ in predemo.evaluate(bad, EXP)}
    assert not by_name["FalkorDB graph"]
    assert not by_name["LinkedIn cards on /people"]
    assert not by_name["Top 3 people"]
    assert not by_name["/antifomo response time"]
    no_answer = predemo.evaluate(_data(antifomo_seconds=None), EXP)[-1]
    assert no_answer[1] is False and no_answer[2] == "no answer"


def test_failed_and_direct_rows_do_not_count():
    rows = {n: d for n, _, d in predemo.evaluate(_data(), EXP)}
    assert rows["Bright Data stays"].startswith("21 ")
    assert rows["Bright Data flights (Web Unlocker)"].startswith("34 ")


def test_table_marks_fail():
    out = predemo.table([("a", True, "x"), ("bb", False, "y")])
    assert out.splitlines() == ["OK    a   x", "FAIL  bb  y"]


def test_expected_overrides(monkeypatch):
    monkeypatch.setenv("PREDEMO_TOP3", "A, B ,C")
    monkeypatch.setenv("PREDEMO_FLIGHTS_BD", "12")
    exp = predemo.expected()
    assert exp["top3"] == ["A", "B", "C"] and exp["flights_bd"] == 12


def test_script_stops_with_clear_message_when_falkordb_is_down():
    env = {**os.environ, "FALKORDB_HOST": "127.0.0.1", "FALKORDB_PORT": "1", "DEMO_PORT": "1"}
    started = time.monotonic()
    proc = subprocess.run(["bash", str(ROOT / "scripts" / "predemo.sh")], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2
    assert "FalkorDB does not answer GRAPH.LIST on 127.0.0.1:1" in proc.stdout
    assert "make up" in proc.stdout
    assert "Demo on a reset graph" not in proc.stdout  # nothing started
    assert time.monotonic() - started < 30


def test_check_cli_rejects_bad_usage():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "predemo_check.py")],
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
