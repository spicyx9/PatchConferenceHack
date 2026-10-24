"""Markdown diagnostic for ``probes/integration.md`` and the PR body."""

from __future__ import annotations

from conferge.integration.pipeline import E2EReport

_ICON = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}


def render_markdown(report: E2EReport, *, title: str = "Probe: integration (window 15)") -> str:
    lines = [
        f"# {title}",
        "",
        f"- run at: {report.started_at.isoformat()}",
        f"- mode: **{report.mode}** | assembled data_mode: **{report.data_mode}**",
        f"- E2E verdict: **{'PASS' if report.passed else 'FAIL'}** "
        "(WARN stages are documented gaps, not failures)",
        "",
        "## Stages",
        "",
        "| stage | outcome | detail |",
        "|---|---|---|",
    ]
    for s in report.stages:
        lines.append(f"| {s.name} | {_ICON[s.outcome]} | {s.detail.replace('|', '/')} |")
    lines += ["", "## Sources", "",
              "| source | window | path | source_mode | status | events | people | companies "
              "| collected_at | errors |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for sl in report.slices:
        err = "; ".join(sl.errors)[:120].replace("|", "/") or "none"
        collected = sl.collected_at.isoformat() if sl.collected_at else "null"
        lines.append(f"| {sl.name} | w{sl.window} | {sl.attempted} | {sl.source_mode} | "
                     f"{sl.status} | {len(sl.events)} | {len(sl.people)} | {len(sl.companies)} | "
                     f"{collected} | {err} |")
    lines += ["", "## Components on main", "",
              "| window | component | merged | contract | fixture | probe | issues |",
              "|---|---|---|---|---|---|---|"]

    def tri(v: bool | None) -> str:
        return "n/a" if v is None else ("yes" if v else "no")

    for c in report.components:
        lines.append(f"| w{c.component.window} | {c.component.slug} | {tri(c.present)} | "
                     f"{tri(c.contract_ok)} | {tri(c.fixture_present)} | "
                     f"{tri(c.probe_present)} | {'; '.join(c.issues) or c.detail} |")
    lines += ["", "## Interface mismatches for window 00", ""]
    lines += [f"- {m}" for m in dict.fromkeys(report.mismatches)] or ["- none detected"]
    lines += ["", "## Findings by stage", ""]
    for s in report.stages:
        if s.findings:
            lines.append(f"### {s.name}")
            lines += [f"- {f}" for f in s.findings[:25]]
            if len(s.findings) > 25:
                lines.append(f"- ... {len(s.findings) - 25} more")
            lines.append("")
    graph = report.stage("graph")
    if graph and graph.data:
        lines += ["## Graph shape (in-memory GraphStore run)", "",
                  f"- nodes: {graph.data.get('nodes')}", f"- edges: {graph.data.get('edges')}",
                  ""]
    lines += [
        "## Labels",
        "",
        "- `fixture` rows come from each window's explicit, labelled loader; never shown as live.",
        "- Lodging and flights: live w05/w06 searches in live mode; when one fails or returns "
        "nothing, the API fixture (fictional, labelled) is used and the domain is reported "
        "`fixture/degraded`.",
        "- A failed live source stays `failed` with zero records unless `--fallback-fixture` "
        "was passed; the replacement slice is then listed separately as `fixture`.",
        "",
    ]
    return "\n".join(lines)
