"""Text -> Topic links without an LLM (degraded stand-in for GraphRAG-SDK).

The spec targets FalkorDB GraphRAG-SDK with OpenAI embeddings. Neither
``graphrag-sdk`` (not in pyproject, owned by window 0) nor an OpenAI key is
available, so this module links bios/descriptions to an explicit topic
vocabulary by whole-word alias matching. Each edge is tagged
``verification=keyword_match`` with a modest confidence so ranking can tell it
apart from source-declared topics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from conferge.core.schemas import SourceEvidence
from conferge.graph.ingest import GraphIngestor
from conferge.graph.schema import topic_id

TEXT_MATCH_CONFIDENCE = 0.5
_WORD_RE = re.compile(r"[a-z0-9]+")

# Topic -> lowercase aliases; extend from goal topics at call time.
DEFAULT_VOCABULARY: dict[str, tuple[str, ...]] = {
    "AI agents": ("ai agents", "ai agent", "agentic", "autonomous agents", "multi-agent"),
    "developer tools": ("developer tools", "devtools", "developer experience"),
    "Copilot": ("copilot", "github copilot"),
    "MCP": ("mcp", "model context protocol"),
    "venture capital": ("seed investor", "seed fund", "venture", "vc", "pre-seed"),
    "open source": ("open source", "oss"),
}


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _contains(tokens: list[str], phrase: str) -> bool:
    needle = _tokens(phrase)
    width = len(needle)
    return width > 0 and any(tokens[i:i + width] == needle for i in range(len(tokens) - width + 1))


def extract_topics(text: str | None,
                   vocabulary: Mapping[str, Iterable[str]] = DEFAULT_VOCABULARY) -> list[str]:
    if not text:
        return []
    tokens = _tokens(text)
    return [topic for topic, aliases in vocabulary.items()
            if any(_contains(tokens, alias) for alias in (topic, *aliases))]


def link_text_topics(ing: GraphIngestor, kind: str, node_id: str, text: str | None,
                     evidence: list[SourceEvidence],
                     vocabulary: Mapping[str, Iterable[str]] = DEFAULT_VOCABULARY,
                     declared: Iterable[str] = ()) -> list[str]:
    """Write ABOUT edges for topics found in ``text`` (node must already exist).

    Topics in ``declared`` already have a source-declared ABOUT edge; they are
    skipped so a weaker keyword match never overwrites that provenance.
    """
    skip = {topic_id(name) for name in declared}
    found = [name for name in extract_topics(text, vocabulary) if topic_id(name) not in skip]
    for name in found:
        tid = topic_id(name)
        if not ing.has("Topic", tid):
            ing.write_node("Topic", tid, {"name": name}, evidence)
        ing.write_edge(kind, node_id, "ABOUT", "Topic", tid, evidence=evidence,
                       verification="keyword_match", confidence=TEXT_MATCH_CONFIDENCE,
                       kind="text")
    return found


def similar_topics(text: str, topics: Iterable[str], k: int = 5) -> list[tuple[str, float]]:
    """Token Jaccard similarity; a placeholder for vector search on Topic.name."""
    query = set(_tokens(text))
    scored = []
    for topic in topics:
        words = set(_tokens(topic))
        union = query | words
        if union:
            scored.append((topic, round(len(query & words) / len(union), 4)))
    return sorted((s for s in scored if s[1] > 0), key=lambda s: (-s[1], s[0]))[:k]
