"""make probe-<name> dispatch: the probe never sees the slug as an argument."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_probe_gets_a_clean_argv(tmp_path: Path) -> None:
    probe = ROOT / "scripts" / "probes" / "_argv_check.py"
    probe.write_text("import argparse, sys\n"
                     "argparse.ArgumentParser().parse_args()\n"
                     "print(len(sys.argv), sys.argv[0].endswith('_argv_check.py'))\n",
                     encoding="utf-8")
    try:
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_probe.py"), "_argv_check"],
                             capture_output=True, text=True, cwd=ROOT, check=False)
    finally:
        probe.unlink()
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "1 True"


def test_linkedin_probe_parses_its_options() -> None:
    # The real probe's parser (the one make probe-linkedin dispatches to) accepts no positional.
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "probes" / "linkedin.py"), "--help"],
                         capture_output=True, text=True, cwd=ROOT, check=False)
    assert out.returncode == 0 and "--no-collect" in out.stdout
