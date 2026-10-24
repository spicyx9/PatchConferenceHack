"""Check the separately sourced photos retained with cached hotel cards.

Run: uv run python scripts/probes/hotel_covers.py [--check-images]
No provider calls by default. --check-images checks the public image URLs only;
this never refreshes or verifies prices, dates, rooms, or availability.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


async def run(check_images: bool) -> None:
    doc = json.loads((ROOT / "data/cache/stays.json").read_text())
    hotels = [r for r in doc["records"] if r["record"]["id"].startswith("booking:")]
    failed = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for row in hotels:
            card = row.get("card_details") or {}
            urls = card.get("image_urls") or []
            ok = bool(urls and card.get("image_source_url") and card.get("image_collected_at"))
            if check_images and ok:
                try:
                    response = await client.get(urls[0])
                    ok = response.is_success and response.headers.get("content-type", "").startswith("image/")
                except httpx.HTTPError:
                    ok = False
            print(f"{'OK' if ok else 'MISSING'} {row['record']['name']}: "
                  f"photo={card.get('image_source_url')} at={card.get('image_collected_at')}; "
                  f"price remains cached, collected {row['provenance']['collected_at']}")
            if not ok:
                failed.append(row["record"]["id"])
    print(f"{len(hotels) - len(failed)}/{len(hotels)} cached hotels with traceable photos")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-images", action="store_true")
    asyncio.run(run(parser.parse_args().check_images))
