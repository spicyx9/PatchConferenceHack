#!/usr/bin/env python3
"""Read-only proof of the Bright Data slide numbers from committed source files.

Usage:
    python scripts/verify_brightdata_pitch.py
    python scripts/verify_brightdata_pitch.py --json
    python scripts/verify_brightdata_pitch.py --check

No network calls, credentials, changes to the graph, or live data collection.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = frozenset({
    "Kayak", "Hotels.com", "Expedia", "Marriott", "Luma discover API",
})
EXPECTED = {
    "sites_tested": 16,
    "direct_access": 8,
    "bright_data_access": 14,
    "bright_data_only": 6,
    "flight_observations": 34,
    "jfk_outbounds": 20,
    "outbounds_with_return_slice": 0,
    "booking_quotes": 15,
    "airbnb_quotes": 6,
    "linkedin_profiles": 17,
}


def load(relpath: str) -> dict:
    return json.loads((ROOT / relpath).read_text(encoding="utf-8"))


def measured() -> dict:
    matrix = load("data/block_matrix.json")
    site_rows = []
    for site in matrix["sites"]:
        name = site["site"]
        if name in EXCLUDED:
            continue
        attempts = site["attempts"]
        direct = any(attempts[key]["class"] == "ok" for key in
                     ("plain_default_ua", "plain_browser_ua"))
        bd = any(attempts[key]["class"] == "ok" for key in
                 ("brightdata_unlocker", "brightdata_dataset"))
        site_rows.append({
            "name": name,
            "direct": direct,
            "bright_data": bd,
            "bright_data_only": bd and not direct,
            "plain_status": attempts["plain_default_ua"]["class"],
            "browser_ua_status": attempts["plain_browser_ua"]["class"],
            "unlocker_status": attempts["brightdata_unlocker"]["class"],
            "dataset_status": attempts["brightdata_dataset"]["class"],
        })

    flights = load("data/cache/flights.json")["records"]
    stays = load("data/cache/stays.json")["records"]
    linkedin = load("data/cache/linkedin_public.json")["profiles"]
    origins = Counter(
        ((row.get("record") or {}).get("slices") or [{}])[0]
        .get("segments", [{}])[0].get("origin_iata", "unknown")
        for row in flights
    )
    stay_sources = Counter(
        (row.get("provenance") or {}).get("site", "unknown") for row in stays
    )
    return {
        "measured_at": matrix.get("run_at"),
        "scope": "21 original sites minus 4 KYC-restricted sites and direct Luma API",
        "sites_tested": len(site_rows),
        "direct_access": sum(s["direct"] for s in site_rows),
        "bright_data_access": sum(s["bright_data"] for s in site_rows),
        "bright_data_only": sum(s["bright_data_only"] for s in site_rows),
        "bright_data_only_sites": [s["name"] for s in site_rows
                                   if s["bright_data_only"]],
        "site_results": site_rows,
        "flight_observations": len(flights),
        "jfk_outbounds": origins["JFK"],
        "outbound_origins": dict(origins),
        "outbounds_with_return_slice": sum(
            bool((row.get("record") or {}).get("return_slice_collected"))
            for row in flights
        ),
        "booking_quotes": stay_sources["booking"],
        "airbnb_quotes": stay_sources["airbnb"],
        "lodging_price_statuses": dict(Counter(
            (row.get("record") or {}).get("price_status", "unknown")
            for row in stays
        )),
        "linkedin_profiles": len(linkedin),
        "source_paths": [
            "data/block_matrix.json", "data/cache/flights.json",
            "data/cache/stays.json", "data/cache/linkedin_public.json",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="Print machine-readable counts and per-site evidence")
    parser.add_argument("--check", action="store_true",
                        help="Exit nonzero if captured 2026-10-24 slide counts drift")
    args = parser.parse_args()
    data = measured()
    errors = {key: {"expected": val, "actual": data.get(key)}
              for key, val in EXPECTED.items() if data.get(key) != val}
    if args.json:
        print(json.dumps({"data": data, "check": "FAIL" if errors else "PASS",
                          "differences": errors}, indent=2))
    else:
        print("Bright Data pitch evidence — captured sources")
        print("Direct: {direct_access}/{sites_tested} | Bright Data: "
              "{bright_data_access}/{sites_tested} | "
              "Bright-Data-only: +{bright_data_only}".format(**data))
        print("Flights: {flight_observations} outbound observations, "
              "{jfk_outbounds} depart JFK, "
              "{outbounds_with_return_slice} return slices".format(**data))
        print("Lodging: {booking_quotes} Booking quotes, "
              "{airbnb_quotes} Airbnb quotes".format(**data))
        print("LinkedIn: {linkedin_profiles} cached public profiles".format(**data))
        print("Capture files: " + ", ".join(data["source_paths"]))
        print("Snapshot check: " + ("FAIL " + str(errors) if errors else "PASS"))
    return int(args.check and bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
