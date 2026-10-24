"""Goal parser coverage on 25 realistic sentences a judge could type (FR and EN).

Both parsers (``conferge.api.logic.parse_goals`` and
``conferge.agents.planner.goals.parse_goals``) must recognise at least one role in
each sentence and return the same goal ids. Run ``python -m pytest -q -rA`` on
``test_report_coverage`` to print the coverage figure.
"""

from __future__ import annotations

import pytest

from conferge.agents.planner import goals as planner_goals
from conferge.api import logic

# (sentence, expected first target role)
SENTENCES: list[tuple[str, str]] = [
    # English, with a trigger verb
    ("Meet seed investors and AI agent founders", "investor"),
    ("Find CTOs of fintech scale-ups hiring platform engineers", "executive"),
    ("I want to talk to recruiters from fintech companies", "recruiter"),
    ("Looking for DevRel folks working on open source", "devrel"),
    ("Connect with security engineers and CISOs", "security"),
    ("I am a solo founder, I want to meet people like me", "founder"),
    ("Hiring senior backend engineers for our payments startup", "engineer"),
    ("Pitch our devtool to angel investors", "investor"),
    # English, no trigger verb
    ("Product designers interested in AI tooling", "designer"),
    ("Data scientists and ML engineers building agents", "data"),
    ("Open source maintainers and developer advocates", "engineer"),
    ("CTOs and VPs of engineering at infra companies", "executive"),
    ("Recruiters and hiring managers at AI startups", "recruiter"),
    # French, with a trigger verb
    ("Rencontrer des recruteurs et des DevRel", "recruiter"),
    ("Je cherche des CTO de fintech", "executive"),
    ("Discuter avec des ingénieurs sécurité et des RSSI", "security"),
    ("Je suis développeuse, je veux rencontrer des gens comme moi", "engineer"),
    ("Échanger avec des fondateurs open source", "founder"),
    ("Recruter des développeurs Python pour notre startup fintech", "engineer"),
    ("Trouver des responsables sécurité dans la banque", "security"),
    ("Rencontrer des PM qui bossent sur Copilot et des dirigeants", "pm"),
    # French, no trigger verb
    ("Des investisseurs seed et des fondateurs d'agents IA", "investor"),
    ("Designers produit et chercheurs UX", "designer"),
    ("Data scientists et ingénieurs ML", "data"),
    ("Investisseurs en amorçage, infra et cloud", "investor"),
]
assert len(SENTENCES) == 25

PARSERS = {"api": logic.parse_goals, "planner": planner_goals.parse_goals}


def _is_default(goals: list) -> bool:
    return not goals or any(t.startswith("default:") for g in goals for t in g.tags)


def coverage() -> dict[str, list[str]]:
    """Sentences each parser fails on (no goal, or default goals)."""
    return {name: [s for s, _ in SENTENCES if _is_default(parse(s))] for name, parse in PARSERS.items()}


def test_report_coverage() -> None:
    failed = coverage()
    for name, misses in failed.items():
        print(f"{name}: {len(SENTENCES) - len(misses)}/{len(SENTENCES)} sentences recognised; "
              f"misses={misses}")


@pytest.mark.parametrize(("text", "role"), SENTENCES)
def test_every_sentence_yields_a_recognised_goal(text: str, role: str) -> None:
    goals = planner_goals.parse_goals(text)
    assert not _is_default(goals), goals
    assert goals[0].target_roles == [role]
    assert sum(g.priority for g in goals) == pytest.approx(1.0)


@pytest.mark.parametrize(("text", "role"), SENTENCES)
def test_both_parsers_agree_on_ids(text: str, role: str) -> None:
    api_ids = [g.id for g in logic.parse_goals(text)]
    planner_ids = [g.id for g in planner_goals.parse_goals(text)]
    assert api_ids == planner_ids


def test_unknown_role_is_explicit_not_silent() -> None:
    goals = planner_goals.parse_goals("just sightseeing")
    assert [g.id for g in goals] == [g.id for g in planner_goals.DEFAULT_GOALS]
    assert planner_goals.goal_warnings(goals) == [planner_goals.UNKNOWN_ROLE_WARNING]
    assert planner_goals.goal_warnings(planner_goals.parse_goals("meet founders")) == []
    assert logic.goal_warnings(logic.parse_goals("just sightseeing")) == [planner_goals.UNKNOWN_ROLE_WARNING]


def test_topics_are_recognised() -> None:
    goals = planner_goals.parse_goals("Find CTOs of fintech scale-ups hiring platform engineers")
    assert [g.target_roles for g in goals] == [["executive"], ["engineer"]]
    assert "fintech" in goals[0].topics and "infra" in goals[0].topics
    goals = planner_goals.parse_goals("Trouver des responsables sécurité dans la banque")
    assert set(goals[0].topics) >= {"security", "fintech"}


def test_longer_role_alias_wins_over_its_tail() -> None:
    # "security engineers" is one role, not security + engineer.
    goals = planner_goals.parse_goals("Connect with security engineers")
    assert [g.target_roles for g in goals] == [["security"]]
    goals = planner_goals.parse_goals("Data scientists et ingénieurs ML")
    assert [g.target_roles for g in goals] == [["data"]]
