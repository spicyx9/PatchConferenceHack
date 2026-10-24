"""Window 10: conflict-aware agenda optimizer and anti-FOMO verdicts.

Public API (window 09 may ``from conferge.agents.antifomo import optimize``):
``optimize(candidates, constraints, original=None) -> Plan``, ``explain(plan)``,
``find_conflicts``, ``verdict``, ``build_candidates`` and the ``run`` agent.
"""

from conferge.agents.antifomo.agent import AntiFomoAgent, constraints_from_context, run
from conferge.agents.antifomo.conflicts import Conflict, Verdict, find_conflicts, verdict, verdicts
from conferge.agents.antifomo.models import (
    Candidate, Constraints, Plan, PlanItem, Rejection, TimeSlot,
)
from conferge.agents.antifomo.optimizer import explain, optimize
from conferge.agents.antifomo.scoring import build_candidates, score_event, target_people

__all__ = [
    "AntiFomoAgent", "Candidate", "Conflict", "Constraints", "Plan", "PlanItem", "Rejection",
    "TimeSlot", "Verdict", "build_candidates", "constraints_from_context", "explain",
    "find_conflicts", "optimize", "run", "score_event", "target_people", "verdict", "verdicts",
]
