"""Bright Data LinkedIn enrichment for the demo's people (saved snapshots first, one collection).

Targets: the best ranked speakers plus event hosts of ``fixtures/people.json`` that already
carry a public ``linkedin_url``; nobody is matched by name here. Profiles come first from
saved files in ``data/probes/`` (existing snapshots downloaded with ``GET
/datasets/v3/snapshot/<id>?format=json`` -> ``linkedin_<id>.json``, then earlier collections).
Only targets that no saved file covers go to one new ``POST /datasets/v3/scrape`` on dataset
``gd_l1viktl72bvl7bjuj0`` (at most 20 inputs per request, 2 retries on 429/5xx, 120 s), saved
to ``linkedin_<ts>.json``. These files hold public profiles of real people: never committed.

What a profile may change, and nothing else:

* ``identity_confidence``: 1.0 when the profile confirms name and company, 0.7 name only,
  unchanged otherwise (a profile whose name does not match writes nothing at all);
* ``headline`` and ``company`` on the Person node, with provenance (provider, dataset_id,
  snapshot_id, source_url, collected_at);
* a ``WORKS_AT`` edge to the profile's company (Company node created when absent). An
  existing edge keeps its provenance (source, verification, source_mode, observed_at,
  confidence): LinkedIn is added as corroboration (``evidence_sources``, ``linkedin_*``) and
  only raises its ``identity_confidence``.

A LinkedIn profile proves nothing about presence at an event: no ATTENDS edge is written
and ``presence_confidence`` is never touched.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from conferge.core.schemas import Company, Person, RunReport

PROVIDER = "brightdata:linkedin"
DATASET_ID = "gd_l1viktl72bvl7bjuj0"
ENDPOINT = "/datasets/v3/scrape"
MAX_INPUTS_PER_REQUEST = 20
RETRIES = 2
TIMEOUT_S = 120.0
NEW_COLLECTION_MIN_MISSING = 4  # a new collection only when more than 3 targets are missing
ROOT = Path(__file__).resolve().parents[2]
PEOPLE_FIXTURE = ROOT / "fixtures" / "people.json"
PROBE_DIR = ROOT / "data" / "probes"
POOL_MAX_AGE = timedelta(hours=24)
_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "gmbh", "sas",
                     "sa", "plc", "limited", "incorporated"}


@dataclass(frozen=True)
class LinkedInProfile:
    """The fields kept from one dataset record, with the provenance of that record."""

    linkedin_url: str
    name: str | None = None
    headline: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    about: str | None = None
    followers: int | None = None
    snapshot_id: str | None = None
    collected_at: str | None = None
    source_mode: str = "live"


@dataclass
class Collection:
    """One Bright Data answer (a scrape call or a snapshot download), never more."""

    status: str  # ok / degraded / failed
    collected_at: datetime
    inputs: list[str]
    kind: str = "collection"  # "snapshot": an existing snapshot downloaded
    records: list[dict[str, Any]] = field(default_factory=list)
    snapshot_id: str | None = None
    http_status: int | None = None
    requests: int = 0
    cost: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    source_mode: str = "live"
    path: Path | None = None


@dataclass
class WriteReport:
    persons_written: list[str] = field(default_factory=list)
    companies_created: list[str] = field(default_factory=list)
    works_at: list[tuple[str, str]] = field(default_factory=list)
    """Every WORKS_AT the run touched: created or corroborated."""
    works_at_corroborated: list[tuple[str, str]] = field(default_factory=list)
    """Existing edges that kept their provenance and got LinkedIn as extra evidence."""


# -- targets ------------------------------------------------------------------------------

def fixture_hosts(path: Path = PEOPLE_FIXTURE) -> list[Person]:
    """Hosts of ``fixtures/people.json`` (presence kind ``host``), file order."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Person.model_validate(p["person"]) for p in raw.get("profiles", [])
            if any(pr.get("kind") == "host" for pr in p.get("presences", []))]


def select_targets(ranked_ids: Iterable[str], people: Iterable[Person],
                   hosts: Iterable[Person], *, speakers: int = 10,
                   host_count: int = 5) -> list[Person]:
    """Top ``speakers`` ranked speakers with a linkedin_url, then ``host_count`` hosts with one."""
    by_id = {p.id: p for p in people}
    picked: list[Person] = []
    for pid in ranked_ids:
        if len(picked) == speakers:
            break
        person = by_id.get(pid)
        if person and person.participation == "confirmed_speaker" and person.linkedin_url \
                and person not in picked:
            picked.append(person)
    seen = {p.id for p in picked}
    picked += [h for h in hosts if h.linkedin_url and h.id not in seen][:host_count]
    return picked


def missing(targets: Iterable[Person], pool: dict[str, LinkedInProfile]) -> list[Person]:
    """Targets whose canonical linkedin_url has no saved profile."""
    return [t for t in targets if _canon(str(t.linkedin_url)) not in pool]


def profiles_for(targets: Iterable[Person], pool: dict[str, LinkedInProfile]) -> list[LinkedInProfile]:
    return [pr for t in targets if (pr := pool.get(_canon(str(t.linkedin_url)) or ""))]


# -- Bright Data calls --------------------------------------------------------------------

def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return [data] if isinstance(data, dict) else []


def _finish(out: Collection) -> Collection:
    bad = [r for r in out.records if r.get("error")]
    out.errors += [f"record error: {r.get('error_code') or r.get('error')}" for r in bad]
    good = len(out.records) - len(bad)
    out.status = "ok" if good and not out.errors else "degraded" if good else "failed"
    return out


class _Session:
    """BrightDataClient on our own httpx client: 120 s timeout, 2 retries, headers observed."""

    def __init__(self, out: Collection, http_client: httpx.AsyncClient | None,
                 api_key: str | None, timeout_s: float) -> None:
        from conferge.core.brightdata import BrightDataClient
        from conferge.core.settings import env_value

        self.out = out
        self.own = http_client is None
        self.http = http_client or httpx.AsyncClient(base_url="https://api.brightdata.com",
                                                     timeout=timeout_s)
        self.http.event_hooks["response"] = [*self.http.event_hooks.get("response", []),
                                             self._remember]
        key = api_key if api_key is not None else (env_value("BRIGHTDATA_API_KEY") or None)
        self.client = BrightDataClient(key, client=self.http, retries=RETRIES)

    async def _remember(self, response: httpx.Response) -> None:
        self.out.requests += 1
        self.out.http_status = response.status_code
        self.out.cost.update({k: v for k, v in response.headers.items()
                              if re.search(r"cost|price|charge|billing|credit", k, re.I)})

    async def close(self) -> None:
        if self.own:
            await self.http.aclose()


async def download_snapshot(snapshot_id: str, *, http_client: httpx.AsyncClient | None = None,
                            api_key: str | None = None, timeout_s: float = TIMEOUT_S) -> Collection:
    """``GET /datasets/v3/snapshot/<id>?format=json`` of an existing snapshot (no new collection)."""
    from conferge.core.brightdata import BrightDataError

    out = Collection(status="failed", collected_at=datetime.now(timezone.utc), inputs=[],
                     kind="snapshot", snapshot_id=snapshot_id)
    session = _Session(out, http_client, api_key, timeout_s)
    try:
        if reason := session.client.not_ready("datasets"):
            out.errors.append(reason)
            return out
        res = await session.client.snapshot_results(snapshot_id)
        if res.status == "running":
            out.errors.append(f"snapshot {snapshot_id} still running")
            return out
        out.records = _rows(res.data)
    except BrightDataError as exc:
        out.errors.append(f"GET /datasets/v3/snapshot/{snapshot_id}: {exc}")
        return out
    finally:
        await session.close()
    out.inputs = [u for r in out.records if (u := _record_url(r))]
    return _finish(out)


async def collect(urls: list[str], *, http_client: httpx.AsyncClient | None = None,
                  api_key: str | None = None, timeout_s: float = TIMEOUT_S) -> Collection:
    """One collection: ``ceil(len(urls) / 20)`` scrape requests and no other loop.

    A 202 (snapshot still running) is followed by reads of that same snapshot until
    ``timeout_s`` is spent; no input is ever sent twice. Response headers that look like
    cost or credit information are kept as returned (Bright Data may send none).
    """
    from conferge.core.brightdata import BrightDataError

    out = Collection(status="failed", collected_at=datetime.now(timezone.utc), inputs=list(urls))
    if not urls:
        out.errors.append("no target with a linkedin_url")
        return out
    session = _Session(out, http_client, api_key, timeout_s)
    deadline = time.monotonic() + timeout_s
    try:
        if reason := session.client.not_ready("datasets"):
            out.errors.append(reason)
            return out
        for start in range(0, len(urls), MAX_INPUTS_PER_REQUEST):
            batch = urls[start:start + MAX_INPUTS_PER_REQUEST]
            try:
                res = await session.client.scrape_dataset(
                    DATASET_ID, [{"url": u} for u in batch], limit_per_input=None)
                out.snapshot_id = res.snapshot_id or out.snapshot_id
                while res.status == "running" and res.snapshot_id:
                    if time.monotonic() >= deadline:
                        raise BrightDataError(
                            f"snapshot {res.snapshot_id} not ready after {timeout_s:.0f}s")
                    await asyncio.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
                    res = await session.client.snapshot_results(res.snapshot_id)
                out.records += _rows(res.data)
            except BrightDataError as exc:
                out.errors.append(f"{ENDPOINT} ({len(batch)} inputs): {exc}")
    finally:
        await session.close()
    return _finish(out)


# -- saved files --------------------------------------------------------------------------

def save(collection: Collection, directory: Path = PROBE_DIR) -> Path:
    """Every record as returned: ``linkedin_<snapshot_id>.json`` or ``linkedin_<ts>.json``."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = (collection.snapshot_id if collection.kind == "snapshot"
            else collection.collected_at.strftime("%Y%m%dT%H%M%SZ"))
    path = directory / f"linkedin_{stem}.json"
    body = {k: v for k, v in asdict(collection).items() if k not in {"path", "source_mode"}}
    body.update(provider=PROVIDER, dataset_id=DATASET_ID, collected_at=collection.collected_at.isoformat(),
                endpoint=(f"GET /datasets/v3/snapshot/{collection.snapshot_id}?format=json"
                          if collection.kind == "snapshot" else f"POST {ENDPOINT}"))
    if collection.kind == "snapshot":
        body["collected_at_note"] = ("download time; per-record collection time is the "
                                     "record's own timestamp when Bright Data returns one")
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    collection.path = path
    return path


def load_pool(directory: Path = PROBE_DIR, *, now: datetime | None = None,
              max_age: timedelta = POOL_MAX_AGE) -> dict[str, LinkedInProfile]:
    """canonical linkedin_url -> saved profile, labelled ``cached``.

    Files younger than ``max_age`` only; downloaded snapshots win over collections, then
    the newest file wins.
    """
    now = now or datetime.now(timezone.utc)
    bodies = []
    for path in directory.glob("linkedin_*.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        if now - datetime.fromisoformat(body["collected_at"]) <= max_age:
            bodies.append(body)
    snapshots = [b for b in bodies if b.get("kind") == "snapshot"]
    others = sorted((b for b in bodies if b.get("kind") != "snapshot"),
                    key=lambda b: b["collected_at"], reverse=True)
    pool: dict[str, LinkedInProfile] = {}
    for body in [*snapshots, *others]:
        for record in body["records"]:
            profile = profile_from_record(record, snapshot_id=body.get("snapshot_id"),
                                          collected_at=body["collected_at"], source_mode="cached")
            if profile and profile.linkedin_url not in pool:
                pool[profile.linkedin_url] = profile
    return pool


# -- mapping and identity -----------------------------------------------------------------

def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _canon(url: str | None) -> str | None:
    """Canonical profile URL, slug lowercased: Bright Data echoes slugs with another case."""
    from conferge.people.linkedin import canonical_profile_url

    canon = canonical_profile_url(url) if url else None
    return canon.lower() if canon else None


def _record_url(record: dict[str, Any]) -> str | None:
    given = record.get("input") if isinstance(record.get("input"), dict) else {}
    return (_canon(_str(given.get("url"))) or _canon(_str(record.get("input_url")))
            or _canon(_str(record.get("url"))))


def profile_from_record(record: dict[str, Any], *, snapshot_id: str | None = None,
                        collected_at: str | None = None,
                        source_mode: str = "live") -> LinkedInProfile | None:
    """Keep name, headline, title, company, location, url, about, followers when present."""
    if record.get("error"):
        return None
    url = _record_url(record)
    if not url:
        return None
    current = record.get("current_company") if isinstance(record.get("current_company"), dict) else {}
    jobs = record.get("experience") if isinstance(record.get("experience"), list) else []
    job = jobs[0] if jobs and isinstance(jobs[0], dict) else {}
    followers = record.get("followers")
    return LinkedInProfile(
        linkedin_url=url,
        name=_str(record.get("name")),
        headline=_str(record.get("headline")) or _str(record.get("position")),
        title=_str(current.get("title")) or _str(job.get("title")),
        company=(_str(current.get("name")) or _str(record.get("current_company_name"))
                 or _str(job.get("company"))),
        location=_str(record.get("city")) or _str(record.get("location")),
        about=_str(record.get("about")),
        followers=followers if isinstance(followers, int) else None,
        snapshot_id=snapshot_id,
        collected_at=_str(record.get("timestamp")) or collected_at,
        source_mode=source_mode,
    )


def _tokens(text: str, drop: frozenset[str] | set[str] = frozenset()) -> list[str]:
    from conferge.people.taxonomy import fold

    return [w for w in re.findall(r"[a-z0-9]+", fold(text)) if w not in drop]


def name_matches(person_name: str, profile_name: str | None) -> bool:
    """Same first and last name tokens (accents, case, middle names and initials ignored).

    An abbreviated last name ("Kaush G.") does not confirm "Kaush Ganguly".
    """
    a = [t for t in _tokens(person_name) if len(t) > 1]
    b = [t for t in _tokens(profile_name or "") if len(t) > 1]
    return bool(a and b) and a[0] == b[0] and a[-1] == b[-1]


def company_matches(known: str | None, profile_company: str | None) -> bool:
    """One name is the other, or a whole-word run inside it (legal suffixes ignored)."""
    a, b = _tokens(known or "", _COMPANY_SUFFIXES), _tokens(profile_company or "", _COMPANY_SUFFIXES)
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return any(long_[i:i + len(short)] == short for i in range(len(long_) - len(short) + 1))


def identity_confidence(person: Person, known_company: str | None,
                        profile: LinkedInProfile) -> float | None:
    if not name_matches(person.name, profile.name):
        return person.identity_confidence
    return 1.0 if company_matches(known_company, profile.company) else 0.7


# -- writes -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Enrichment:
    person_id: str
    profile: LinkedInProfile
    identity_confidence: float | None
    company_id: str | None


def match(people: Iterable[Person], companies: Iterable[Company],
          profiles: Iterable[LinkedInProfile]) -> tuple[list[Enrichment], list[str]]:
    """Pair profiles with people by canonical linkedin_url; a name mismatch writes nothing."""
    from conferge.events.official.normalize import company_id

    names = {c.id: c.name for c in companies}
    by_url = {_canon(str(p.linkedin_url)): p for p in people if p.linkedin_url}
    done: list[Enrichment] = []
    unmatched: list[str] = []
    for profile in profiles:
        person = by_url.get(profile.linkedin_url)
        if person is None or not name_matches(person.name, profile.name):
            unmatched.append(profile.linkedin_url)
            continue
        known = names.get(person.company_id) if person.company_id else None
        # The person's own company when LinkedIn names it: never a duplicate Company node.
        same = company_matches(known, profile.company)
        done.append(Enrichment(
            person_id=person.id, profile=profile,
            identity_confidence=identity_confidence(person, known, profile),
            company_id=person.company_id if same else (
                company_id(profile.company) if profile.company else None)))
    return done, unmatched


def _company_exists(store: Any, company_id: str) -> bool:
    from conferge.graph.queries import run_read

    return bool(run_read(store, "MATCH (c:Company {id: $id}) RETURN c.id", {"id": company_id}))


def _works_at(store: Any, person_id: str, company_id: str) -> dict[str, Any] | None:
    from conferge.graph.queries import run_read

    rows = run_read(store, "MATCH (:Person {id: $p})-[r:WORKS_AT]->(:Company {id: $c}) "
                    "RETURN properties(r)", {"p": person_id, "c": company_id})
    return dict(rows[0][0]) if rows else None


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _corroboration(existing: dict[str, Any], e: Enrichment) -> dict[str, Any]:
    """LinkedIn added to an existing WORKS_AT: provenance (source, verification, source_mode,
    observed_at, confidence, title) is never written; evidence grows, identity only rises."""
    pr = e.profile
    sources = [str(x) for x in existing.get("evidence_sources") or [existing.get("source")] if x]
    first = PROVIDER not in sources
    props: dict[str, Any] = {
        "evidence_sources": [*sources, PROVIDER] if first else sources,
        "linkedin_verification": "linkedin_profile", "linkedin_snapshot_id": pr.snapshot_id,
        "linkedin_observed_at": pr.collected_at, "linkedin_source_url": pr.linkedin_url,
        "linkedin_source_mode": pr.source_mode, "linkedin_title": pr.title,
    }
    # The demo reload rewrites evidence_count from the person record (1): it never stays
    # below the number of distinct sources, and LinkedIn counts once.
    count = int(existing.get("evidence_count") or 0)
    wanted = count + 1 if first else max(count, len(sources))
    if wanted != count:
        props["evidence_count"] = wanted
    known = existing.get("identity_confidence")
    if e.identity_confidence is not None and (known is None or e.identity_confidence > known):
        props["identity_confidence"] = e.identity_confidence
    props = _clean(props)
    if "snapshot_id" in existing:  # written on the edge by the first version, now linkedin_*
        props["snapshot_id"] = None
    return props


def write(store: Any, enrichments: Iterable[Enrichment]) -> WriteReport:
    """Person headline/company/identity_confidence + WORKS_AT, through GraphStore MERGE only."""
    report = WriteReport()
    for e in enrichments:
        pr = e.profile
        store.merge_node("Person", e.person_id, _clean({
            "identity_confidence": e.identity_confidence, "headline": pr.headline,
            "company": pr.company, "provider": PROVIDER, "dataset_id": DATASET_ID,
            "snapshot_id": pr.snapshot_id, "linkedin_source_url": pr.linkedin_url,
            "linkedin_collected_at": pr.collected_at, "linkedin_source_mode": pr.source_mode}))
        report.persons_written.append(e.person_id)
        if not e.company_id:
            continue
        if not _company_exists(store, e.company_id):
            store.merge_node("Company", e.company_id, _clean({
                "name": pr.company, "source": PROVIDER, "source_mode": pr.source_mode,
                "observed_at": pr.collected_at}))
            report.companies_created.append(e.company_id)
        existing = _works_at(store, e.person_id, e.company_id)
        if existing is not None:
            props = _corroboration(existing, e)
            report.works_at_corroborated.append((e.person_id, e.company_id))
        else:
            props = _clean({
                "verification": "linkedin_profile", "source": PROVIDER,
                "source_mode": pr.source_mode, "title": pr.title,
                "confidence": e.identity_confidence, "identity_confidence": e.identity_confidence,
                "observed_at": pr.collected_at, "evidence_sources": [PROVIDER],
                "evidence_count": 1, "linkedin_snapshot_id": pr.snapshot_id,
                "linkedin_source_url": pr.linkedin_url})
        store.merge_edge("Person", e.person_id, "WORKS_AT", "Company", e.company_id, props)
        report.works_at.append((e.person_id, e.company_id))
    return report


def apply_to_people(people: list[Person], enrichments: Iterable[Enrichment]) -> list[Person]:
    """In-memory copy: only identity_confidence changes on the Person model."""
    conf = {e.person_id: e.identity_confidence for e in enrichments}
    return [p.model_copy(update={"identity_confidence": conf[p.id]}) if p.id in conf else p
            for p in people]


def cards(enrichments: Iterable[Enrichment]) -> dict[str, dict[str, Any]]:
    """person_id -> the LinkedIn evidence shown on a /people card."""
    return {e.person_id: {
        "provider": PROVIDER, "dataset_id": DATASET_ID, "snapshot_id": e.profile.snapshot_id,
        "source_mode": e.profile.source_mode, "source_url": e.profile.linkedin_url,
        "collected_at": e.profile.collected_at,
        "headline": e.profile.headline, "company": e.profile.company,
        "identity_confidence": e.identity_confidence,
    } for e in enrichments}


def run_report(started: datetime, *, targets: int, written: int, source_mode: str,
               errors: list[str]) -> RunReport:
    status = "failed" if not written else "degraded" if errors or written < targets else "ok"
    return RunReport(provider=PROVIDER, started_at=started,
                     finished_at=max(datetime.now(timezone.utc), started), status=status,
                     termination="exhausted" if status == "ok" else "error",
                     source_mode=source_mode,  # type: ignore[arg-type]
                     fetched_count=targets, unique_count=written, errors=errors)


# -- one enrichment run -------------------------------------------------------------------

@dataclass
class EnrichResult:
    targets: list[Person]
    from_files: int
    absent_before: list[Person]
    collection: Collection | None
    enrichments: list[Enrichment]
    unmatched: list[str]
    absent_after: list[Person]
    written: WriteReport | None
    source_mode: str
    errors: list[str]


async def enrich(targets: list[Person], companies: Iterable[Company], store: Any | None, *,
                 allow_collect: bool, directory: Path = PROBE_DIR) -> EnrichResult:
    """Saved profiles first; one collection for the absent targets only if more than 3."""
    pool = load_pool(directory)
    absent = missing(targets, pool)
    from_files = len(targets) - len(absent)
    collection = None
    if allow_collect and len(absent) >= NEW_COLLECTION_MIN_MISSING:
        collection = await collect([str(p.linkedin_url) for p in absent])
        save(collection, directory)
        for r in collection.records:
            if pr := profile_from_record(r, snapshot_id=collection.snapshot_id,
                                         collected_at=collection.collected_at.isoformat()):
                pool.setdefault(pr.linkedin_url, pr)
    absent_after = missing(targets, pool)
    enrichments, unmatched = match(targets, companies, profiles_for(targets, pool))
    written = write(store, enrichments) if store is not None and enrichments else None
    errors = [*(collection.errors if collection else []),
              *([f"{len(absent_after)} targets without a profile"] if absent_after else [])]
    return EnrichResult(targets=targets, from_files=from_files, absent_before=absent,
                        collection=collection, enrichments=enrichments, unmatched=unmatched,
                        absent_after=absent_after, written=written,
                        source_mode="live" if collection and collection.records else "cached",
                        errors=errors)
