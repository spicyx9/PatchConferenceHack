"""FastAPI demo app: versioned JSON endpoints plus the one-page UI in ``static/``.

Every response carries ``data_source`` (live | cached | fixture | mixed |
unknown), ``status``, ``collected_at`` and ``warnings``. Fixture data is never
reported as live. Run with ``uv run uvicorn conferge.api.app:app``.
"""

from __future__ import annotations

import copy
import platform
import subprocess
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from conferge.api import logic, providers
from conferge.api.data import DemoData, load_fixture
from conferge.api.provenance import source_of
from conferge.extras.router import router as calendar_router
from conferge.flights.round_trip_total import display as rt_display
from conferge.core.schemas import AgentContext, Goal, Opportunity

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_STATUS_RANK = {"ok": 0, "degraded": 1, "failed": 2}


class GoalRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    conference_id: str | None = None
    user_id: str = "demo-user"


class MetRequest(BaseModel):
    person_id: str
    note: str | None = Field(default=None, max_length=1000)


class EventAction(BaseModel):
    event_id: str


class SkipAction(EventAction):
    reason: Literal["conflict", "not_interested", "cancelled"] = "not_interested"


class ScenarioRequest(BaseModel):
    scenario_id: str


class ProposalRequest(BaseModel):
    proposal_id: str


class DemoState:
    """In-memory session state; FalkorDB persistence is attempted for MET."""

    def __init__(self, data: DemoData, found: providers.Providers, graph_probe: bool) -> None:
        self.pristine = data
        self.providers = found
        self.graph_probe = graph_probe
        self.reset()
        self.restore_memory()

    def restore_memory(self) -> int:
        """Meetings already recorded in FalkorDB survive an API restart (they live in the graph).

        Reads the user's MET Meeting nodes (person, note, time); nothing is written. Returns how
        many were restored; 0 without a graph. ``POST /reset`` deletes them on purpose.
        """
        store = self.store()
        if store is None:
            return 0
        try:
            from conferge.graph.queries import run_read

            rows = run_read(store, "MATCH (m:Meeting {user_id: $user_id, kind: 'MET'})-[:MET]->(p:Person) "
                                   "RETURN p.id, m.note, m.at ORDER BY m.at", {"user_id": USER_ID})
        except Exception:  # noqa: BLE001 - no graph memory: the process starts empty, as before
            return 0
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != 3:
                continue  # not a Meeting row: nothing to restore
            person_id, note, at = row
            if not isinstance(person_id, str) or self.data.person(person_id) is None:
                continue
            self.met[person_id] = note or ""
            if at:
                try:
                    self.met_at[person_id] = datetime.fromisoformat(str(at))
                except ValueError:
                    pass
        self.invalidate()
        return len(self.met)

    def reset(self) -> None:
        self.data = copy.deepcopy(self.pristine)
        self.goal_text = self.data.demo_goal_text
        self.goals: list[Goal] = logic.parse_goals(self.goal_text)
        self.met: dict[str, str] = {}
        self.met_at: dict[str, datetime] = {}
        self.attended: set[str] = set()
        self.skipped: set[str] = set()
        self.accepted: set[str] = set()
        self.scenario_id: str | None = None
        self.simulated_events: set[str] = set()  # event ids rewritten by /simulate-change
        self.agent_mode: str | None = None
        self.agent_opportunities: list[Opportunity] | None = None
        self.agent_warnings: list[str] = []
        self.rank_mode: str | None = None  # "graph" or DEGRADED_NO_GRAPH, set by _ranking()
        self.rank_seconds: float | None = None  # wall time of the last uncached ranking
        self.rank_warnings: list[str] = []
        self._rank_cache: tuple[list[Opportunity], dict[str, float]] | None = None
        self._synced_goals: tuple[str, ...] | None = None

    def invalidate(self) -> None:
        """Drop the cached ranking: goals, memory or the graph changed."""
        self._rank_cache = None

    def store(self) -> Any | None:
        return providers.connect_store() if self.graph_probe else None

    def _graph_ranking(self) -> tuple[list[Opportunity], dict[str, float]] | None:
        """people_for_goal / events_for_goal in FalkorDB; None when the graph is unavailable."""
        store = self.store()
        if store is None:
            self.rank_warnings = ["FalkorDB not reachable"]
            return None
        try:
            from conferge.graph import ranking
            from conferge.graph.ingest import GraphIngestor

            ids = tuple((g.id, g.stated_at) for g in self.goals)
            if self._synced_goals != ids:  # goals live in the graph, written through GraphStore
                GraphIngestor(store, default_mode="live").ingest_goals(USER_ID, self.goals)
                self._synced_goals = ids
            known = {p.id for p in self.data.people}
            people = [o for o in ranking.rank_people(store, USER_ID, self.goals)
                      if set(o.person_ids) <= known]
            return people, ranking.event_scores(store, USER_ID, self.goals, people)
        except Exception as exc:  # noqa: BLE001 - graph down mid-request: degraded, visibly
            self.rank_warnings = [f"FalkorDB ranking failed: {type(exc).__name__}"]
            return None

    def _ranking(self) -> tuple[list[Opportunity], dict[str, float]]:
        if self._rank_cache is not None:
            return self._rank_cache
        started = time.perf_counter()
        try:
            return self._compute_ranking()
        finally:
            self.rank_seconds = round(time.perf_counter() - started, 3)

    def _compute_ranking(self) -> tuple[list[Opportunity], dict[str, float]]:
        graph = self._graph_ranking()
        if graph is not None:
            self.rank_mode = "graph"
            self.rank_warnings = ["ranking computed from FalkorDB traversals (people_for_goal, events_for_goal)"]
            self._rank_cache = graph
            return graph
        # Degraded fallback only: the graph did not answer. Python ranking, labelled as such.
        self.rank_mode = DEGRADED_NO_GRAPH
        self.rank_warnings = [*self.rank_warnings,
                              "degraded_no_graph: ranking computed in Python without FalkorDB"]
        if self.agent_opportunities:
            met = set(self.met)
            people = sorted(self.agent_opportunities,
                            key=lambda o: (bool(set(o.person_ids) & met), -o.score, o.id))
        else:
            people = logic.rank_people(self.data, self.goals, self.met)
        self._rank_cache = (people, logic.event_scores(self.data, self.goals, people))
        return self._rank_cache

    def opportunities(self) -> list[Opportunity]:
        return self._ranking()[0]

    def event_scores(self) -> dict[str, float]:
        return self._ranking()[1]

    def plan(self) -> dict[str, Any]:
        return logic.build_plan(
            self.data, self.goals, self.opportunities(),
            skipped=self.skipped, attended=self.attended, scores=self.event_scores(),
        )


USER_ID = "demo-user"
DEGRADED_NO_GRAPH = "degraded_no_graph"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _envelope(
    state: DemoState, domains: list[str], payload: dict[str, Any],
    *, extra_warnings: list[str] | None = None, mode_override: str | None = None,
) -> dict[str, Any]:
    slices = [state.data.domains[d] for d in domains if d in state.data.domains]
    modes = {mode_override} if mode_override else {s.source_mode for s in slices}
    data_source = modes.pop() if len(modes) == 1 else ("mixed" if modes else "unknown")
    status = max((s.status for s in slices), key=lambda s: _STATUS_RANK[s], default="ok")
    if state.rank_mode == DEGRADED_NO_GRAPH and {"people", "events"} & set(domains) and not mode_override:
        data_source, status = DEGRADED_NO_GRAPH, "degraded"
    warnings = {w for s in slices for w in s.warnings} | set(extra_warnings or [])
    shared = payload.get("plan_graph")
    if isinstance(shared, dict) and shared.get("error"):  # a 200 must not hide a failed graph write
        warnings.add(f"plan not written to FalkorDB: {shared['error']}; served from the API process only")
    if state.scenario_id:  # every response served while a simulation is in force says so
        warnings.add(f"simulated change active: scenario {state.scenario_id!r} rewrote "
                     f"{len(state.simulated_events)} event(s); not an update from the source (POST /reset clears it)")
    warnings = sorted(warnings)
    collected = max((s.collected_at for s in slices), default=None)
    return {
        "data_source": data_source,
        "status": status,
        "collected_at": collected.isoformat() if collected else None,
        "served_at": _now(),
        "warnings": warnings,
        **payload,
    }


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
            timeout=2, cwd=Path(__file__).resolve().parent,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def create_app(
    data: DemoData | None = None,
    found: providers.Providers | None = None,
    *,
    graph_probe: bool = True,
) -> FastAPI:
    """Build the app. Inject ``data`` (live envelopes) or ``found`` providers in tests."""
    state = DemoState(
        data or load_fixture(), found if found is not None else providers.discover_providers(),
        graph_probe,
    )
    app = FastAPI(title="Conferge demo API", version="0.1.0")
    app.state.demo = state
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    api = APIRouter(prefix="/api/v1")

    def health() -> dict[str, Any]:
        graph_up = providers.connect_store() is not None if state.graph_probe else False
        return {
            "status": "ok",
            "git_sha": _git_sha(),
            "versions": {
                "python": platform.python_version(), "conferge": _version("conferge"),
                "fastapi": _version("fastapi"), "pydantic": _version("pydantic"),
            },
            "graph_up": graph_up,
            "providers": [vars(s) for s in state.providers.statuses],
            "served_at": _now(),
        }

    app.get("/health")(health)
    api.get("/health")(health)

    @api.get("/sources")
    def sources() -> dict[str, Any]:
        return _envelope(state, list(state.data.domains), {
            "domains": {
                name: {"source_mode": s.source_mode, "status": s.status,
                       "collected_at": s.collected_at.isoformat(), "warnings": s.warnings}
                for name, s in state.data.domains.items()
            },
            "badge": logic.source_badge(state.data.domains),
            "providers": [vars(s) for s in state.providers.statuses],
        })

    @api.get("/conference")
    def conference() -> dict[str, Any]:
        return _envelope(state, ["conference"], {
            "conference": state.data.conference.model_dump(mode="json"),
            "user": state.data.user, "demo_goal_text": state.data.demo_goal_text,
        })

    def _publish_plan(plan: dict[str, Any]) -> dict[str, Any] | None:
        """Planner writes the plan to FalkorDB (shared agent state); None without a graph."""
        store = state.store()
        if store is None:
            return None
        try:
            from conferge.agents.planner.graph_state import publish_plan

            return publish_plan(store, USER_ID, plan, state.attended)
        except Exception as exc:  # noqa: BLE001 - the plan is still served, visibly unshared
            return {"error": type(exc).__name__}

    def _plan_payload(publish: bool = True) -> dict[str, Any]:
        opps = state.opportunities()
        plan = state.plan()
        shared = _publish_plan(plan) if publish else None
        return {
            "goal_text": state.goal_text,
            "goals": [g.model_dump(mode="json") for g in state.goals],
            "plan": plan,
            "plan_graph": shared,
            "people": [o.model_dump(mode="json") for o in opps[:10]],
            "computed_by": ("falkordb" if state.rank_mode == "graph"
                            else state.agent_mode or logic.FALLBACK),
            "ranking_mode": state.rank_mode,
            "scenario_id": state.scenario_id,
        }

    def _plan_warnings() -> list[str]:
        if state.rank_mode == "graph":
            return [*state.rank_warnings, *logic.goal_warnings(state.goals)]
        base = [*state.rank_warnings, *state.agent_warnings, *logic.goal_warnings(state.goals)]
        if state.agent_mode is None:
            base.append("planner agent not available: deterministic api-fallback ranking")
        return base

    @api.post("/goal")
    async def goal(req: GoalRequest) -> dict[str, Any]:
        if req.conference_id and req.conference_id != state.data.conference.id:
            raise HTTPException(404, f"unknown conference_id {req.conference_id!r}")
        goals = logic.parse_goals(req.text)  # never empty: unknown role -> tagged defaults + warning
        stated = datetime.now(timezone.utc)
        goals = [g.model_copy(update={"stated_at": stated}) for g in goals]
        state.goal_text, state.goals = req.text, goals
        state.agent_mode, state.agent_opportunities, state.agent_warnings = None, None, []
        state.invalidate()
        state._ranking()
        agent = state.providers.agents.get("planner") or state.providers.agents.get("networking")
        if agent is not None and state.rank_mode != "graph":  # Python agent: degraded fallback only
            data_modes = {state.data.domains[d].source_mode for d in ("events", "people")
                          if d in state.data.domains}
            mode = data_modes.pop() if len(data_modes) == 1 else "mixed"
            ctx = AgentContext(
                conference=state.data.conference, goals=goals, user_id=req.user_id,
                data_mode=mode if mode in {"live", "cached", "fixture"} else "mixed",
                events=state.data.events, people=state.data.people,
                budget_usd=state.data.user.get("budget_usd"),
            )
            try:
                result = await providers.run_agent(agent, ctx)
                if result.status != "failed" and result.opportunities:
                    state.agent_mode = result.agent
                    state.agent_opportunities = result.opportunities
                    state.agent_warnings = [f"{result.agent}: {e}" for e in result.errors]
                else:
                    state.agent_warnings = [f"{result.agent} returned {result.status} with no opportunities; using api-fallback"]
            except Exception as exc:  # noqa: BLE001 - visible degradation, not a 500
                state.agent_warnings = [f"planner agent error {type(exc).__name__}; using api-fallback"]
            state.invalidate()
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

    @api.get("/plan")
    def plan() -> dict[str, Any]:
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

    @api.get("/pipeline")
    def pipeline_view() -> dict[str, Any]:
        """How every source of this demo was collected, from the RunReports of the run."""
        from conferge.core import brightdata as bd
        from conferge.integration.pipeline_view import HEADLINE, reachability, totals

        rows = state.data.pipeline
        timings = {"steps": list(state.data.timings.get("steps", [])),
                   "sources": list(state.data.timings.get("sources", []))}
        if state.rank_seconds is not None:
            timings["steps"].append({"step": "rank", "seconds": state.rank_seconds,
                                     "note": f"last {state.rank_mode} ranking, measured at request time"})
        return _envelope(state, [], {
            "headline": HEADLINE, "rows": rows, "totals": totals(rows),
            "brightdata_calls": bd.calls(), "reachability": reachability(),
            "timings": timings, "sources_report": state.data.sources_report,
            "note": None if rows else "no collection run in this process (dataset served as loaded)",
        }, mode_override="live" if any(r["kind"] != "fallback" for r in rows) else "fixture")

    @api.get("/cost")
    def cost() -> dict[str, Any]:
        """Bright Data calls made by this process and their estimated USD cost (estimate only)."""
        from conferge.core import cost as bd_cost

        snap = bd_cost.snapshot()
        return _envelope(state, [], snap, mode_override="live" if snap["calls"] else "unknown",
                         extra_warnings=["estimate: flat USD 0.0015 per call, real price not verified"])

    @api.get("/brightdata")
    def brightdata_usage() -> dict[str, Any]:
        """What Bright Data actually returned in this process, per API; config state, never the key."""
        from conferge.core import brightdata as bd

        client = bd.BrightDataClient.from_env()
        apis = ("datasets", "web_unlocker", "serp")
        ready = {api: client.not_ready(api) is None for api in apis}
        # "live" only when at least one Bright Data API can actually be called from this
        # process; without a key nothing here is live, so the label says "unknown".
        notes = [] if any(ready.values()) else ["Bright Data not configured: no API ready in this process"]
        cached: dict[str, Any] = {"datasets": 0, "web_unlocker": 0, "serp": 0, "collected_at": {}}
        api_key = {"dataset": "datasets", "unlocker": "web_unlocker", "serp": "serp"}
        for r in state.data.pipeline:
            if r.get("cached") and r["kind"] == "brightdata" and r["brightdata_api"] in api_key:
                cached[api_key[r["brightdata_api"]]] += r["records"] or 0
                cached["collected_at"][r["provider"]] = r["collected_at"]
        cached["total"] = cached["datasets"] + cached["web_unlocker"] + cached["serp"]
        return _envelope(state, [], {
            "usage": bd.usage(),
            "cached": cached,
            "ready": ready,
            "not_ready_reason": {api: client.not_ready(api) for api in apis},
        }, extra_warnings=notes, mode_override="live" if any(ready.values()) else "unknown")

    @api.get("/search")
    def search(q: str = Query(..., min_length=2, max_length=100),
               limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
        store = state.store()
        if store is not None:
            try:
                from conferge.graph import queries as graph_queries

                found = graph_queries.search(store, q, limit)
                return _envelope(state, ["people", "events"], {**found, "backend": "falkordb"},
                                 extra_warnings=["full-text search in FalkorDB (Person name/bio, Event title)"])
            except Exception:  # noqa: BLE001 - fall back to the API dataset, visibly
                pass
        needle = q.casefold()
        people = [{"id": p.id, "name": p.name, "title": p.title, "score": None}
                  for p in state.data.people
                  if needle in f"{p.name} {p.bio or ''}".casefold()][:limit]
        events = [{"id": e.id, "title": e.title,
                   "start_at": e.start_at.isoformat() if e.start_at else None, "score": None}
                  for e in state.data.events if needle in e.title.casefold()][:limit]
        return _envelope(state, ["people", "events"],
                         {"people": people, "events": events, "backend": logic.FALLBACK},
                         extra_warnings=["FalkorDB not reachable: substring search on the API dataset"])

    @api.get("/antifomo")
    async def antifomo() -> dict[str, Any]:
        agent = state.providers.agents.get("antifomo")
        if agent is None:
            return _envelope(state, ["events"], {"skips": [], "computed_by": None},
                             extra_warnings=["anti-FOMO agent not available"])
        mode = _envelope(state, ["events", "people"], {})["data_source"]
        ctx = AgentContext(
            conference=state.data.conference, goals=state.goals, user_id="demo-user",
            data_mode=mode if mode in {"live", "cached", "fixture"} else "mixed",
            events=state.data.events, people=state.data.people,
            opportunities=state.opportunities(),
        )
        try:
            result = await providers.run_agent(agent, ctx)
        except Exception as exc:  # noqa: BLE001 - visible degradation, not a 500
            return _envelope(state, ["events"], {"skips": [], "computed_by": None},
                             extra_warnings=[f"anti-FOMO agent error {type(exc).__name__}"])
        # The plan comes from the graph (written by the planner), not from this process.
        notes = [f"{result.agent}: {e}" for e in result.errors]
        store, plan_version, skips_written = state.store(), None, None
        served = state.plan()  # the plan the UI shows: every "gain" below names one of its events
        plan_items = {i["event_id"]: i for d in served["days"] for i in d["items"]}
        if store is not None:
            from conferge.agents.antifomo.graph_state import planned_from_graph, publish_skips

            _publish_plan(served)  # make sure the planner's current plan is in the graph
            planned, plan_version = planned_from_graph(store, USER_ID)
        else:
            planned = set(plan_items)
            notes.append("FalkorDB not reachable: anti-FOMO read the plan from the API process")
        skips = logic.antifomo_skips(result.decisions, state.data, planned=planned, plan_items=plan_items)
        if store is not None:
            skips_written = publish_skips(store, USER_ID, skips)
        return _envelope(state, ["events", "people"], {
            "skips": skips, "computed_by": result.agent, "agent_status": result.status,
            "plan_source": "falkordb" if store is not None else "process",
            "plan_version": plan_version, "skips_graph": skips_written,
        }, extra_warnings=notes)

    def _company_card(company: Any, funding: dict[str, Any]) -> dict[str, Any] | None:
        """Company of a /people card, plus Crunchbase funding from the public cache when known."""
        if company is None:
            return None
        from conferge.people import crunchbase

        card = company.model_dump(mode="json")
        view = crunchbase.company_view(funding.get(company.id))
        if view:
            card["funding"], card["last_round"] = view["funding"], view["last_round"]
            card["evidence"] = [*card.get("evidence", []), view["evidence"]]
        return card

    def _why(opp: Opportunity) -> dict[str, Any]:
        """Edge rationales and evidence ids of the graph path behind this suggestion."""
        edges = [e for e in opp.path if "rationale" in e and "evidence_ids" in e]
        ids = list(dict.fromkeys(i for e in edges for i in e["evidence_ids"]))
        return {"edges": edges, "evidence_ids": ids,
                "source": "falkordb" if edges else None}

    @api.get("/people")
    def people(limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
        from conferge.people import crunchbase

        opps = state.opportunities()[:limit]
        funding = crunchbase.load_public_cache(crunchbase.PUBLIC_CACHE)  # read-only, may be {}
        cards = []
        for opp in opps:
            person = state.data.person(opp.person_ids[0]) if opp.person_ids else None
            company = state.data.company(person.company_id) if person else None
            cards.append({
                "opportunity": opp.model_dump(mode="json"),
                "person": person.model_dump(mode="json") if person else None,
                "company": _company_card(company, funding),
                "met": bool(person and person.id in state.met),
                "met_note": state.met.get(person.id) if person else None,
                "linkedin": state.data.linkedin.get(person.id) if person else None,
                "why": _why(opp),
            })
        return _envelope(state, ["people", "companies"], {"items": cards, "count": len(cards),
                                                               "total": len(state.opportunities())},
                         extra_warnings=_plan_warnings())

    def _events_view(event_type: str | None, day: str | None, min_score: float | None) -> list[dict[str, Any]]:
        from conferge.api.artwork import event_artwork, load_fixture_covers

        covers = load_fixture_covers()
        scores = state.event_scores()
        out = []
        for event in state.data.events:
            if event_type and event.event_type != event_type:
                continue
            if day and (not event.start_at or event.start_at.date().isoformat() != day):
                continue
            score = scores.get(event.id, 0.0)
            if min_score is not None and score < min_score:
                continue
            item = event.model_dump(mode="json")
            item["score"] = score
            item["source_mode"] = logic._mode_of(event.evidence)
            item["attended"] = event.id in state.attended
            item["skipped"] = event.id in state.skipped
            item.update(event_artwork(event, covers))
            item["simulated"] = event.id in state.simulated_events
            out.append(item)
        out.sort(key=lambda e: (e["start_at"] is None, e["start_at"] or "", e["id"]))
        return out

    @api.get("/events")
    def events(
        day: str | None = None, type: str | None = None,  # noqa: A002 - public query name
        min_score: float | None = Query(None, ge=0, le=100),
    ) -> dict[str, Any]:
        items = _events_view(type, day, min_score)
        return _envelope(state, ["events"], {"items": items, "count": len(items)})

    @api.get("/sessions")
    def sessions(day: str | None = None) -> dict[str, Any]:
        items = _events_view("session", day, None)
        return _envelope(state, ["events"], {"items": items, "count": len(items)})

    @api.get("/stays")
    def stays() -> dict[str, Any]:
        items = logic.stays_view(state.data)
        return _envelope(state, ["stays"], {"items": items, "count": len(items)})

    @api.get("/flights")
    def flights(alternatives: bool = False) -> dict[str, Any]:
        offers = state.data.flights
        domain = state.data.domains.get("flights")
        if alternatives and domain and domain.source_mode == "cached":
            from conferge.integration import travel_cache

            cached = travel_cache.load(flight_alternatives=True)
            if cached and "flights" in cached:
                offers = cached["flights"].items
        items = [{**f.model_dump(mode="json"), **rt_display(f), "source": source_of(f.evidence)}
                 for f in offers]
        return _envelope(state, ["flights"], {"items": items, "count": len(items)})

    @api.get("/travel")
    def travel() -> dict[str, Any]:
        view = logic.travel_view(state.data, state.plan(), state.accepted)
        return _envelope(state, ["flights", "stays", "events"], view)

    @api.get("/travel/map")
    def travel_map() -> dict[str, Any]:
        return _envelope(state, ["events", "stays", "conference"], logic.travel_map(state.data, state.plan()))

    def _graph() -> tuple[dict[str, Any], str | None, list[str]]:
        store = state.store()
        if store is not None:
            live = providers.read_live_graph(store)
            if live is not None:
                modes = {n["source_mode"] for n in live["nodes"]}
                mode = modes.pop() if len(modes) == 1 else "mixed"
                return live, mode, ["graph read from FalkorDB; node source_mode taken from node properties"]
        graph = logic.build_graph(state.data, state.goals, state.met)
        return graph, None, ["FalkorDB not reachable or empty: graph built from the API dataset"]

    @api.get("/graph")
    def graph(
        type: str | None = None,  # noqa: A002
        limit: int = Query(400, ge=1, le=400),
    ) -> dict[str, Any]:
        g, mode, notes = _graph()
        nodes = [n for n in g["nodes"] if not type or n["type"] == type or n["type"] == "User"]
        nodes = nodes[:limit]
        keep = {n["id"] for n in nodes}
        edges = [e for e in g["edges"] if e["source"] in keep and e["target"] in keep]
        backend = "falkordb" if mode is not None else logic.FALLBACK
        return _envelope(state, ["events", "people", "companies"],
                         {"nodes": nodes, "edges": edges, "backend": backend},
                         extra_warnings=notes, mode_override=mode)

    def _falkordb_path(person: str, user: str) -> dict[str, Any] | None:
        """Explainable goal -> person path queried in FalkorDB itself.

        The /graph read is capped at 400 edges, too small a sample to search for a path.
        """
        store = state.store()
        if store is None:
            return None
        try:
            from conferge.graph import queries as graph_queries
            from conferge.graph.explain import path_to_text

            result = graph_queries.path_user_to_person(store, user, person)
            found = result["paths"]
        except Exception:  # noqa: BLE001 - fall back to the sampled graph, visibly
            return None
        if not found:
            return None
        path, steps = found[0], []
        signature = result["rows"][0].get("signature") if result["rows"] else None
        for i, node in enumerate(path["nodes"]):
            props = node["props"]
            steps.append({"node": {
                "id": node["id"], "type": node["label"],
                "label": str(props.get("name") or props.get("title") or node["id"]),
                "source_mode": props.get("source_mode") or "unknown",
            }})
            if i < len(path["edges"]):
                e = path["edges"][i]
                steps.append({"edge": {
                    "id": f"{e['source']}|{e['type']}|{e['target']}", "source": e["source"],
                    "target": e["target"], "type": e["type"],
                    "evidence_source": e["props"].get("source"),
                    "confidence": e["props"].get("confidence"),
                    "observed_at": e["props"].get("observed_at"),
                    "rationale": e.get("rationale"), "evidence_ids": e.get("evidence_ids") or [],
                }})
        modes = {s["node"]["source_mode"] for s in steps if "node" in s}
        cypher = graph_queries.literal_cypher(
            dict(graph_queries.PATH_SIGNATURES).get(signature, ""),
            {"user_id": user, "person_id": person, "cap": 1}) if signature else None
        return {"steps": steps, "explanation": path_to_text(path), "signature": signature,
                "cypher": cypher, "browser_url": providers.browser_url(cypher) if cypher else None,
                "mode": modes.pop() if len(modes) == 1 else "mixed"}

    @api.get("/graph/path")
    def graph_path(person: str, user: str = "demo-user") -> dict[str, Any]:
        live = _falkordb_path(person, user)
        if live is not None:
            steps = live["steps"]
            return _envelope(state, ["people", "events"], {
                "path": steps,
                "node_ids": [s["node"]["id"] for s in steps if "node" in s],
                "edge_ids": [s["edge"]["id"] for s in steps if "edge" in s],
                "hops": sum(1 for s in steps if "edge" in s),
                "explanation": live["explanation"], "backend": "falkordb",
                "signature": live["signature"], "cypher": live["cypher"],
                "browser_url": live["browser_url"],
            }, extra_warnings=["path queried in FalkorDB; node source_mode taken from node properties"],
                mode_override=live["mode"])
        g, mode, notes = _graph()
        start = f"user:{user}"
        if not any(n["id"] == start for n in g["nodes"]):
            start = next((n["id"] for n in g["nodes"] if n["type"] == "User"), start)
        steps = logic.shortest_path(g, start, person)
        if not steps:
            raise HTTPException(404, f"no path from {user!r} to {person!r}")
        return _envelope(state, ["people", "events"], {
            "path": steps,
            "node_ids": [s["node"]["id"] for s in steps if "node" in s],
            "edge_ids": [s["edge"]["id"] for s in steps if "edge" in s],
            "hops": sum(1 for s in steps if "edge" in s),
        }, extra_warnings=notes, mode_override=mode)

    @api.post("/met")
    def met(req: MetRequest) -> dict[str, Any]:
        person = state.data.person(req.person_id)
        if person is None:
            raise HTTPException(404, f"unknown person_id {req.person_id!r}")
        state.met[person.id] = req.note or ""
        state.met_at[person.id] = datetime.now(timezone.utc)
        persisted, memory_id = "memory", None
        store = state.store()
        if store is not None:
            try:
                found = store.graph.query(
                    "MATCH (p:Person {id: $id}) RETURN p.id", params={"id": person.id}
                )
                if getattr(found, "result_set", None):
                    from conferge.graph import record_memory

                    memory_id = record_memory(store, "demo-user", "MET", "Person", person.id,
                                              note=req.note)
                    persisted = "falkordb"
            except Exception:  # noqa: BLE001 - memory still holds the meeting
                persisted = "memory"
        state.invalidate()  # the next ranking is re-read from FalkorDB (MET excluded by the query)
        payload = _plan_payload()
        payload.update({"person_id": person.id, "persisted": persisted,
                        "memory_id": memory_id if persisted == "falkordb" else None})
        notes = _plan_warnings()
        if persisted == "memory":
            notes.append("meeting kept in process memory only: not written to FalkorDB")
        return _envelope(state, ["people", "events"], payload, extra_warnings=notes)

    @api.get("/followup")
    def followup(person: str) -> dict[str, Any]:
        """Follow-up draft for a person the user has MET; proposed, never sent."""
        from conferge.agents.followup import best_goal, draft_followup

        found = state.data.person(person)
        if found is None:
            raise HTTPException(404, f"unknown person_id {person!r}")
        if found.id not in state.met:
            raise HTTPException(409, f"{person!r} not met yet: record the meeting first")
        opp = next((o for o in state.opportunities() if found.id in o.person_ids), None)
        person_events = [e for e in (state.data.event(i) for i in found.event_ids) if e is not None]
        # Where they met is known only if the user attended one of the person's events.
        met_event = next((e for e in person_events if e.id in state.attended), None)
        draft = draft_followup(
            found, conference=state.data.conference, goal=best_goal(found, state.goals),
            event=met_event, person_event=person_events[0] if person_events else None,
            company=state.data.company(found.company_id),
            note=state.met.get(found.id) or None,
            path_text=opp.rationale if opp else None, met_at=state.met_at.get(found.id),
        )
        payload = draft.model_dump(mode="json")
        payload["draft_status"] = payload.pop("status")  # "status" belongs to the envelope
        return _envelope(state, ["people"], payload)

    def _event_or_404(event_id: str) -> None:
        if state.data.event(event_id) is None:
            raise HTTPException(404, f"unknown event_id {event_id!r}")

    @api.post("/attended")
    def attended(req: EventAction) -> dict[str, Any]:
        _event_or_404(req.event_id)
        state.attended.add(req.event_id)
        state.skipped.discard(req.event_id)
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

    @api.post("/skipped")
    def skipped(req: SkipAction) -> dict[str, Any]:
        _event_or_404(req.event_id)
        state.skipped.add(req.event_id)
        state.attended.discard(req.event_id)
        persisted = "memory"
        store = state.store()
        if store is not None:
            try:
                from conferge.graph import record_memory

                record_memory(store, "demo-user", "SKIPPED", "Event", req.event_id, reason=req.reason)
                persisted = "falkordb"
            except Exception:  # noqa: BLE001 - the plan still honours the skip
                persisted = "memory"
        payload = _plan_payload()
        payload.update({"event_id": req.event_id, "reason": req.reason, "persisted": persisted})
        notes = _plan_warnings()
        if persisted == "memory":
            notes.append("skip kept in process memory only: not written to FalkorDB")
        return _envelope(state, ["events", "people"], payload, extra_warnings=notes)

    @api.get("/scenarios")
    def scenarios() -> dict[str, Any]:
        items = [{"id": s["id"], "label": s["label"]} for s in state.data.scenarios]
        return _envelope(state, ["events"], {"items": items, "active": state.scenario_id})

    def _replacement_path(replacement: dict[str, Any] | None) -> dict[str, Any] | None:
        """Why the replacement matters: goal -> person path for the first person it brings."""
        if not replacement or not replacement["people"]:
            return None
        person = replacement["people"][0]["person_id"]
        live = _falkordb_path(person, "demo-user")
        if live is not None:
            labels = [s["node"]["label"] for s in live["steps"] if "node" in s]
            return {"backend": "falkordb", "person_id": person, "nodes": labels,
                    "explanation": live["explanation"]}
        g = logic.build_graph(state.data, state.goals, state.met)
        steps = logic.shortest_path(g, "user:demo-user", person)
        if not steps:
            return None
        return {"backend": logic.FALLBACK, "person_id": person,
                "nodes": [s["node"].get("label", s["node"]["id"]) for s in steps if "node" in s],
                "explanation": None}

    @api.post("/simulate-change")
    def simulate_change(req: ScenarioRequest) -> dict[str, Any]:
        scenario = next((s for s in state.data.scenarios if s["id"] == req.scenario_id), None)
        if scenario is None:
            raise HTTPException(404, f"unknown scenario_id {req.scenario_id!r}")
        before = state.plan()
        scenario = logic.resolve_scenario(scenario, before)
        _publish_plan(before)  # the replanner reads the plan in force from the graph
        changed = logic.apply_scenario(state.data, scenario)
        state.scenario_id = scenario["id"]
        state.simulated_events.update(changed)
        payload = _plan_payload(publish=False)
        store = state.store()
        if store is not None:
            from conferge.agents.replanner.graph_state import publish_replan

            try:
                payload["plan_graph"] = publish_replan(
                    store, USER_ID, label=scenario["label"], scenario_id=scenario["id"],
                    changed=changed, new_plan=payload["plan"], attended=state.attended)
            except Exception as exc:  # noqa: BLE001 - the diff is still served
                payload["plan_graph"] = {"error": type(exc).__name__}
        replan = logic.explain_replan(before, payload["plan"], changed, state.data)
        for entry in replan:
            entry["graph_path"] = _replacement_path(entry["replacement"])
        payload.update({
            "scenario": {"id": scenario["id"], "label": scenario["label"]},
            "changed_events": changed,
            "diff": logic.plan_diff(before, payload["plan"]),
            "replan": replan,
        })
        return _envelope(state, ["events", "people"], payload,
                         extra_warnings=[*_plan_warnings(), "simulated change: not a real update from the source"])

    @api.get("/agents/state")
    def agents_state() -> dict[str, Any]:
        """What the planner, anti-FOMO and replanner wrote to FalkorDB for the user."""
        store = state.store()
        if store is None:
            return _envelope(state, ["events"], {"backend": None, "agents": [], "plan": None,
                                                 "skips": [], "changes": [], "cypher": None},
                             extra_warnings=["FalkorDB not reachable: no shared agent state"])
        from conferge.graph import agent_state

        cypher = agent_state.state_cypher(USER_ID)
        return _envelope(state, ["events"], {
            "backend": "falkordb", "user_id": USER_ID,
            "agents": agent_state.agent_activity(store, USER_ID),
            "plan": agent_state.read_plan(store, USER_ID),
            "skips": agent_state.read_skips(store, USER_ID),
            "changes": agent_state.read_changes(store, USER_ID),
            "cypher": cypher, "browser_url": providers.browser_url(cypher),
        })

    @api.post("/reset")
    def reset() -> dict[str, Any]:
        state.reset()
        cleared: dict[str, int] | None = None
        notes: list[str] = []
        store = state.store()
        if store is not None:
            try:  # the graph memory too: otherwise a reset would not reset the ranking
                cleared = store.delete_user_state(USER_ID)
            except Exception as exc:  # noqa: BLE001 - visible: the ranking will still exclude MET people
                notes.append(f"graph memory kept: FalkorDB delete failed ({type(exc).__name__}); "
                             "people met earlier stay excluded from the ranking")
        payload = _plan_payload()
        payload["graph_memory_cleared"] = cleared
        return _envelope(state, ["events", "people"], payload, extra_warnings=[*_plan_warnings(), *notes])

    @api.post("/proposal/accept")
    def proposal_accept(req: ProposalRequest) -> dict[str, Any]:
        view = logic.travel_view(state.data, state.plan(), state.accepted)
        if not any(p["id"] == req.proposal_id for p in view["proposals"]):
            raise HTTPException(404, f"unknown proposal_id {req.proposal_id!r}")
        state.accepted.add(req.proposal_id)
        view = logic.travel_view(state.data, state.plan(), state.accepted)
        return _envelope(state, ["flights", "stays", "events"], view)

    @api.get("/roi")
    def roi() -> dict[str, Any]:
        view = logic.roi_view(state.data, state.goals, state.opportunities(), state.met)
        return _envelope(state, ["flights", "stays", "people"], view)

    app.include_router(api)
    app.include_router(calendar_router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
