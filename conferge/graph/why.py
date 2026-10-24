"""Deterministic "why this person?" answer from graph edge rationales (no LLM).

Pattern of market-terminal signalTerminalChat.ts without the model: the answer is the
concatenation of the ``rationale`` sentences written on each edge of the
``path_user_to_person`` paths, each suffixed with ``[ev:<evidence_id>]`` for every
evidence id of that edge, plus the list of cited evidence ``{evidence_id, source_url}``.
Only ids present on those edges are cited.
"""

from __future__ import annotations

from typing import Any

from conferge.core.store import GraphQuery, GraphStore
from conferge.graph.paths import PathEdge
from conferge.graph.queries import path_user_to_person


def _source_url(evidence_id: str, edge: PathEdge) -> str | None:
    """The URL behind an evidence id: itself for a URL, the profile URL for a snapshot id."""
    if evidence_id.startswith(("http://", "https://")):
        return evidence_id
    props = edge["props"]
    for snapshot, url in (("linkedin_snapshot_id", "linkedin_source_url"),
                          ("snapshot_id", "source_url")):
        if props.get(snapshot) == evidence_id and props.get(url):
            return str(props[url])
    return None  # record:<Kind>:<id> or raw_ref: an internal record, no public URL


def why_person(target: GraphStore | GraphQuery, user_id: str, person_id: str,
               limit: int = 3) -> dict[str, Any]:
    result = path_user_to_person(target, user_id, person_id, limit)
    sentences: list[str] = []
    evidence: dict[str, str | None] = {}
    for path in result["paths"]:
        for edge in path["edges"]:
            ids = edge.get("evidence_ids") or []
            if not edge.get("rationale") or not ids:
                continue
            sentence = f"{edge['rationale'].rstrip('.')}." + "".join(f" [ev:{i}]" for i in ids)
            if sentence not in sentences:  # the same edge shared by two paths is said once
                sentences.append(sentence)
            for evidence_id in ids:
                evidence.setdefault(evidence_id, _source_url(evidence_id, edge))
    signature = result["rows"][0]["signature"] if result["rows"] else None
    return {
        "person_id": person_id, "user_id": user_id, "signature": signature,
        "paths": len(result["paths"]),
        "answer": " ".join(sentences) if sentences else None,
        "sentences": sentences,
        "evidence": [{"evidence_id": i, "source_url": url} for i, url in evidence.items()],
        "computed_by": "falkordb",
    }
