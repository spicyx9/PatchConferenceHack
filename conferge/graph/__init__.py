"""Window 08: FalkorDB opportunity graph (ingestion via GraphStore, read-only traversals)."""

from conferge.graph.bundle import GraphBundle, ingest_bundle
from conferge.graph.explain import path_to_text
from conferge.graph.ingest import GraphIngestor, IngestReport
from conferge.graph.memory import record_memory
from conferge.graph.why import why_person
from conferge.graph.queries import (
    company_coverage,
    conflicts,
    events_for_goal,
    graph_for_ui,
    path_user_to_person,
    people_for_goal,
    people_met_before,
    replan_after_change,
)

__all__ = [
    "GraphBundle", "GraphIngestor", "IngestReport", "company_coverage", "conflicts",
    "events_for_goal", "graph_for_ui", "ingest_bundle", "path_to_text", "path_user_to_person",
    "people_for_goal", "people_met_before", "record_memory", "replan_after_change",
    "why_person",
]
