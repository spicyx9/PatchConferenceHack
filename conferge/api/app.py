"""FastAPI demo app: versioned JSON endpoints plus the one-page UI in ``static/``.

Every response carries ``data_source`` (live | cached | fixture | mixed |
unknown), ``status``, ``collected_at`` and ``warnings``. Fixture data is never
reported as live. Run with ``uv run uvicorn conferge.api.app:app``.
"""

from __future__ import annotations

import copy
import platform
import subprocess
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from conferge.api import logic, providers
from conferge.api.data import DemoData, load_fixture
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

    def reset(self) -> None:
        self.data = copy.deepcopy(self.pristine)
        self.goal_text = self.data.demo_goal_text
        self.goals: list[Goal] = logic.parse_goals(self.goal_text)
        self.met: dict[str, str] = {}
        self.attended: set[str] = set()
        self.skipped: set[str] = set()
        self.accepted: set[str] = set()
        self.scenario_id: str | None = None
        self.agent_mode: str | None = None
        self.agent_opportunities: list[Opportunity] | None = None
        self.agent_warnings: list[str] = []

    def store(self) -> Any | None:
        return providers.connect_store() if self.graph_probe else None

    def opportunities(self) -> list[Opportunity]:
        if self.agent_opportunities:
            met = set(self.met)
            return sorted(
                self.agent_opportunities,
                key=lambda o: (bool(set(o.person_ids) & met), -o.score, o.id),
            )
        return logic.rank_people(self.data, self.goals, self.met)

    def plan(self) -> dict[str, Any]:
        return logic.build_plan(
            self.data, self.goals, self.opportunities(),
            skipped=self.skipped, attended=self.attended,
        )


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
    warnings = sorted({w for s in slices for w in s.warnings} | set(extra_warnings or []))
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
            "providers": [vars(s) for s in state.providers.statuses],
        })

    @api.get("/conference")
    def conference() -> dict[str, Any]:
        return _envelope(state, ["conference"], {
            "conference": state.data.conference.model_dump(mode="json"),
            "user": state.data.user, "demo_goal_text": state.data.demo_goal_text,
        })

    def _plan_payload() -> dict[str, Any]:
        opps = state.opportunities()
        return {
            "goal_text": state.goal_text,
            "goals": [g.model_dump(mode="json") for g in state.goals],
            "plan": state.plan(),
            "people": [o.model_dump(mode="json") for o in opps[:10]],
            "computed_by": state.agent_mode or logic.FALLBACK,
            "scenario_id": state.scenario_id,
        }

    def _plan_warnings() -> list[str]:
        base = list(state.agent_warnings)
        if state.agent_mode is None:
            base.append("planner agent not available: deterministic api-fallback ranking")
        return base

    @api.post("/goal")
    async def goal(req: GoalRequest) -> dict[str, Any]:
        if req.conference_id and req.conference_id != state.data.conference.id:
            raise HTTPException(404, f"unknown conference_id {req.conference_id!r}")
        goals = logic.parse_goals(req.text)
        if not goals:
            raise HTTPException(422, "no goal recognised; mention investors, founders, PMs or engineers")
        state.goal_text, state.goals = req.text, goals
        state.agent_mode, state.agent_opportunities, state.agent_warnings = None, None, []
        agent = state.providers.agents.get("planner") or state.providers.agents.get("networking")
        if agent is not None:
            mode = _envelope(state, ["events", "people"], {})["data_source"]
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
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

    @api.get("/plan")
    def plan() -> dict[str, Any]:
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

    @api.get("/people")
    def people(limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
        opps = state.opportunities()[:limit]
        cards = []
        for opp in opps:
            person = state.data.person(opp.person_ids[0]) if opp.person_ids else None
            company = state.data.company(person.company_id) if person else None
            cards.append({
                "opportunity": opp.model_dump(mode="json"),
                "person": person.model_dump(mode="json") if person else None,
                "company": company.model_dump(mode="json") if company else None,
                "met": bool(person and person.id in state.met),
                "met_note": state.met.get(person.id) if person else None,
            })
        return _envelope(state, ["people", "companies"], {"items": cards, "count": len(cards)},
                         extra_warnings=_plan_warnings())

    def _events_view(event_type: str | None, day: str | None, min_score: float | None) -> list[dict[str, Any]]:
        scores = logic.event_scores(state.data, state.goals, state.opportunities())
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
    def flights() -> dict[str, Any]:
        items = [f.model_dump(mode="json") for f in state.data.flights]
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

    @api.get("/graph/path")
    def graph_path(person: str, user: str = "demo-user") -> dict[str, Any]:
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
        persisted = "memory"
        store = state.store()
        if store is not None:
            try:
                found = store.graph.query(
                    "MATCH (p:Person {id: $id}) RETURN p.id", params={"id": person.id}
                )
                if getattr(found, "result_set", None):
                    meeting_id = f"meeting:demo-user:{person.id}"
                    store.merge_node("Meeting", meeting_id, {
                        "user_id": "demo-user", "met_at": _now(), "source": "user",
                    })
                    store.merge_edge("Meeting", meeting_id, "INVOLVES", "Person", person.id, {
                        "source": "user", "confidence": 1.0, "observed_at": _now(),
                    })
                    persisted = "falkordb"
            except Exception:  # noqa: BLE001 - memory still holds the meeting
                persisted = "memory"
        payload = _plan_payload()
        payload.update({"person_id": person.id, "persisted": persisted})
        return _envelope(state, ["people", "events"], payload, extra_warnings=_plan_warnings())

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
    def skipped(req: EventAction) -> dict[str, Any]:
        _event_or_404(req.event_id)
        state.skipped.add(req.event_id)
        state.attended.discard(req.event_id)
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

    @api.get("/scenarios")
    def scenarios() -> dict[str, Any]:
        items = [{"id": s["id"], "label": s["label"]} for s in state.data.scenarios]
        return _envelope(state, ["events"], {"items": items, "active": state.scenario_id})

    @api.post("/simulate-change")
    def simulate_change(req: ScenarioRequest) -> dict[str, Any]:
        scenario = next((s for s in state.data.scenarios if s["id"] == req.scenario_id), None)
        if scenario is None:
            raise HTTPException(404, f"unknown scenario_id {req.scenario_id!r}")
        before = state.plan()
        changed = logic.apply_scenario(state.data, scenario)
        state.scenario_id = scenario["id"]
        payload = _plan_payload()
        payload.update({
            "scenario": {"id": scenario["id"], "label": scenario["label"]},
            "changed_events": changed,
            "diff": logic.plan_diff(before, payload["plan"]),
        })
        return _envelope(state, ["events", "people"], payload,
                         extra_warnings=[*_plan_warnings(), "simulated change: not a real update from the source"])

    @api.post("/reset")
    def reset() -> dict[str, Any]:
        state.reset()
        return _envelope(state, ["events", "people"], _plan_payload(), extra_warnings=_plan_warnings())

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

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
