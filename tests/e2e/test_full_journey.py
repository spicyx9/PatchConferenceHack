"""Full user journey against the real API process and the real FalkorDB, no mock.

Starts ``scripts/run_demo.py`` (fixture sources, fixture travel) on a free port with its own
graph, walks the demo journey through HTTP, restarts the API process on the same graph and
checks the ranking survives. Opt-in: ``CONFERGE_E2E=1`` (``make e2e``); FalkorDB at
``FALKORDB_HOST:FALKORDB_PORT`` (default 127.0.0.1:6380).

Steps run in file order and share one API process; a failed step leaves the later ones
running on whatever state is there, so each failure points at its own module.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("FALKORDB_HOST", "127.0.0.1")
PORT = int(os.environ.get("FALKORDB_PORT", "6380"))
GRAPH = os.environ.get("CONFERGE_E2E_GRAPH", "conferge_e2e")
GOAL = "founder of an AI dev tool, wants seed investors, AI-agent founders, Copilot PMs"
TRIP = (date(2026, 10, 27), date(2026, 10, 30))
CONF_TZ = ZoneInfo("America/Los_Angeles")
DATA_SOURCES = {"live", "cached", "fixture", "mixed"}
# Enum fields where "unknown" is a declared value, not a placeholder.
ENUM_KEYS = {"status", "conference_relation", "coordinate_precision", "data_source", "source_mode",
             "mode", "precision", "verification", "presence", "participation"}
PLACEHOLDERS = {"", "n/a", "na", "tbd", "tba", "null", "none", "undefined", "nan", "-", "?"}

pytestmark = pytest.mark.skipif(os.environ.get("CONFERGE_E2E") != "1",
                                reason="end-to-end journey: set CONFERGE_E2E=1 (make e2e)")


def _falkordb_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Api:
    """One ``run_demo.py`` process; ``restart`` keeps the graph."""

    def __init__(self) -> None:
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}/api/v1"
        self.proc: subprocess.Popen[bytes] | None = None
        self.log = Path(tempfile.gettempdir()) / f"conferge-e2e-api-{self.port}.log"

    def start(self, keep_graph: bool = False) -> None:
        env = {**os.environ, "FALKORDB_HOST": HOST, "FALKORDB_PORT": str(PORT), "PYTHONUNBUFFERED": "1"}
        cmd = [sys.executable, "scripts/run_demo.py", "--mode", "fixture", "--travel", "fixture",
               "--graph", GRAPH, "--port", str(self.port)] + (["--keep-graph"] if keep_graph else [])
        with self.log.open("ab") as log:
            self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"run_demo.py exited {self.proc.returncode}; see {self.log}")
            try:
                self.call("GET", "/conference")
                return
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.5)
        raise RuntimeError(f"API not ready on port {self.port} after 180 s; see {self.log}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def restart(self) -> None:
        self.stop()
        self.start(keep_graph=True)

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read())


@pytest.fixture(scope="module")
def api() -> Any:
    if not _falkordb_up():
        pytest.fail(f"FalkorDB not reachable at {HOST}:{PORT} (make up, or set FALKORDB_PORT)")
    server = Api()
    if server.log.exists():
        server.log.unlink()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="module")
def journey() -> dict[str, Any]:
    """Values carried from one step to the next."""
    return {}


def envelope(body: dict[str, Any]) -> dict[str, Any]:
    assert body.get("data_source") in DATA_SOURCES, f"data_source {body.get('data_source')!r}"
    assert body.get("status") in {"ok", "degraded", "failed"}, body.get("status")
    assert body.get("collected_at"), "collected_at missing"
    assert datetime.fromisoformat(body["collected_at"]).tzinfo is not None, "collected_at not tz-aware"
    no_placeholders(body)
    return body


def no_placeholders(value: Any, path: str = "$") -> None:
    """Absent facts must be ``null``, never a filler string that looks like data."""
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str) and k not in ENUM_KEYS and k != "warnings":
                low = v.strip().lower()
                assert low not in PLACEHOLDERS and low != "unknown", f"{path}.{k} = {v!r}: expected null"
            no_placeholders(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            no_placeholders(v, f"{path}[{i}]")


def ranking(api: Api) -> list[str]:
    body = envelope(api.call("GET", "/people?limit=100"))
    return [c["person"]["id"] for c in body["items"] if c.get("person")]


def test_01_reset(api: Api) -> None:
    body = envelope(api.call("POST", "/reset", {}))
    assert body["plan"]["days"], "reset returned an empty plan"


def test_02_goal_in_natural_language(api: Api, journey: dict[str, Any]) -> None:
    body = envelope(api.call("POST", "/goal", {"text": GOAL}))
    goals = body["goals"]
    roles = {r for g in goals for r in g.get("target_roles", [])}
    assert {"investor", "founder", "pm"} <= roles, f"goal roles parsed: {sorted(roles)}"
    assert body["goal_text"] == GOAL
    journey["goals"] = [g["id"] for g in goals]


def test_03_discovery_events(api: Api) -> None:
    body = envelope(api.call("GET", "/events"))
    assert body["count"] > 0
    for e in body["items"]:
        assert e["source_url"] or e["evidence"], f"{e['id']}: no provenance"
        for ev in e["evidence"]:
            assert ev["source_url"] and ev["collected_at"], f"{e['id']}: evidence without url/time"
        if e["price_min"] is not None or e["price_max"] is not None:
            assert e["currency"], f"{e['id']}: price without currency"
        if e["start_at"]:
            assert datetime.fromisoformat(e["start_at"]).tzinfo is not None, f"{e['id']}: naive start_at"


def test_04_discovery_people(api: Api) -> None:
    body = envelope(api.call("GET", "/people?limit=100"))
    assert body["count"] > 0
    for card in body["items"]:
        person = card["person"]
        assert person, f"opportunity {card['opportunity']['id']} without person"
        assert person.get("evidence") or person.get("source_url"), f"{person['id']}: no provenance"


def test_05_top5_paths_in_falkordb_with_provenance(api: Api, journey: dict[str, Any]) -> None:
    top = ranking(api)[:5]
    assert len(top) == 5, f"only {len(top)} people ranked"
    journey["top5"] = top
    for pid in top:
        body = envelope(api.call("GET", f"/graph/path?person={urllib.request.quote(pid)}"))
        assert body.get("backend") == "falkordb", f"{pid}: path backend {body.get('backend')!r}"
        edges = [s["edge"] for s in body["path"] if "edge" in s]
        assert edges and body["hops"] == len(edges), f"{pid}: no edge in path"
        assert body["node_ids"][-1] == pid, f"{pid}: path ends at {body['node_ids'][-1]}"
        for e in edges:
            assert e["evidence_source"], f"{pid}: edge {e['id']} without evidence_source"
            # Contract (conferge/graph/schema.py): observed_at is None when the source has no
            # timestamp, never the ingest time. Only user input (goals) has no timestamp.
            if e["observed_at"] is None:
                assert e["evidence_source"] == "user", f"{pid}: edge {e['id']} without observed_at"
            else:
                assert datetime.fromisoformat(e["observed_at"]).tzinfo is not None, e


def test_06_plan_on_trip_days(api: Api, journey: dict[str, Any]) -> None:
    body = envelope(api.call("GET", "/plan"))
    days = [d for d in body["plan"]["days"] if d["items"]]
    assert days, "empty plan"
    for d in days:
        day = date.fromisoformat(d["day"])
        assert TRIP[0] <= day <= TRIP[1], f"plan day {day} outside the trip"
        for item in d["items"]:
            start = datetime.fromisoformat(item["start_at"]).astimezone(CONF_TZ)
            assert start.date() == day, f"{item['event_id']} starts {start} but listed on {day}"
            assert 6 <= start.hour, f"{item['event_id']} starts {start:%H:%M} local"
    journey["plan"] = body["plan"]


def test_07_antifomo_three_categories(api: Api) -> None:
    body = envelope(api.call("GET", "/antifomo"))
    cats = {s["category"] for s in body["skips"]}
    assert {"time_conflict", "travel", "low_score"} <= cats, f"anti-FOMO categories: {sorted(cats)}"
    for s in body["skips"]:
        assert s["reason"] and s["gain"], s


def test_08_simulate_change_on_top_plan_event(api: Api, journey: dict[str, Any]) -> None:
    before = envelope(api.call("GET", "/plan"))["plan"]
    items = [i for d in before["days"] for i in d["items"]]
    top = max(items, key=lambda i: i["score"])
    scenarios = envelope(api.call("GET", "/scenarios"))["items"]
    pick = next((s for s in scenarios if "sold" in s["id"].lower()), scenarios[0] if scenarios else None)
    assert pick, "no scenario"
    body = envelope(api.call("POST", "/simulate-change", {"scenario_id": pick["id"]}))
    assert top["event_id"] in body["changed_events"], (
        f"changed {body['changed_events']}, top plan event is {top['event_id']}")
    diff = body["diff"]
    assert any(diff.get(k) for k in ("added", "removed", "changed")), f"empty diff {diff}"
    assert "simulated change: not a real update from the source" in body["warnings"]


def test_09_met_drops_person_in_ranking(api: Api, journey: dict[str, Any]) -> None:
    before = ranking(api)
    first = before[0]
    body = envelope(api.call("POST", "/met", {"person_id": first, "note": "e2e"}))
    assert body["persisted"] == "falkordb", f"meeting persisted to {body['persisted']!r}"
    assert body["memory_id"], "no memory id returned"
    after = ranking(api)
    assert first not in after[:1], "met person still first"
    assert first not in after or after.index(first) > before.index(first), "met person did not drop"
    journey["after_met"] = after
    journey["met"] = first


def test_10_restart_keeps_ranking(api: Api, journey: dict[str, Any]) -> None:
    assert "after_met" in journey, "step 09 did not produce a ranking"
    api.restart()
    body = envelope(api.call("POST", "/goal", {"text": GOAL}))
    assert body["goals"]
    after = ranking(api)
    assert after == journey["after_met"], (
        f"ranking changed across restart: {journey['met']} at "
        f"{after.index(journey['met']) if journey['met'] in after else 'absent'} after restart, "
        f"{journey['after_met'].index(journey['met']) if journey['met'] in journey['after_met'] else 'absent'} before")
