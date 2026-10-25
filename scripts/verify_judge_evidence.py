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


def access_metrics(matrix: Any) -> dict[str, int]:
    """Recompute reachability from site-level attempts, never aggregate counts."""
    if not isinstance(matrix, dict) or not isinstance(matrix.get("sites"), list):
        raise ValueError("data/block_matrix.json: expected a sites array")
    sites = matrix["sites"]
    if not sites:
        raise ValueError("data/block_matrix.json: sites array is empty")

    required = (
        "plain_default_ua",
        "plain_browser_ua",
        "brightdata_unlocker",
        "brightdata_dataset",
    )
    allowed_classes = {"ok", "blocked", "error", "not_run", "pending", "shell_js"}
    direct = unlocker = dataset = bright_data = any_path = 0
    names: set[str] = set()

    for index, site in enumerate(sites):
        if not isinstance(site, dict):
            raise ValueError(f"data/block_matrix.json: site {index} is not an object")
        name = site.get("site")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"data/block_matrix.json: site {index} has no valid name")
        if name in names:
            raise ValueError(f"data/block_matrix.json: duplicate site name: {name}")
        names.add(name)
        attempts = site.get("attempts")
        if not isinstance(attempts, dict):
            raise ValueError(f"data/block_matrix.json: {name} has no attempts object")

        for attempt_name in required:
            attempt = attempts.get(attempt_name)
            if not isinstance(attempt, dict):
                raise ValueError(
                    f"data/block_matrix.json: {name} missing {attempt_name} attempt"
                )
            attempt_class = attempt.get("class")
            if attempt_class not in allowed_classes:
                raise ValueError(
                    f"data/block_matrix.json: {name}.{attempt_name} has invalid class "
                    f"{attempt_class!r}"
                )

        direct_ok = any(attempts[key]["class"] == "ok" for key in required[:2])
        unlocker_ok = attempts["brightdata_unlocker"]["class"] == "ok"
        dataset_attempt = attempts["brightdata_dataset"]
        dataset_ok = dataset_attempt["class"] == "ok"
        if dataset_ok:
            record_count = dataset_attempt.get("records")
            if not isinstance(record_count, int) or isinstance(record_count, bool) or record_count <= 0:
                raise ValueError(
                    f"data/block_matrix.json: {name} dataset is ok without positive records"
                )
        bright_data_ok = unlocker_ok or dataset_ok
        direct += direct_ok
        unlocker += unlocker_ok
        dataset += dataset_ok
        bright_data += bright_data_ok
        any_path += direct_ok or bright_data_ok

    computed = {
        "access_sites": len(sites),
        "access_direct": direct,
        "access_unlocker": unlocker,
        "access_dataset": dataset,
        "access_bright_data": bright_data,
        "access_any_path": any_path,
    }
    reported = matrix.get("counts")
    if not isinstance(reported, dict):
        raise ValueError("data/block_matrix.json: expected a counts object")
    reported_keys = {
        "access_sites": "n",
        "access_direct": "reachable_without_brightdata",
        "access_unlocker": "reachable_with_unlocker_only",
        "access_bright_data": "reachable_with_brightdata",
        "access_any_path": "reachable_any_path",
    }
    for metric, key in reported_keys.items():
        if reported.get(key) != computed[metric]:
            raise ValueError(
                f"data/block_matrix.json: stored {key}={reported.get(key)!r} "
                f"disagrees with recomputed {computed[metric]}"
            )
    return computed


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
    if not isinstance(profiles, list):
        raise ValueError("data/cache/linkedin_public.json: expected profiles array")
    if not isinstance(companies, list):
        raise ValueError("data/cache/crunchbase_public.json: expected companies array")

    actual = {
        "flights": len(flights),
        "flight_web_unlocker": flight_apis["unlocker"],
        "stays": len(stays),
        "booking": stay_sites["booking"],
        "airbnb": stay_sites["airbnb"],
        "linkedin_profiles": len(profiles),
        "crunchbase_companies": len(companies),
        **access_metrics(matrix),
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
    return {
        "pass": all(item["pass"] for item in checks.values()),
        "metrics": actual,
        "checks": checks,
    }


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
