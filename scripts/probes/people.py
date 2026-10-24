"""Probe for window 07 (people): writes probes/people.md.

Steps, each labelled with its own source mode:
1. fixture replay: official speakers (w03 fixture) + public Luma hosts (w01 fixture);
2. live Bright Data SERP name + company -> LinkedIn (needs BRIGHTDATA_API_KEY and
   BRIGHTDATA_SERP_ZONE; otherwise reported as missing_credentials, not an error);
3. live public GitHub API reachability (no key needed), not applied to any person;
4. deterministic ranking against the demo goals.
No fixture is ever reported as live.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.agents.planner.goals import DEFAULT_GOALS  # noqa: E402
from conferge.core.schemas import DiscoveryQuery  # noqa: E402
from conferge.people.collect import collect_fixtures  # noqa: E402
from conferge.people.dedup import dedupe  # noqa: E402
from conferge.people.enrich import EnrichmentError, GitHubEnricher  # noqa: E402
from conferge.people.match import run  # noqa: E402
from conferge.people.source import PeopleSource  # noqa: E402

OUT = ROOT / "probes" / "people.md"
GITHUB_CHECK_LOGIN = "octocat"  # GitHub's public demo account, connectivity check only


async def _serp_step(profiles) -> list[str]:
    # Speakers without a catalog-declared LinkedIn URL but with a company: the only
    # people for whom a SERP lookup is both useful and verifiable.
    targets = [p for p in profiles if p.person.linkedin_url is None and p.company_name][:3]
    lines = ["## 2. Bright Data SERP name + company -> LinkedIn (live attempt)", ""]
    if not targets:
        return lines + ["No eligible target (all have a declared URL or no company).", ""]
    query = DiscoveryQuery(domain="people", limit=len(targets), filters={"candidates": [
        {"name": p.person.name, "company": p.company_name} for p in targets]})
    async with PeopleSource() as source:
        result = await source.discover(query)
    report = result.run_report
    missing = any("missing_credentials" in e for e in [*result.errors, *report.errors])
    lines += [
        f"- status: **{'missing_credentials' if missing else report.status}** "
        f"(run_report status={report.status}, termination={report.termination})",
        f"- source_mode: {report.source_mode}; queries: {len(targets)}; "
        f"records: {len(result.items)}",
        f"- targets: {', '.join(p.person.name for p in targets)}",
    ]
    for err in list(dict.fromkeys([*report.errors, *result.errors]))[:5]:
        lines.append(f"- error: {err}")
    for item in result.items:
        payload = item.payload
        lines.append(f"- {payload.get('name')}: status={payload.get('status')} "
                     f"url={payload.get('linkedin_url')} confidence={payload.get('confidence')}")
    return lines + [""]


async def _github_step() -> list[str]:
    lines = ["## 3. Public GitHub API (live attempt, no key)", ""]
    try:
        async with GitHubEnricher() as gh:
            record = await asyncio.wait_for(gh.fetch_user(GITHUB_CHECK_LOGIN), timeout=15)
        repos = record.payload.get("repos") or []
        lines += [f"- status: **ok**, source_mode: {record.source_mode}",
                  f"- {record.source_url} collected_at {record.collected_at.isoformat()}, "
                  f"{len(repos)} non-fork repos",
                  "- connectivity check only; no fixture person has a declared GitHub URL, "
                  "so nothing was applied (no name-based guessing)."]
    except (EnrichmentError, TimeoutError, OSError) as exc:
        lines += [f"- status: **failed** ({type(exc).__name__}: {exc})"]
    return lines + [""]


async def main() -> None:
    now = datetime.now(timezone.utc)
    collected = collect_fixtures(explicit_opt_in=True)
    profiles, ambiguities = dedupe(collected.profiles)
    speakers = sum(any(x.kind == "speaker" for x in p.presences) for p in profiles)
    hosts = sum(any(x.kind == "host" for x in p.presences) for p in profiles)
    declared_li = sum(1 for p in profiles if p.person.linkedin_url)
    lines = [
        "# Probe: people (window 07)", "",
        f"Run at {now.isoformat()}.", "",
        "## 1. Candidate collection (FIXTURE replay, not live)", "",
        f"- source_mode: **{collected.source_mode}**, status: {collected.status}",
        "- inputs: fixtures/official.json (public GitHub Universe 2026 RainFocus catalog), "
        "fixtures/luma.json (public Luma event pages, hosts only)",
        f"- raw profiles: {len(collected.profiles)}; unique after dedup: {len(profiles)}; "
        f"ambiguous same-name pairs (not merged): {len(ambiguities)}",
        f"- confirmed speakers: {speakers}; confirmed hosts: {hosts}; "
        f"catalog-declared LinkedIn URLs: {declared_li} (none guessed)",
        "- guest lists read: 0 (never)", "",
    ]
    for report in collected.reports:
        lines.append(f"- report {report.provider}: {report.status}/{report.termination}, "
                     f"{report.source_mode}, fetched={report.fetched_count}; "
                     + "; ".join(report.warnings)[:200])
    lines.append("")
    lines += await _serp_step(profiles)
    lines += await _github_step()
    result = await run(DEFAULT_GOALS, profiles, events=collected.events, limit=10)
    lines += [
        "## 4. Ranking vs demo goals (deterministic, offline, data is FIXTURE)", "",
        f"- status: {result.status}; source_mode: {result.source_mode}; scorer: "
        f"{result.scorer}; considered: {result.considered}; shortlisted: {result.shortlisted}",
        "", "| # | person | roles | score | presence | where (from event) |",
        "|---|---|---|---|---|---|",
    ]
    for i, m in enumerate(result.matches, 1):
        w = m.where[0] if m.where else None
        where = (f"{w.title[:50]} @ {w.start_at.isoformat() if w.start_at else 'time unknown'}"
                 if w else "none")
        lines.append(f"| {i} | {m.person.name} | {', '.join(m.person.roles)} | {m.score} | "
                     f"{m.presence_status} | {where} |")
    lines += ["", "Presence is confirmed only for published speakers and hosts. Investor "
              "matches are absent because the public catalog lists no seed investors as "
              "speakers; none were invented.", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
