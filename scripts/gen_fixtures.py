"""Generate ``fixtures/demo.json`` deterministically (window 13).

Usage:
    uv run python scripts/gen_fixtures.py          # write the fixture
    uv run python scripts/gen_fixtures.py --check  # fail if the committed file is stale

Only ``fixtures/demo.json`` is written; per-source fixtures belong to their windows.
Every record is validated by ``conferge.core.schemas`` while being built.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from conferge.demo.fixture import FIXTURE_PATH, build_fixture, dumps, load_fixture


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    parser.add_argument("--out", type=Path, default=FIXTURE_PATH)
    args = parser.parse_args(argv)

    text = dumps(build_fixture())
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current != text:
            print(f"{args.out} is stale; run scripts/gen_fixtures.py", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    load_fixture(args.out)
    print(f"wrote {args.out} ({len(text)} bytes, source_mode=fixture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
