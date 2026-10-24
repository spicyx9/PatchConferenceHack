"""Deterministic, fully offline demo world for the GitHub Universe 2026 journey.

Everything produced here is labelled ``source_mode="fixture"``. People, companies,
side events, prices and itineraries are synthetic and marked as such; only the
anchor conference facts come from ``docs/knowledge/03-demo-scenario.md`` and are
not live-verified by this package.
"""

from conferge.demo.engine import DemoPlannerAgent, replay
from conferge.demo.seed import FIXED_COLLECTED_AT, build_world

__all__ = ["DemoPlannerAgent", "FIXED_COLLECTED_AT", "build_world", "replay"]
