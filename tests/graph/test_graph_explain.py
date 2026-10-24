"""Deterministic path -> text explanations on hand-built serialized paths."""

from __future__ import annotations

from typing import Any

from conferge.graph.explain import path_to_text


def _node(node_id: str, label: str, **props: Any) -> dict[str, Any]:
    return {"id": node_id, "label": label, "props": props}


def _edge(source: str, target: str, rel: str, **props: Any) -> dict[str, Any]:
    return {"source": source, "target": target, "type": rel, "props": props}


def test_speaker_path_names_title_and_local_time():
    path = {
        "nodes": [_node("p1", "Person", name="Ada Speaker"),
                  _node("e1", "Event", title="Agents Keynote",
                        start_at="2026-10-28T21:00:00+00:00", timezone="America/Los_Angeles")],
        "edges": [_edge("p1", "e1", "SPEAKS_AT")],
    }
    text = path_to_text(path)
    assert "Ada Speaker" in text
    assert "'Agents Keynote'" in text
    assert "Oct 28 14:00 PDT" in text
    assert not text.startswith("[fixture]")


def test_event_without_start_says_time_not_published():
    path = {
        "nodes": [_node("p1", "Person", name="Ada"), _node("e1", "Event", title="Breakfast")],
        "edges": [_edge("p1", "e1", "HOSTS")],
    }
    assert "time not published" in path_to_text(path)


def test_candidate_part_of_is_marked_unconfirmed():
    path = {
        "nodes": [_node("e1", "Event", title="Mixer"),
                  _node("c1", "Conference", name="GitHub Universe")],
        "edges": [_edge("e1", "c1", "PART_OF", relation="candidate")],
    }
    text = path_to_text(path)
    assert "candidate (unconfirmed)" in text
    assert "GitHub Universe" in text


def test_fixture_source_mode_prefix():
    path = {
        "nodes": [_node("p1", "Person", name="Fixture Alice", source="fixture:w08",
                        source_mode="fixture"),
                  _node("e1", "Event", title="[FIXTURE] Talk", source_mode="fixture")],
        "edges": [_edge("p1", "e1", "SPEAKS_AT", source_mode="fixture")],
    }
    text = path_to_text(path)
    assert text.startswith("[fixture] ")
    assert "fixture:w08/fixture" in text


def test_live_source_has_no_fixture_prefix():
    path = {
        "nodes": [_node("p1", "Person", name="Ada", source="luma", source_mode="live"),
                  _node("e1", "Event", title="Talk")],
        "edges": [_edge("p1", "e1", "SPEAKS_AT")],
    }
    text = path_to_text(path)
    assert not text.startswith("[fixture]")
    assert "luma/live" in text


def test_empty_path_returns_empty_string():
    assert path_to_text({"nodes": [], "edges": []}) == ""
    assert path_to_text({"nodes": [_node("p1", "Person", name="Ada")], "edges": []}) == ""
