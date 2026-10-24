"""Deterministic path -> sentence explanations (no LLM).

Only facts present on the path are verbalized: a missing time reads as
"time not published", a candidate side event is called a candidate, and any
fixture-sourced element prefixes the sentence with ``[fixture]``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from conferge.graph.paths import PathNode, SerializedPath

_RELATION_PHRASE = {
    "official": "an official session of",
    "confirmed_side_event": "a confirmed side event of",
    "candidate": "a candidate (unconfirmed) side event around",
    "unknown": "linked, with an unknown relation, to",
}


def _name(node: PathNode) -> str:
    props = node["props"]
    return str(props.get("name") or props.get("title") or node["id"])


def _when(node: PathNode) -> str:
    start = node["props"].get("start_at")
    if not start:
        return " (time not published)"
    try:
        moment = datetime.fromisoformat(str(start))
        tz_name = node["props"].get("timezone")
        if tz_name:
            moment = moment.astimezone(ZoneInfo(str(tz_name)))
        label = moment.strftime("%b %d %H:%M") + " " + (moment.tzname() or "")
    except (ValueError, ZoneInfoNotFoundError):
        return f" (starts {start})"
    return f" on {label.strip()}"


def _quoted(node: PathNode) -> str:
    return f"'{_name(node)}'"


def _phrase(rel: str, src: PathNode, dst: PathNode, props: dict[str, Any]) -> str:
    if rel == "ABOUT":
        inferred = " (inferred from text)" if props.get("verification") == "keyword_match" else ""
        if src["label"] == "Goal":
            return f"your goal {_quoted(src)} targets {_name(dst)}"
        if src["label"] == "Person":
            return f"{_name(src)} works on {_name(dst)}{inferred}"
        return f"{_quoted(src)} is about {_name(dst)}{inferred}"
    if rel == "SPEAKS_AT":
        return f"{_name(src)} speaks at {_quoted(dst)}{_when(dst)}"
    if rel == "HOSTS":
        return f"{_name(src)} hosts {_quoted(dst)}{_when(dst)}"
    if rel == "WORKS_AT":
        title = props.get("title")
        return f"{_name(src)} works at {_name(dst)}" + (f" as {title}" if title else "")
    if rel == "ATTENDS_CONFIRMED":
        return f"{_name(src)} is publicly listed as attending {_quoted(dst)}"
    if rel == "PART_OF":
        phrase = _RELATION_PHRASE.get(str(props.get("relation")), "part of")
        return f"{_quoted(src)} is {phrase} {_name(dst)}"
    if rel == "LOCATED_AT":
        return f"{_quoted(src)} takes place at {_name(dst)}"
    if rel == "NEAR":
        meters = props.get("distance_m")
        return f"{_name(src)} is near {_name(dst)}" + (f" ({meters} m)" if meters else "")
    if rel == "MET":
        return f"you already met {_name(dst)}"
    if rel == "INVOLVES":
        return f"{_name(src)} involves {_name(dst)}"
    if rel == "SERVES_GOAL":
        return f"{_name(src)} serves goal {_quoted(dst)}"
    if rel == "EXHIBITS_AT":
        return f"{_name(src)} is a {props.get('role') or 'exhibitor'} at {_name(dst)}"
    return f"{_name(src)} {rel.lower()} {_name(dst)}"


def path_sources(path: SerializedPath) -> list[str]:
    seen: dict[str, None] = {}
    for item in [*path["nodes"], *path["edges"]]:
        props = item["props"]
        if props.get("source") or props.get("source_mode"):
            seen[f"{props.get('source') or 'unknown'}/{props.get('source_mode') or 'unknown'}"] = None
    return list(seen)


def path_to_text(path: SerializedPath) -> str:
    nodes = {n["id"]: n for n in path["nodes"]}
    parts = []
    for edge in path["edges"]:
        src, dst = nodes.get(edge["source"]), nodes.get(edge["target"])
        if src is None or dst is None:
            continue
        parts.append(_phrase(edge["type"], src, dst, edge["props"]))
    if not parts:
        return ""
    sentence = "; ".join(parts)
    sentence = sentence[0].upper() + sentence[1:] + "."
    sources = path_sources(path)
    if any(s.endswith("/fixture") for s in sources):
        sentence = "[fixture] " + sentence
    return sentence + (f" Sources: {', '.join(sources)}." if sources else "")
