#!/usr/bin/env python3
"""Offline verification of committed judge-facing evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> Any:
    path = ROOT / relative
    if not path.is_file():
        raise ValueError(f"missing evidence file: {relative}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {relative}: {exc}") from exc


def records(document: Any, relative: str) -> list[dict[str, Any]]:
    value = document.get("records") if isinstance(document, dict) else None
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{relative}: expected an object with a records array")
    return value


def verify() -> dict[str, Any]:
    flights = records(load("data/cache/flights.json"), "data/cache/flights.json")
    stays = records(load("data/cache/stays.json"), "data/cache/stays.json")
    linkedin = load("data/cache/linkedin_public.json")
    crunchbase = load("data/cache/crunchbase_public.json")
    matrix = load("data/block_matrix.json")

    flight_apis = Counter(item.get("provenance", {}).get("api") for item in flights)
    stay_sites = Counter(item.get("provenance", {}).get("site") for item in stays)
    profiles = linkedin.get("profiles") if isinstance(linkedin, dict) else None
    companies = crunchbase.get("companies") if isinstance(crunchbase, dict) else None
    sites = matrix.get("sites") if isinstance(matrix, dict) else None
    counts = matrix.get("counts") if isinstance(matrix, dict) else None
    if not isinstance(profiles, list):
        raise ValueError("data/cache/linkedin_public.json: expected profiles array")
    if not isinstance(companies, list):
        raise ValueError("data/cache/crunchbase_public.json: expected companies array")
    if not isinstance(sites, list) or not isinstance(counts, dict):
        raise ValueError("data/block_matrix.json: expected sites array and counts object")

    actual = {
        "flights": len(flights),
        "flight_web_unlocker": flight_apis["unlocker"],
        "stays": len(stays),
        "booking": stay_sites["booking"],
        "airbnb": stay_sites["airbnb"],
        "linkedin_profiles": len(profiles),
        "crunchbase_companies": len(companies),
        "access_sites": len(sites),
        "access_direct": counts.get("reachable_without_brightdata"),
        "access_bright_data": counts.get("reachable_with_brightdata"),
        "access_unlocker": counts.get("reachable_with_unlocker_only"),
        "access_any_path": counts.get("reachable_any_path"),
    }
    expected = {
        "flights": 34,
        "flight_web_unlocker": 34,
        "stays": 21,
        "booking": 15,
        "airbnb": 6,
        "linkedin_profiles": 17,
        "crunchbase_companies": 2,
        "access_sites": 21,
        "access_direct": 10,
        "access_bright_data": 14,
        "access_unlocker": 12,
        "access_any_path": 16,
    }
    checks = {
        key: {"expected": value, "actual": actual[key], "pass": actual[key] == value}
        for key, value in expected.items()
    }
    return {"pass": all(item["pass"] for item in checks.values()), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--check", action="store_true", help="explicit CI-style check mode")
    args = parser.parse_args()
    try:
        result = verify()
    except ValueError as exc:
        result = {"pass": False, "error": str(exc)}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif "error" in result:
        print(f"FAIL: {result['error']}")
    else:
        for name, item in result["checks"].items():
            status = "PASS" if item["pass"] else "FAIL"
            print(f"{status} {name}: expected {item['expected']}, found {item['actual']}")
        print(
            "PASS: committed judge evidence is internally consistent"
            if result["pass"]
            else "FAIL: committed judge evidence does not match expected values"
        )
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
