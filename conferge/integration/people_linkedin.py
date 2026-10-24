"""Bright Data LinkedIn enrichment for the demo's speakers (window 07 client, bounded run).

Only people who already carry a public ``linkedin_url`` (official speaker records) are
fetched; nothing is matched by name here. Each success adds a ``brightdata:linkedin``
evidence (source URL, collected_at) and fills an empty ``bio`` from the profile's
``about``. The RunReport feeds the data pipeline panel.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from conferge.core.schemas import Person, RunReport, SourceEvidence

PROVIDER = "brightdata:linkedin"


async def enrich_with_linkedin(people: list[Person], *, limit: int = 5,
                               timeout_s: float = 110.0) -> tuple[list[Person], RunReport]:
    from conferge.core.brightdata import BrightDataClient
    from conferge.people.linkedin import fetch_profile

    started = datetime.now(timezone.utc)
    targets = [p for p in people if p.linkedin_url][:limit]

    def report(status: str, ok: int, errors: list[str]) -> RunReport:
        return RunReport(provider=PROVIDER, started_at=started,
                         finished_at=datetime.now(timezone.utc), status=status,  # type: ignore[arg-type]
                         termination="exhausted" if status == "ok" else "error",
                         source_mode="live", fetched_count=len(targets), unique_count=ok,
                         errors=errors)

    client = BrightDataClient.from_env()
    reason = client.not_ready("datasets")
    if reason or not targets:
        await client.aclose()
        return people, report("failed", 0, [reason or "no person with a linkedin_url"])
    async with client:
        results = await asyncio.gather(
            *(fetch_profile(client, str(p.linkedin_url), timeout_s=timeout_s) for p in targets),
            return_exceptions=True)
    enriched: dict[str, Person] = {}
    errors: list[str] = []
    for person, result in zip(targets, results, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"{person.id}: {type(result).__name__}: {str(result)[:120]}")
            continue
        about = (result.payload or {}).get("about")
        enriched[person.id] = person.model_copy(update={
            "bio": person.bio or (about.strip() if isinstance(about, str) and about.strip() else None),
            "evidence": [*person.evidence, SourceEvidence(
                provider=PROVIDER, source_mode="live", source_url=person.linkedin_url,
                collected_at=result.collected_at, source_record_id=result.source_id)],
        })
    status = "ok" if not errors else ("degraded" if enriched else "failed")
    return [enriched.get(p.id, p) for p in people], report(status, len(enriched), errors)
