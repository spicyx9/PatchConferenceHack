"""Named, read-only Cypher traversals over the opportunity graph.

Every query is a module-level constant with ``$parameters`` only (no value
interpolation) and is sent with ``GRAPH.RO_QUERY`` when the client supports it,
so FalkorDB itself rejects any accidental write. Each function returns
``{"rows": [...], "paths": [...]}`` where a path is ``{nodes[], edges[]}``
ready for cytoscape and for ``conferge.graph.explain.path_to_text``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from conferge.core.store import GraphQuery, GraphStore
from conferge.graph.paths import GraphResult, SerializedPath, path_key, serialize_node, serialize_path

PATH_CAP = 200

# -- people_for_goal: multi-hop (2 to 4) goal -> topic -> event -> person ------------
Q_PEOPLE_VIA_SPEAKER = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(:Event)<-[:SPEAKS_AT]-(person:Person) RETURN person.id, p LIMIT $cap"
)
Q_PEOPLE_VIA_HOST = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(:Event)<-[:HOSTS]-(person:Person) RETURN person.id, p LIMIT $cap"
)
Q_PEOPLE_VIA_HOST_COMPANY = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(:Event)<-[:HOSTS]-(:Company)<-[:WORKS_AT]-(person:Person) "
    "RETURN person.id, p LIMIT $cap"
)
Q_PEOPLE_VIA_ATTENDANCE = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(:Event)<-[:ATTENDS_CONFIRMED]-(person:Person) RETURN person.id, p LIMIT $cap"
)
Q_PEOPLE_VIA_COMPANY_TOPIC = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(:Company)<-[:WORKS_AT]-(person:Person) RETURN person.id, p LIMIT $cap"
)
Q_PEOPLE_VIA_TOPIC = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(person:Person) RETURN person.id, p LIMIT $cap"
)
Q_PEOPLE_BY_ROLE = (
    "MATCH (g:Goal {id: $goal_id, user_id: $user_id}), (person:Person) "
    "WHERE size(g.target_roles) > 0 AND any(r IN person.roles WHERE r IN g.target_roles) "
    "RETURN person.id, [r IN person.roles WHERE r IN g.target_roles] LIMIT $cap"
)
Q_GOAL = "MATCH (g:Goal {id: $goal_id, user_id: $user_id}) RETURN g.priority, g.description"
Q_PERSON_NAMES = "MATCH (p:Person) WHERE p.id IN $ids RETURN p.id, p.name, p.title, p.roles"

# -- events_for_goal ---------------------------------------------------------------
Q_EVENTS_FOR_GOAL = (
    "MATCH p = (g:Goal {id: $goal_id, user_id: $user_id})-[:ABOUT]->(:Topic)"
    "<-[:ABOUT]-(e:Event) RETURN e.id, e.title, e.start_at, e.status, p LIMIT $cap"
)
Q_EVENT_PEOPLE = (
    "MATCH (e:Event)<-[r:SPEAKS_AT|HOSTS|ATTENDS_CONFIRMED]-(person:Person) "
    "WHERE e.id IN $ids RETURN e.id, person.id, type(r)"
)

# -- conflicts ---------------------------------------------------------------------
Q_CONFLICTS = (
    "MATCH (a:Event)-[:PART_OF]->(c:Conference {id: $conference_id})<-[:PART_OF]-(b:Event) "
    "WHERE a.id < b.id AND a.start_ts IS NOT NULL AND a.end_ts IS NOT NULL "
    "AND b.start_ts IS NOT NULL AND b.end_ts IS NOT NULL "
    "AND a.start_ts < b.end_ts AND a.end_ts > b.start_ts "
    "OPTIONAL MATCH (a)-[:LOCATED_AT]->(va:Venue) "
    "OPTIONAL MATCH (b)-[:LOCATED_AT]->(vb:Venue) "
    "RETURN a.id, a.title, a.start_at, a.end_at, b.id, b.title, b.start_at, b.end_at, "
    "va.name, va.latitude, va.longitude, vb.name, vb.latitude, vb.longitude"
)
Q_UNTIMED_EVENTS = (
    "MATCH (e:Event)-[:PART_OF]->(:Conference {id: $conference_id}) "
    "WHERE e.start_ts IS NULL OR e.end_ts IS NULL RETURN e.id, e.title"
)

# -- explanations / memory ---------------------------------------------------------
# Explicit, bounded path signatures tried in order (no generic shortestPath): the first
# signature that matches gives the explanation, so the "why" is always the strongest
# kind of evidence and reads the same way every time.
_GOAL_TOPIC = "MATCH p = (g:Goal {user_id: $user_id})-[:ABOUT]->(:Topic)"
_TO_PERSON = "(person:Person {id: $person_id}) RETURN g.id, length(p), p ORDER BY length(p) LIMIT $cap"
Q_PATH_SPEAKER = f"{_GOAL_TOPIC}<-[:ABOUT]-(:Event)<-[:SPEAKS_AT]-{_TO_PERSON}"
Q_PATH_ATTENDEE = f"{_GOAL_TOPIC}<-[:ABOUT]-(:Event)<-[:ATTENDS_CONFIRMED]-{_TO_PERSON}"
Q_PATH_HOST_COMPANY = f"{_GOAL_TOPIC}<-[:ABOUT]-(:Event)<-[:HOSTS]-(:Company)<-[:WORKS_AT]-{_TO_PERSON}"
Q_PATH_COMPANY_TOPIC = f"{_GOAL_TOPIC}<-[:ABOUT]-(:Company)<-[:WORKS_AT]-{_TO_PERSON}"
# Additional signatures after the four above (decision: keep Luma/Partiful hosts, a person's
# own topics and the planner's opportunities explainable instead of returning no path).
Q_PATH_HOST = f"{_GOAL_TOPIC}<-[:ABOUT]-(:Event)<-[:HOSTS]-{_TO_PERSON}"
Q_PATH_PERSON_TOPIC = f"{_GOAL_TOPIC}<-[:ABOUT]-{_TO_PERSON}"
Q_PATH_OPPORTUNITY = (
    "MATCH p = (g:Goal {user_id: $user_id})<-[:SERVES_GOAL]-(:Opportunity)-[:INVOLVES]->"
    + _TO_PERSON
)
PATH_SIGNATURES = (
    ("speaker", Q_PATH_SPEAKER), ("attendance", Q_PATH_ATTENDEE),
    ("host_company", Q_PATH_HOST_COMPANY), ("company_topic", Q_PATH_COMPANY_TOPIC),
    ("host", Q_PATH_HOST), ("topic", Q_PATH_PERSON_TOPIC), ("opportunity", Q_PATH_OPPORTUNITY),
)
Q_PEOPLE_MET_BEFORE = (
    "MATCH p = (m:Meeting {user_id: $user_id})-[:MET|INVOLVES]->(person:Person) "
    "RETURN person.id, person.name, m.kind, m.at, p"
)
Q_COMPANY_COVERAGE = (
    "MATCH (person:Person)-[:WORKS_AT]->(c:Company {id: $company_id}) "
    "OPTIONAL MATCH (m:Meeting {user_id: $user_id})-[:MET|INVOLVES]->(person) "
    "RETURN person.id, person.name, person.title, collect(m.kind)"
)

# -- replanning --------------------------------------------------------------------
Q_REPLAN_PEOPLE = (
    "MATCH p = (e:Event {id: $event_id})<-[:SPEAKS_AT|HOSTS|ATTENDS_CONFIRMED]-(:Person) "
    "RETURN p LIMIT $cap"
)
Q_REPLAN_OPPORTUNITIES = (
    "MATCH p = (e:Event {id: $event_id})<-[:INVOLVES]-(:Opportunity) RETURN p LIMIT $cap"
)
Q_REPLAN_SAME_PEOPLE_ELSEWHERE = (
    "MATCH p = (e:Event {id: $event_id})<-[:SPEAKS_AT|HOSTS|ATTENDS_CONFIRMED]-(:Person)"
    "-[:SPEAKS_AT|HOSTS|ATTENDS_CONFIRMED]->(alt:Event) "
    "WHERE alt.id <> e.id AND (alt.status IS NULL OR NOT alt.status IN ['cancelled', 'sold_out']) "
    "RETURN alt.id, alt.title, p LIMIT $cap"
)
Q_REPLAN_SAME_TOPIC = (
    "MATCH p = (e:Event {id: $event_id})-[:ABOUT]->(:Topic)<-[:ABOUT]-(alt:Event) "
    "WHERE alt.id <> e.id AND (alt.status IS NULL OR NOT alt.status IN ['cancelled', 'sold_out']) "
    "RETURN alt.id, alt.title, p LIMIT $cap"
)

# -- UI ----------------------------------------------------------------------------
Q_UI_NODES = (
    "MATCH (c:Conference {id: $conference_id})-[*0..3]-(n) "
    "WITH DISTINCT n WHERE $kinds IS NULL OR labels(n)[0] IN $kinds "
    "RETURN n LIMIT $limit"
)
Q_UI_EDGES = (
    "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids "
    "RETURN a.id, type(r), b.id, properties(r)"
)
Q_NODE_COUNTS = "MATCH (n) RETURN labels(n)[0], count(n)"
Q_EDGE_COUNTS = "MATCH ()-[r]->() RETURN type(r), count(r)"

READ_QUERIES = {name: value for name, value in globals().items() if name.startswith("Q_")}

# Path kind -> base weight; speaking is the strongest public signal, a shared
# topic alone the weakest. Confirmed attendance requires evidence at ingest.
PATH_WEIGHTS = {
    "speaker": 1.0, "attendance": 0.8, "host": 0.9, "host_company": 0.7,
    "company_topic": 0.5, "topic": 0.4, "role": 0.6,
}
UNKNOWN_CONFIDENCE = 0.5  # an edge without confidence is not certain
UNKNOWN_CONFIDENCE_FLAG = "unknown_confidence"


def _graph(target: GraphStore | GraphQuery) -> GraphQuery:
    return target.graph if isinstance(target, GraphStore) else target


def run_read(target: GraphStore | GraphQuery, query: str,
             params: dict[str, Any] | None = None) -> list[list[Any]]:
    graph = _graph(target)
    runner = getattr(graph, "ro_query", None) or graph.query
    result = runner(query, params=params or {})
    return list(getattr(result, "result_set", None) or [])


def _dedup(paths: list[SerializedPath]) -> list[SerializedPath]:
    seen: dict[tuple[str, ...], SerializedPath] = {}
    for path in paths:
        seen.setdefault(path_key(path), path)
    return list(seen.values())


def _path_confidence(path: SerializedPath) -> float:
    """Weakest edge; a missing confidence counts as 0.5 and flags the path."""
    values = [e["props"].get("confidence") for e in path["edges"]]
    if any(not isinstance(v, (int, float)) for v in values):
        flags = path.setdefault("flags", [])
        if UNKNOWN_CONFIDENCE_FLAG not in flags:
            flags.append(UNKNOWN_CONFIDENCE_FLAG)
    scored = [float(v) if isinstance(v, (int, float)) else UNKNOWN_CONFIDENCE for v in values]
    return min(scored) if scored else UNKNOWN_CONFIDENCE


def root_source(path: SerializedPath) -> str:
    """Evidence root of a path: provenance of the edge that reaches the person."""
    for edge in reversed(path["edges"]):
        props = edge["props"]
        if props.get("source") or props.get("source_url"):
            return f"{props.get('source') or 'unknown'}|{props.get('source_url') or ''}"
    return "unknown"


def combine_by_source(contributions: list[tuple[str, float]]) -> float:
    """Max per root source, then noisy-OR across distinct sources: 1 - prod(1 - s).

    Three paths read off the same page are one piece of evidence; two independent
    sources raise the score with diminishing returns and never above 1.
    """
    best: dict[str, float] = {}
    for source, score in contributions:
        best[source] = max(best.get(source, 0.0), min(max(score, 0.0), 1.0))
    remaining = 1.0
    for score in best.values():
        remaining *= 1.0 - score
    return 1.0 - remaining


def _excluded_people(target: GraphStore | GraphQuery, user_id: str) -> set[str]:
    rows = run_read(target, Q_PEOPLE_MET_BEFORE, {"user_id": user_id})
    return {row[0] for row in rows if row[2] in {"MET", "CONTACTED"}}


def people_for_goal(target: GraphStore | GraphQuery, user_id: str, goal_id: str,
                    limit: int = 10, *, include_met: bool = False) -> GraphResult:
    params = {"goal_id": goal_id, "user_id": user_id, "cap": PATH_CAP}
    goal_rows = run_read(target, Q_GOAL, params)
    if not goal_rows:
        return {"rows": [], "paths": []}
    priority = float(goal_rows[0][0]) if goal_rows[0][0] is not None else 1.0
    excluded = set() if include_met else _excluded_people(target, user_id)

    contributions: dict[str, list[tuple[str, float]]] = defaultdict(list)
    reasons: dict[str, list[str]] = defaultdict(list)
    person_paths: dict[str, list[tuple[str, SerializedPath]]] = defaultdict(list)
    for kind, query in (("speaker", Q_PEOPLE_VIA_SPEAKER), ("attendance", Q_PEOPLE_VIA_ATTENDANCE),
                        ("host_company", Q_PEOPLE_VIA_HOST_COMPANY),
                        ("company_topic", Q_PEOPLE_VIA_COMPANY_TOPIC),
                        ("host", Q_PEOPLE_VIA_HOST), ("topic", Q_PEOPLE_VIA_TOPIC)):
        for person_id, raw_path in run_read(target, query, params):
            if person_id in excluded:
                continue
            path = serialize_path(raw_path)
            if path_key(path) in {path_key(p) for _, p in person_paths[person_id]}:
                continue
            person_paths[person_id].append((kind, path))
            contributions[person_id].append(
                (root_source(path), PATH_WEIGHTS[kind] * _path_confidence(path)))
            reasons[person_id].append(kind)
    for person_id, matched_roles in run_read(target, Q_PEOPLE_BY_ROLE, params):
        if person_id in excluded:
            continue
        contributions[person_id].append(("person_record:roles", PATH_WEIGHTS["role"]))
        reasons[person_id].append(f"role:{','.join(matched_roles)}")
    scores = {pid: combine_by_source(c) for pid, c in contributions.items()}

    ranked = sorted(scores, key=lambda pid: (-scores[pid], pid))[:limit]
    names = {row[0]: row[1:] for row in run_read(target, Q_PERSON_NAMES, {"ids": ranked})}
    rows = []
    paths: list[SerializedPath] = []
    for person_id in ranked:
        name, title, roles = names.get(person_id, (None, None, None))
        # Strongest evidence first (speaker before shared topic), then shortest.
        best = [path for _, path in sorted(
            person_paths[person_id], key=lambda kp: (-PATH_WEIGHTS[kp[0]], len(kp[1]["edges"])))]
        rows.append({
            "person_id": person_id, "name": name, "title": title, "roles": roles or [],
            "score": round(scores[person_id] * priority, 4),
            "reasons": sorted(set(reasons[person_id])),
            "path_count": len(person_paths[person_id]),
            "sources": sorted({src for src, _ in contributions[person_id]}),
            "unknown_confidence": any(UNKNOWN_CONFIDENCE_FLAG in p.get("flags", [])
                                      for _, p in person_paths[person_id]),
            "shortest_hops": min((len(p["edges"]) for p in best), default=None),
        })
        paths.extend(best)
    return {"rows": rows, "paths": paths}


def events_for_goal(target: GraphStore | GraphQuery, user_id: str, goal_id: str,
                    limit: int = 20) -> GraphResult:
    params = {"goal_id": goal_id, "user_id": user_id, "cap": PATH_CAP}
    events: dict[str, dict[str, Any]] = {}
    paths: list[SerializedPath] = []
    for event_id, title, start_at, status, raw_path in run_read(target, Q_EVENTS_FOR_GOAL, params):
        row = events.setdefault(event_id, {"event_id": event_id, "title": title,
                                           "start_at": start_at, "status": status,
                                           "topic_paths": 0})
        row["topic_paths"] += 1
        paths.append(serialize_path(raw_path))
    targets = {r["person_id"] for r in people_for_goal(target, user_id, goal_id, 50)["rows"]}
    present: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    if events:
        for event_id, person_id, rel in run_read(target, Q_EVENT_PEOPLE, {"ids": list(events)}):
            present[event_id][rel].add(person_id)
    for event_id, row in events.items():
        everyone = set().union(*present[event_id].values()) if present[event_id] else set()
        row["target_people"] = sorted(everyone & targets)
        row["target_people_count"] = len(row["target_people"])
        row["presence_basis"] = {rel: sorted(ids) for rel, ids in present[event_id].items()}
    rows = sorted(events.values(), key=lambda r: (-r["target_people_count"],
                                                   -r["topic_paths"], r["event_id"]))[:limit]
    keep = {r["event_id"] for r in rows}
    return {"rows": rows,
            "paths": _dedup([p for p in paths if p["nodes"][-1]["id"] in keep])}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(a))))


def conflicts(target: GraphStore | GraphQuery, conference_id: str) -> GraphResult:
    """Overlapping event pairs. Events without both start and end are listed as
    ``unverifiable`` rather than assumed to overlap or not."""
    params = {"conference_id": conference_id}
    rows: list[dict[str, Any]] = []
    for (a_id, a_title, a_start, a_end, b_id, b_title, b_start, b_end,
         va_name, va_lat, va_lon, vb_name, vb_lat, vb_lon) in run_read(target, Q_CONFLICTS, params):
        distance = None
        if None not in (va_lat, va_lon, vb_lat, vb_lon):
            distance = _haversine_m(va_lat, va_lon, vb_lat, vb_lon)
        rows.append({
            "kind": "overlap",
            "a": {"id": a_id, "title": a_title, "start_at": a_start, "end_at": a_end,
                  "venue": va_name},
            "b": {"id": b_id, "title": b_title, "start_at": b_start, "end_at": b_end,
                  "venue": vb_name},
            "distance_m": distance,
        })
    for event_id, title in run_read(target, Q_UNTIMED_EVENTS, params):
        rows.append({"kind": "unverifiable", "a": {"id": event_id, "title": title},
                     "reason": "missing start or end time"})
    return {"rows": rows, "paths": []}


def path_user_to_person(target: GraphStore | GraphQuery, user_id: str, person_id: str,
                        limit: int = 3) -> GraphResult:
    """Paths of the first matching signature in PATH_SIGNATURES order; empty if none."""
    params = {"user_id": user_id, "person_id": person_id, "cap": limit}
    for signature, query in PATH_SIGNATURES:
        found = run_read(target, query, params)
        if not found:
            continue
        rows, paths = [], []
        for goal_id, length, raw_path in found:
            path = serialize_path(raw_path)
            rows.append({"goal_id": goal_id, "hops": length, "signature": signature,
                         "confidence": _path_confidence(path)})
            paths.append(path)
        return {"rows": rows, "paths": paths}
    return {"rows": [], "paths": []}


def people_met_before(target: GraphStore | GraphQuery, user_id: str) -> GraphResult:
    rows, paths = [], []
    for person_id, name, kind, at, raw_path in run_read(
        target, Q_PEOPLE_MET_BEFORE, {"user_id": user_id}
    ):
        rows.append({"person_id": person_id, "name": name, "kind": kind, "at": at})
        paths.append(serialize_path(raw_path))
    return {"rows": rows, "paths": paths}


def company_coverage(target: GraphStore | GraphQuery, user_id: str,
                     company_id: str) -> GraphResult:
    met, remaining = [], []
    for person_id, name, title, kinds in run_read(
        target, Q_COMPANY_COVERAGE, {"user_id": user_id, "company_id": company_id}
    ):
        entry = {"person_id": person_id, "name": name, "title": title,
                 "memory": sorted(k for k in kinds if k)}
        (met if {"MET", "CONTACTED"} & set(entry["memory"]) else remaining).append(entry)
    return {"rows": [{"company_id": company_id, "met": met, "remaining": remaining}],
            "paths": []}


def replan_after_change(target: GraphStore | GraphQuery, event_id: str,
                        change: dict[str, Any]) -> GraphResult:
    """What a change on ``event_id`` (e.g. ``{"status": "sold_out"}``) impacts.

    Read-only: the caller records the change through ingestion; this only
    reports impacted people, opportunities and alternatives with their paths.
    """
    params = {"event_id": event_id, "cap": PATH_CAP}
    impacted_people = [serialize_path(p) for (p,) in run_read(target, Q_REPLAN_PEOPLE, params)]
    impacted_opps = [serialize_path(p) for (p,) in run_read(target, Q_REPLAN_OPPORTUNITIES, params)]
    alternatives: dict[str, dict[str, Any]] = {}
    alt_paths: list[SerializedPath] = []
    for reason, query in (("same_people", Q_REPLAN_SAME_PEOPLE_ELSEWHERE),
                          ("same_topic", Q_REPLAN_SAME_TOPIC)):
        for alt_id, alt_title, raw_path in run_read(target, query, params):
            alt = alternatives.setdefault(alt_id, {"event_id": alt_id, "title": alt_title,
                                                   "reasons": []})
            if reason not in alt["reasons"]:
                alt["reasons"].append(reason)
            alt_paths.append(serialize_path(raw_path))
    rows = [{
        "event_id": event_id, "change": change,
        "impacted_people": sorted({p["nodes"][-1]["id"] for p in impacted_people}),
        "impacted_opportunities": sorted({p["nodes"][-1]["id"] for p in impacted_opps}),
        "alternatives": sorted(alternatives.values(),
                               key=lambda a: (-len(a["reasons"]), a["event_id"])),
    }]
    return {"rows": rows, "paths": _dedup(impacted_people + impacted_opps + alt_paths)}


def graph_for_ui(target: GraphStore | GraphQuery, conference_id: str, limit: int = 400,
                 kinds: list[str] | None = None) -> GraphResult:
    """Subgraph within 3 hops of the conference as one ``{nodes, edges}`` path."""
    nodes = [serialize_node(n) for (n,) in run_read(
        target, Q_UI_NODES, {"conference_id": conference_id, "limit": limit, "kinds": kinds})]
    ids = [n["id"] for n in nodes]
    edges = [{"source": a, "target": b, "type": rel, "props": dict(props or {})}
             for a, rel, b, props in run_read(target, Q_UI_EDGES, {"ids": ids})] if ids else []
    return {"rows": [{"node_count": len(nodes), "edge_count": len(edges),
                      "truncated": len(nodes) >= limit}],
            "paths": [{"nodes": nodes, "edges": edges}]}


def graph_counts(target: GraphStore | GraphQuery) -> dict[str, dict[str, int]]:
    return {
        "nodes": {label: count for label, count in run_read(target, Q_NODE_COUNTS)},
        "edges": {rel: count for rel, count in run_read(target, Q_EDGE_COUNTS)},
    }
