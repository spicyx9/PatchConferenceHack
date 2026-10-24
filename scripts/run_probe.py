"""Dispatch any team's probe script without modifying the shared Makefile."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/run_probe.py <slug> [probe options]", file=sys.stderr)
        return 2
    slug = sys.argv[1]
    if not slug.replace("-", "").replace("_", "").isalnum():
        print("invalid probe slug", file=sys.stderr)
        return 2
    path = Path(__file__).resolve().parent / "probes" / f"{slug}.py"
    if not path.exists():
        print(f"Probe not yet implemented: scripts/probes/{slug}.py", file=sys.stderr)
        return 1
    # The probe parses its own options: it must not see the slug as a positional argument.
    sys.argv = [str(path), *sys.argv[2:]]
    try:
        runpy.run_path(str(path), run_name="__main__")
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
