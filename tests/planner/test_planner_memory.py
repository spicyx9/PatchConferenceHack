"""Networking memory: constraint exclusions, met() re-ranking and graph persistence."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest
from planner_helpers import load_fixture, make_ctx, ranking

from conferge.agents.networking import MemoryBook, met
from conferge.agents.networking.memory import MemoryEntry, persist
from conferge.agents.planner import PlannerAgent
from conferge.core.store import GraphStore

EXPECTED = load_fixture()["expected"]["people_ranking"]


def _excluded(result) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {d["person_id"]: d["reason"] for d in result.decisions
            if d.get("type") == "excluded_person"}


@pytest.mark.parametrize("key", ["met_person_ids", "contacted_person_ids"])
async def test_constraint_exclusion(key: str) -> None:
    res = await PlannerAgent(people_limit=None).run(make_ctx(**{key: ["fx-p-inv-bo"]}))
    assert "fx-p-inv-bo" not in ranking(res)
    assert "already met" in _excluded(res)["fx-p-inv-bo"]
    gil = next(o for o in res.opportunities if o.person_ids == ["fx-p-inv-gil"])
    assert "already covered by a met contact" in gil.rationale
    assert "N(0.00)" in gil.rationale


async def test_excluded_person_not_counted_in_event_score() -> None:
    res = await PlannerAgent(people_limit=None).run(make_ctx(met_person_ids=["fx-p-founder-ana"]))
    infra = next(d for d in res.decisions
                 if d.get("type") == "event_score" and d["event_id"] == "fx-s-agent-infra")
    assert "0 confirmed" in infra["explanation"]
    assert "Ana" not in infra["explanation"]


async def test_met_reranks_immediately() -> None:
    agent = PlannerAgent(people_limit=None)
    ctx = make_ctx()
    before = await agent.run(ctx)
    top = ranking(before)[0]
    assert top == EXPECTED[0]
    after = await met(agent, ctx, top, note="coffee at Fort Mason")
    assert top not in ranking(after)
    assert ranking(after)[0] == EXPECTED[1]
    assert after.status == "ok"
    assert top in _excluded(after)
    assert agent.memory.excluded(ctx.user_id) == {top}
    # memory is per user
    other = await agent.run(ctx.model_copy(update={"user_id": "someone-else"}))
    assert ranking(other)[0] == top


async def test_met_persists_through_graphstore_merge() -> None:
    raw = Mock()
    store = GraphStore(raw)
    agent = PlannerAgent(people_limit=None)
    res = await met(agent, make_ctx(), "fx-p-inv-bo", note="hi", store=store)
    assert res.status == "ok"
    assert res.errors == []
    cyphers = [c.args[0] for c in raw.query.call_args_list]
    assert len(cyphers) == 2
    assert all("MERGE" in q for q in cyphers)
    assert cyphers[0].startswith("MERGE (n:Meeting")
    assert "[r:MET]" in cyphers[1]
    edge_params = raw.query.call_args_list[1].kwargs["params"]
    assert edge_params["to_id"] == "fx-p-inv-bo"


async def test_failing_store_degrades_but_reranks() -> None:
    raw = Mock()
    raw.query.side_effect = ConnectionError("down")
    agent = PlannerAgent(people_limit=None)
    res = await met(agent, make_ctx(), "fx-p-inv-bo", store=GraphStore(raw))
    assert res.status == "degraded"
    assert any("not persisted" in e and "ConnectionError" in e for e in res.errors)
    assert "fx-p-inv-bo" not in ranking(res)


def test_persist_returns_error_string_not_raise() -> None:
    entry = MemoryBook().record("u", "p")
    assert isinstance(entry, MemoryEntry)
    assert persist(object(), entry, "u") is not None
    assert "not persisted" in (persist(object(), entry, "u") or "")


def test_memory_book_requires_aware_timestamp() -> None:
    book = MemoryBook()
    with pytest.raises(ValueError, match="timezone-aware"):
        book.record("u", "p", at=datetime(2026, 10, 28, 10, 0))
    entry = book.record("u", "p", "CONTACTED")
    assert entry.at.tzinfo is not None
    assert book.excluded("u") == {"p"}
    assert book.excluded("nobody") == set()
