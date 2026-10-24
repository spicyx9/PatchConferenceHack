from __future__ import annotations

from conferge.events.discovery.queries import QueryPlan, build_queries


def test_explicit_queries_go_first_and_are_deduplicated() -> None:
    plan = QueryPlan(city="San Francisco", conference_name="GitHub Universe",
                     extra_queries=["GitHub Universe 2026 side event",
                                    "AI founders happy hour San Francisco October 28",
                                    "github universe 2026 SIDE event"])
    texts = [q.text for q in build_queries(plan)]
    assert texts[:2] == ["GitHub Universe 2026 side event",
                         "AI founders happy hour San Francisco October 28"]
    assert sum(t.casefold() == "github universe 2026 side event" for t in texts) == 1
