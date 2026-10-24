"""Venues of the demo plan through the Bright Data Google Maps dataset (gd_m8ebnr0q2qlklc02fz).

Method from github.com/yaronbeen/bright-data-google-maps-scraper: "discover by location" inputs
``{keyword, lat, long, zoom_level, country}``; output fields read with aliases (name/title,
address/full_address, latitude/lat, longitude/lon/lng, rating/totalScore,
reviews_count/reviewsCount, website/open_website, place_id/placeId/fid).

One collection per run: one trigger (at most 20 inputs), ``/snapshot`` polled every 2 s, 180 s
timeout. Each venue gets the best name match among the records of its own input; no match means
every place field is null. Nothing is estimated.

Graph writes go through ``GraphStore.merge_node("Venue", ...)`` only and never overwrite a non-null
property: name/address/latitude/longitude are filled only when null; the Google Maps values are
kept in their own ``google_maps_*`` properties with provider, dataset_id, snapshot_id, collected_at.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATASET_ID = "gd_m8ebnr0q2qlklc02fz"
PROVIDER = "brightdata:google_maps"
MAX_VENUES = 15
MAX_INPUTS = 20
POLL_SECONDS = 2.0
TIMEOUT_SECONDS = 180.0
ZOOM = 16
CITY_ZOOM = 12
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "venues.json"
PLACE_FIELDS = ("name", "address", "lat", "lng", "rating", "reviews_count", "website", "place_id")


def _fold(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip()) if value not in (None, "") else None
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    mult = 1
    if text[-1:] in ("K", "k"):
        mult, text = 1_000, text[:-1]
    elif text[-1:] in ("M", "m"):
        mult, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * mult)
    except ValueError:
        return None


def plan_venues(plan: dict[str, Any], events: list[dict[str, Any]], conference: dict[str, Any],
                limit: int = MAX_VENUES) -> list[dict[str, Any]]:
    """Fort Mason first, then the venues of the side events kept in the plan, deduplicated by name + city.

    ``plan`` is ``GET /plan`` (``plan.days[].items[]``), ``events`` the items of ``GET /events``,
    ``conference`` the ``conference`` object of ``GET /conference``. Sessions at the conference
    venue are covered by its entry.
    """
    from conferge.graph.schema import venue_id

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str | None, address: str | None, city: str | None,
            lat: float | None, lng: float | None, event_ids: list[str]) -> None:
        if not name:
            return
        key = (_fold(name), _fold(city))
        if key in seen:
            for v in out:
                if (_fold(v["query_name"]), _fold(v["city"])) == key:
                    v["event_ids"] = sorted(set(v["event_ids"]) | set(event_ids))
            return
        if len(out) >= limit:
            return
        seen.add(key)
        out.append({"venue_id": venue_id(name, address, city), "query_name": name, "address": address,
                    "city": city, "lat": lat, "lng": lng, "event_ids": sorted(event_ids)})

    add(conference.get("venue_name"), conference.get("address"), conference.get("city"),
        conference.get("latitude"), conference.get("longitude"), [])
    by_id = {e["id"]: e for e in events}
    planned = [i["event_id"] for d in plan.get("days", []) for i in d.get("items", [])]
    for eid in planned:
        event = by_id.get(eid)
        if not event or event.get("event_type") == "session" or event.get("conference_relation") == "official":
            continue
        venue = event.get("venue") or {}
        add(venue.get("name"), venue.get("address"), venue.get("city") or conference.get("city"),
            venue.get("latitude"), venue.get("longitude"), [eid])
    return out


def inputs_for(venues: list[dict[str, Any]], conference: dict[str, Any]) -> list[dict[str, Any]]:
    """Discover-by-location inputs: the venue name near its known point (else the conference)."""
    out = []
    for v in venues[:MAX_INPUTS]:
        lat = v["lat"] if v["lat"] is not None else conference.get("latitude")
        lng = v["lng"] if v["lng"] is not None else conference.get("longitude")
        keyword = " ".join(p for p in (v["query_name"], v["city"]) if p)
        # Own point known: search close (ZOOM); else around the conference at city scale.
        zoom = ZOOM if v["lat"] is not None and v["lng"] is not None else CITY_ZOOM
        out.append({"keyword": keyword, "lat": lat, "long": lng, "zoom_level": zoom, "country": "US"})
    return out


def normalize(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _first(record, "name", "title"),
        "address": _first(record, "address", "full_address"),
        "lat": _float(_first(record, "latitude", "lat")),
        "lng": _float(_first(record, "longitude", "lon", "long", "lng")),
        "rating": _float(_first(record, "rating", "totalScore")),
        "reviews_count": _int(_first(record, "reviews_count", "reviewsCount")),
        "website": _first(record, "website", "open_website"),
        "place_id": _first(record, "place_id", "placeId", "fid"),
    }


def _same_word(a: str, b: str) -> bool:
    return a == b or (len(a) > 3 and len(b) > 3 and (a.startswith(b) or b.startswith(a)))  # coffee/coffees


def _name_score(query: str, found: str | None) -> float:
    """Share of the query's words found in the place name; 0 unless the first (distinctive) word matches."""
    q, f = _fold(query).split(), _fold(found).split()
    if not q or not f or not any(_same_word(q[0], w) for w in f):
        return 0.0
    return sum(any(_same_word(t, w) for w in f) for t in q) / len(q)


def _input_keyword(record: dict[str, Any]) -> str | None:
    raw = record.get("input")
    return raw.get("keyword") if isinstance(raw, dict) else None


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    p1, p2 = radians(lat1), radians(lat2)
    h = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(h))


MAX_DISTANCE_M = 500


def _pick(venue: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """One place for the venue, or None with the reason. Never a guess between branches."""
    city = _fold(venue["city"])
    in_city = [c for c in candidates if not city or city in _fold(c["address"])]
    if not in_city:
        return None, "no result in the venue's city"
    if venue["lat"] is not None and venue["lng"] is not None:
        located = [(c, _distance_m(venue["lat"], venue["lng"], c["lat"], c["lng"]))
                   for c in in_city if c["lat"] is not None and c["lng"] is not None]
        near = sorted((d, i) for i, (c, d) in enumerate(located) if d <= MAX_DISTANCE_M)
        if near:
            return located[near[0][1]][0], f"nearest branch to the known point ({near[0][0]:.0f} m)"
        return None, f"no result within {MAX_DISTANCE_M} m of the known point"
    if len(in_city) == 1:
        return in_city[0], "single result in the venue's city"
    return None, f"ambiguous: {len(in_city)} results in the venue's city, no known point to choose"


def match(venues: list[dict[str, Any]], records: list[dict[str, Any]], *, snapshot_id: str | None,
          collected_at: str, min_score: float = 0.5) -> list[dict[str, Any]]:
    """Best record per venue: name match, same city, then the known point or a single result.

    No match, an ambiguous chain with several branches, or a dataset error for that input
    leaves every place field null, with the reason in ``match_reason``.
    """
    usable = [r for r in records if isinstance(r, dict) and not (r.get("error") or r.get("error_code"))]
    failed = {_input_keyword(r) for r in records if isinstance(r, dict) and (r.get("error") or r.get("error_code"))}
    out = []
    for venue in venues:
        keyword = " ".join(p for p in (venue["query_name"], venue["city"]) if p)
        same_input = [r for r in usable if _input_keyword(r) == keyword] or usable
        candidates = [n for n in (normalize(r) for r in same_input)
                      if _name_score(venue["query_name"], n["name"]) >= min_score]
        best, reason = _pick(venue, candidates) if candidates else (None, "no matching name")
        if best is None and keyword in failed:
            reason = "dataset error for this input"
        place = best or dict.fromkeys(PLACE_FIELDS)
        out.append({
            "venue_id": venue["venue_id"], "query_name": venue["query_name"], "city": venue["city"],
            "event_ids": venue["event_ids"], "found": best is not None, "match_reason": reason,
            **place, "provider": PROVIDER, "dataset_id": DATASET_ID, "snapshot_id": snapshot_id,
            "collected_at": collected_at,
        })
    return out


async def collect(client: Any, venues: list[dict[str, Any]], conference: dict[str, Any], *,
                  poll_seconds: float = POLL_SECONDS, timeout: float = TIMEOUT_SECONDS,
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One trigger, poll /snapshot until ready or timeout. Returns (raw records, run info)."""
    started = datetime.now(timezone.utc)
    inputs = inputs_for(venues, conference)
    snapshot_id = await client.trigger_dataset(DATASET_ID, inputs, method="discover_by_location",
                                               limit_per_input=5)
    deadline = time.monotonic() + timeout
    status, records = "running", []
    while time.monotonic() < deadline:
        out = await client.snapshot_results(snapshot_id)
        if out.status == "ready":
            data = out.data
            records = data if isinstance(data, list) else ([] if data is None else [data])
            status = "ready"
            break
        await asyncio.sleep(poll_seconds)
    finished = datetime.now(timezone.utc)
    return records, {"snapshot_id": snapshot_id, "status": status, "inputs": len(inputs),
                     "started_at": started.isoformat(), "finished_at": finished.isoformat(),
                     "records": len(records)}


async def read_snapshot(client: Any, snapshot_id: str, inputs: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read an already triggered snapshot (no new collection): progress, then its records if ready."""
    progress = await client.snapshot_progress(snapshot_id)
    records: list[dict[str, Any]] = []
    status = progress.get("status") or "unknown"
    if status == "ready":
        out = await client.snapshot_results(snapshot_id)
        data = out.data
        records = data if isinstance(data, list) else ([] if data is None else [data])
    now = datetime.now(timezone.utc).isoformat()
    return records, {"snapshot_id": snapshot_id, "status": status, "inputs": inputs,
                     "started_at": None, "finished_at": now, "records": len(records),
                     "note": "read after the 180 s polling window; same single collection"}


def write_cache(entries: list[dict[str, Any]], run: dict[str, Any], path: Path = CACHE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": PROVIDER, "dataset_id": DATASET_ID, "run": run,
                                "venues": entries}, indent=1, ensure_ascii=False) + "\n")
    return path


def load_cache(path: Path = CACHE) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


_GM_PROPS = {"address": "google_maps_address", "lat": "google_maps_latitude", "lng": "google_maps_longitude",
             "rating": "google_maps_rating", "reviews_count": "google_maps_reviews_count",
             "website": "google_maps_website", "place_id": "google_maps_place_id",
             "name": "google_maps_name"}


def write_graph(store: Any, entries: list[dict[str, Any]]) -> dict[str, int]:
    """Fill Venue nodes through GraphStore MERGE; a non-null property is never overwritten."""
    from conferge.graph.queries import run_read

    written = skipped = 0
    for e in entries:
        if not e.get("found") or not e.get("venue_id"):
            skipped += 1
            continue
        rows = run_read(store, "MATCH (v:Venue {id: $id}) RETURN properties(v)", {"id": e["venue_id"]})
        existing = rows[0][0] if rows and rows[0] else {}
        props: dict[str, Any] = {}
        for key, gm_key in _GM_PROPS.items():
            if e.get(key) is not None and existing.get(gm_key) is None:
                props[gm_key] = e[key]
        for key, graph_key in (("name", "name"), ("address", "address"), ("lat", "latitude"),
                               ("lng", "longitude")):
            if e.get(key) is not None and existing.get(graph_key) is None:
                props[graph_key] = e[key]
        for key in ("dataset_id", "snapshot_id", "collected_at"):
            if e.get(key) is not None and existing.get(f"google_maps_{key}") is None:
                props[f"google_maps_{key}"] = e[key]
        if existing.get("google_maps_provider") is None:
            props["google_maps_provider"] = PROVIDER
        if not existing and e.get("city") is not None:
            props.setdefault("city", e["city"])
        if props:
            store.merge_node("Venue", e["venue_id"], props)
            written += 1
    return {"written": written, "skipped_not_found": skipped}


def apply_to_events(events: list[Any], entries: list[dict[str, Any]]) -> tuple[list[Any], int]:
    """Google Maps coordinates take priority over fixture ones for travel times, labelled by evidence."""
    from conferge.core.schemas import SourceEvidence

    by_event = {eid: e for e in entries if e.get("found") and e.get("lat") is not None
                and e.get("lng") is not None for eid in e["event_ids"]}
    out, changed = [], 0
    for event in events:
        e = by_event.get(event.id)
        if e is None or event.venue is None:
            out.append(event)
            continue
        venue = event.venue.model_copy(update={"latitude": e["lat"], "longitude": e["lng"],
                                               "coordinate_precision": "exact"})
        evidence = [*event.evidence, SourceEvidence(
            provider=PROVIDER, source_mode="cached", source_url=None,
            collected_at=datetime.fromisoformat(e["collected_at"]),
            source_record_id=e.get("place_id"), raw_ref=e.get("snapshot_id"),
            confidence=None)]
        out.append(event.model_copy(update={"venue": venue, "evidence": evidence}))
        changed += 1
    return out, changed


def run_report(cache: dict[str, Any]) -> Any:
    """RunReport of the cached collection, for the Data pipeline panel (no call)."""
    from conferge.core.schemas import RunReport

    run, venues = cache.get("run") or {}, cache.get("venues") or []
    found = sum(1 for v in venues if v.get("found"))
    finished = datetime.fromisoformat(run.get("finished_at") or venues[0]["collected_at"])
    started = datetime.fromisoformat(run["started_at"]) if run.get("started_at") else finished
    ready = run.get("status") == "ready"
    errors = [] if ready else [f"snapshot {run.get('snapshot_id')} {run.get('status')} after the polling window"]
    if ready and found < len(venues):
        errors.append(f"{len(venues) - found} of {len(venues)} venues not found: their fields stay null")
    return RunReport(
        provider=PROVIDER, started_at=started, finished_at=finished,
        status="ok" if ready and found == len(venues) else ("degraded" if ready else "failed"),
        termination="exhausted" if ready else "error", source_mode="cached",
        fetched_count=max(int(run.get("records") or 0), found), unique_count=found,
        expected_count=len(venues), errors=errors,
    )
