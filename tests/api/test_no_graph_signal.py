"""``make demo DEMO_ARGS=--no-graph`` must show its degraded ranking, not a silent fixture badge.

Rehearsal bug 4: run_demo served the app with graph probing on, so a FalkorDB left running from
an earlier session answered the ranking from a graph that was never loaded, and the UI showed no
signal. The launcher now builds the app with ``graph_probe=False`` under ``--no-graph``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

import conferge.api.app  # noqa: F401 - its module-level app probes once at import, before the spy below
from conferge.api import providers
from conferge.api.data import load_fixture

ROOT = Path(__file__).resolve().parents[2]


def _run_demo():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("run_demo", ROOT / "scripts" / "run_demo.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_no_graph_serves_a_visible_degraded_ranking_even_when_a_graph_answers(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def never_called():  # type: ignore[no-untyped-def]
        calls.append("connect_store")
        return None

    monkeypatch.setattr(providers, "connect_store", never_called)
    client = TestClient(_run_demo().build_app(load_fixture(), no_graph=True))
    body = client.get("/api/v1/plan").json()
    assert body["data_source"] == "degraded_no_graph" and body["status"] == "degraded"
    assert body["ranking_mode"] == "degraded_no_graph"
    assert any(w.startswith("degraded_no_graph") for w in body["warnings"])
    assert calls == []  # no probe: a leftover FalkorDB must not rank a graph that was never loaded
    assert client.get("/health").json()["graph_up"] is False
    html = client.get("/").text
    assert 'id="degraded-banner"' in html and 'data-ranking-mode="degraded_no_graph"' in html


def test_with_graph_the_launcher_probes_falkordb(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    probed: list[str] = []
    monkeypatch.setattr(providers, "connect_store", lambda: probed.append("x"))
    client = TestClient(_run_demo().build_app(load_fixture(), no_graph=False))
    client.get("/api/v1/plan")
    assert probed  # the normal path still asks the graph
