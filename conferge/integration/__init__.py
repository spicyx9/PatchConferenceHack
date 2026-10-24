"""Window 15: end-to-end integration harness.

Read-only over the feature windows: this package imports their public entry
points, wires them request -> normalized sources -> graph -> planning -> API and
reports what passes, what is fixture and which interfaces do not line up. It
never edits another window's data and never relabels a fixture as live.
"""

from conferge.integration.memgraph import MemoryGraph
from conferge.integration.pipeline import E2EReport, StageResult, run_e2e
from conferge.integration.report import render_markdown

__all__ = ["E2EReport", "MemoryGraph", "StageResult", "render_markdown", "run_e2e"]
