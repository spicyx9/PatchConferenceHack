"""Honesty fixes (P1): labels say what the data proves, nothing more."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conferge.api.app import create_app
from conferge.api.data import load_fixture
from conferge.api.providers import Providers

ROOT = Path(__file__).resolve().parents[2]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def _client() -> TestClient:
    return TestClient(create_app(data=load_fixture(), found=Providers(), graph_probe=False))


# -- 1. simulated sold out ----------------------------------------------------------------

def test_simulated_sold_out_is_flagged_and_labelled_as_simulated() -> None:
    client = _client()
    client.post("/api/v1/goal", json={"text": load_fixture().demo_goal_text, "user_id": "demo-user"})
    scenario = client.get("/api/v1/scenarios").json()["items"][0]["id"]
    res = client.post("/api/v1/simulate-change", json={"scenario_id": scenario}).json()
    changed = set(res["changed_events"])
    events = client.get("/api/v1/events").json()["items"]
    hit = [e for e in events if e["id"] in changed]
    assert hit and all(e["simulated"] and e["status"] == "sold_out" for e in hit)
    # The UI reads that flag: every sold-out label goes through statusLabel(status, id).
    assert '"Sold out (simulated scenario)"' in APP_JS
    assert "markSimulated(res.changed_events)" in APP_JS and "e.simulated" in APP_JS
    assert "eventStatus(event.status)" not in APP_JS  # the agenda card uses statusLabel


# -- 2. "Meet: X" only with SPEAKS_AT / HOSTS ---------------------------------------------

def test_meet_only_for_confirmed_speakers_or_hosts() -> None:
    from conferge.api import logic

    data = load_fixture()
    client = _client()
    client.post("/api/v1/goal", json={"text": data.demo_goal_text, "user_id": "demo-user"})
    plan = client.get("/api/v1/plan").json()["plan"]
    people = [(i["event_id"], p) for d in plan["days"] for i in d["items"] for p in i["people"]]
    people += [(c["loser"]["event_id"], p) for c in plan["conflicts"] for p in c["what_you_miss"]]
    assert people and all("confirmed" in p for _, p in people)
    for event_id, p in people:
        event = data.event(event_id)
        edge = p["person_id"] in event.speaker_ids + event.organizer_ids or (
            event_id in data.person(p["person_id"]).event_ids
            and data.person(p["person_id"]).participation in {"confirmed_speaker",
                                                              "confirmed_organizer"})
        assert p["confirmed"] is edge
    # an attendee listing gives a possible, never confirmed, meeting
    attendee = next((q for q in data.people if q.event_ids and q.participation not in
                     {"confirmed_speaker", "confirmed_organizer"}), None)
    if attendee:
        ev = next(e for e in data.events if e.id in attendee.event_ids)
        if attendee.id not in ev.speaker_ids + ev.organizer_ids:
            assert logic.confirmed_at(data, ev, attendee.id) is False
    assert 'Possibly: " + names(maybe) + " (not confirmed)"' in APP_JS
    assert "var who = meetLine(i.people);" in APP_JS and "meetLine(r.people)" in APP_JS


# -- 3. stay cards: guests and nights next to the price -----------------------------------

def test_stay_card_says_adults_and_nights_next_to_the_price() -> None:
    import subprocess

    js = (ROOT / "static" / "travel-cards.js").read_text(encoding="utf-8")
    script = js + """
    ;var html = window.TravelCards.stay({name: "Chelsea Inn", check_in: "2026-10-27",
      check_out: "2026-10-30", adults: 2, rooms: 1, total_price: "500.00", currency: "USD",
      price_status: "quoted_total", venue: {}}, "");
    console.log(html);"""
    out = subprocess.run(["node", "-e", "var window = {}; var document = {};" + script],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "2 adults · 3 nights" in out.stdout


# -- 4. data_source from the records, not from a key --------------------------------------

def test_brightdata_and_pipeline_data_source_follow_the_records(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from conferge.api.app import _pipeline_mode, _records_mode

    monkeypatch.setenv("BRIGHTDATA_API_KEY", "a-key-is-not-a-record")
    monkeypatch.setenv("BRIGHTDATA_SERP_ZONE", "serp_api1")
    body = _client().get("/api/v1/brightdata").json()
    assert body["ready"]["serp"] is True  # configured...
    assert body["live"]["records"] == 0  # ...but nothing collected in this process
    expected = "cached" if body["cached"]["total"] else "fixture"
    assert body["data_source"] == expected != "live"
    assert (_records_mode(0, 0), _records_mode(3, 0), _records_mode(0, 5), _records_mode(2, 5)) == (
        "fixture", "live", "cached", "mixed")
    rows = [{"kind": "brightdata", "records": 9, "cached": True}]
    assert _pipeline_mode(rows) == "cached"
    assert _pipeline_mode([{"kind": "fallback", "records": 5}]) == "fixture"


# -- 5. simulated Change nodes and demo goals are not live -------------------------------

class _Recorder:
    def __init__(self) -> None:
        self.nodes: list[tuple[str, str, dict]] = []
        self.edges: list[tuple] = []
        self.graph = self

    def merge_node(self, kind: str, node_id: str, props: dict | None = None) -> None:
        self.nodes.append((kind, node_id, props or {}))

    def merge_edge(self, *args: object) -> None:
        self.edges.append(args)

    def query(self, *_: object, **__: object) -> object:
        raise RuntimeError("no graph reads in this test")


def test_simulated_change_is_simulated_not_live() -> None:
    from conferge.graph import agent_state

    store = _Recorder()
    agent_state.write_change(store, "demo-user", label="sold out", scenario_id="w15-simulated-sold-out",
                             event_ids=["e1"], from_version=1, written_by="replanner", at_ms=1)
    ((_, _, props),) = [n for n in store.nodes if n[0] == "Change"]
    assert props["source_mode"] == "simulated"
    assert all(e[-1]["source_mode"] == "simulated" for e in store.edges)


def test_demo_goals_are_fixture_typed_goals_are_live(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from conferge.api import providers

    store = _Recorder()
    monkeypatch.setattr(providers, "connect_store", lambda *a, **k: store)
    client = TestClient(create_app(data=load_fixture(), found=Providers()))
    client.get("/api/v1/people?limit=3")  # graph ranking syncs the goals, then degrades here
    demo = [p for k, _, p in store.nodes if k == "Goal"]
    assert demo and {p["source_mode"] for p in demo} == {"fixture"}
    store.nodes.clear()
    client.post("/api/v1/goal", json={"text": "I want to meet engineers working on security",
                                      "user_id": "demo-user"})
    client.get("/api/v1/people?limit=3")
    typed = [p for k, _, p in store.nodes if k == "Goal"]
    assert typed and {p["source_mode"] for p in typed} == {"live"}


# -- 6. is_investor: "venture" alone is not enough ----------------------------------------

def test_venture_alone_is_not_an_investor() -> None:
    from conferge.core.schemas import Company
    from conferge.events.official.normalize import infer_roles as roles_from_title
    from conferge.people.enrich import investor_flag

    assert "investor" not in roles_from_title("Venture Lead, Developer Tools")
    assert "investor" not in roles_from_title("partner marketing")  # not an investing partner
    for title in ("Investor", "General Partner", "VC Associate", "Partner, Seed Capital", "Fund Manager"):
        assert "investor" in roles_from_title(title), title
    assert investor_flag(Company(id="c1", name="Example Ventures")).is_investor is None
    assert investor_flag(Company(id="c2", name="Example Capital")).is_investor is True
    # the Crunchbase flag stays authoritative: never overwritten by the heuristic
    flagged = Company(id="c3", name="Example Ventures", is_investor=True)
    assert investor_flag(flagged).is_investor is True
