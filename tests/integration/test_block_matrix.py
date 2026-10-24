"""Block matrix: classification rules and the reachability section of the Data pipeline panel."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.integration.pipeline_view import BLOCK_MATRIX, reachability

ROOT = Path(__file__).resolve().parents[2]


def _probe_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("block_matrix", ROOT / "scripts/probes/block_matrix.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules["block_matrix"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_classification_uses_the_marker_not_the_page_size() -> None:
    bm = _probe_module()
    big_shell = "<html>" + "x" * 500_000 + "</html>"
    assert bm._classify(200, "<b>Ship It Afterparty</b>", "https://a/", r"Ship It Afterparty")[0] == "ok"
    assert bm._classify(200, big_shell, "https://a/", r"Ship It Afterparty")[0] == "shell_js"
    assert bm._classify(999, "", "https://a/", "MARKER")[0] == "blocked"
    assert bm._classify(429, "", "https://a/", "MARKER")[0] == "blocked"
    assert bm._classify(202, "", "https://a/", "MARKER")[0] == "blocked"
    assert bm._classify(200, "<div id='px-captcha'>", "https://a/", "MARKER")[0] == "blocked"
    assert bm._classify(200, "ok", "https://www.linkedin.com/authwall?x", "MARKER")[0] == "blocked"
    assert bm._classify(500, "", "https://a/", "MARKER")[0] == "error"


def test_site_list_is_derived_from_connectors() -> None:
    bm = _probe_module()
    sites = bm.sites()
    for s in sites:
        assert (ROOT / s.connector.split(",")[0].strip()).exists(), s.connector
        assert s.url.startswith("https://") and s.marker
    names = {s.name for s in sites}
    assert {"Booking", "Airbnb", "Google Flights", "LinkedIn public profile", "Kayak", "Hilton",
            "Google Search (SERP)", "githubuniverse.com"} <= names


def test_reachability_reads_the_last_run(tmp_path: Path) -> None:
    assert reachability(tmp_path / "missing.json") is None
    if BLOCK_MATRIX.exists():
        data = reachability()
        assert data is not None
        raw = json.loads(BLOCK_MATRIX.read_text())
        assert data["counts"] == raw["counts"] and data["run_at"] == raw["run_at"]
        assert len(data["sites"]) == raw["counts"]["n"]
        body = TestClient(create_app(graph_probe=False)).get("/api/v1/pipeline").json()
        assert body["reachability"]["counts"] == raw["counts"]
