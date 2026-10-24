"""Window 07: public people enrichment and networking ranking.

Sources: official speakers (w03), public Luma hosts (w01), Bright Data SERP for
name + company -> LinkedIn, public GitHub API. Never private guest lists.
"""

from conferge.people.agent import PeopleAgent, profiles_from_people
from conferge.people.collect import CollectedPeople, collect_fixtures, from_luma, from_official
from conferge.people.dedup import dedupe
from conferge.people.fixture import load_fixture
from conferge.people.match import GraphAdjustment, apply_graph_adjustments, rank, run
from conferge.people.models import PersonMatch, PersonProfile, Presence, ProfileLookup
from conferge.people.source import PeopleSource

__all__ = [
    "CollectedPeople",
    "GraphAdjustment",
    "PeopleAgent",
    "PeopleSource",
    "PersonMatch",
    "PersonProfile",
    "Presence",
    "ProfileLookup",
    "apply_graph_adjustments",
    "collect_fixtures",
    "dedupe",
    "from_luma",
    "from_official",
    "load_fixture",
    "profiles_from_people",
    "rank",
    "run",
]
