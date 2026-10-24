"""make probe-integration: E2E diagnostic written to probes/integration.md.

Always runs the offline fixture E2E (the demo backup). Unless ``--offline`` is
passed (or CONFERGE_OFFLINE=1), it also tries the live path against the public
endpoints the merged windows use (no Bright Data or OpenAI key needed). A live
source that fails stays ``failed``; ``--fallback-fixture`` adds a separately
labelled fixture slice for it.

Exit code: 0 when the fixture E2E passes (live failures are reported, not fatal),
1 otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from conferge.integration import render_markdown, run_e2e  # noqa: E402


async def _main(args: argparse.Namespace) -> int:
    fixture = await run_e2e("fixture")
    parts = [render_markdown(fixture, title="Probe: integration (window 15), fixture E2E")]
    if not args.offline:
        live = await run_e2e("live", fallback_fixture=args.fallback_fixture,
                             timeout=args.timeout, include_backup=False)
        parts.append(render_markdown(live, title="Live E2E (public endpoints, no API keys)"))
        print(f"live E2E: {'PASS' if live.passed else 'FAIL'} data_mode={live.data_mode}")
    else:
        parts.append("# Live E2E\n\nSkipped (--offline). Live behaviour unverified in this run.\n")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n\n---\n\n".join(parts), encoding="utf-8")
    print(f"fixture E2E: {'PASS' if fixture.passed else 'FAIL'}; wrote {out}")
    return 0 if fixture.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        default=os.getenv("CONFERGE_OFFLINE") == "1")
    parser.add_argument("--fallback-fixture", action="store_true")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--out", default=str(ROOT / "probes" / "integration.md"))
    if argv is None:
        # scripts/run_probe.py leaves its own "<slug>" argument in sys.argv.
        argv = [a for a in sys.argv[1:] if a != "integration"]
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
