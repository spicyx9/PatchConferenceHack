"""Build a clean Spawnpoint bundle from tracked app files plus the photo cache."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP_DIRS = {"conferge", "fixtures", "static", "data"}


def main() -> None:
    stage = Path(tempfile.mkdtemp(prefix="conferge-release-"))
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    for name in filter(None, files):
        path = Path(name)
        if (path.parts[0] in APP_DIRS or name.startswith("integrations/trueforge/")
                or name in {"scripts/run_demo.py", "Dockerfile", "requirements.txt"}):
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, target)
    photos = ROOT / "raw/connection-photos"
    if not (photos / "manifest.json").is_file():
        raise SystemExit("Photo cache is missing; restore it before deploying.")
    shutil.copytree(photos, stage / "raw/connection-photos")
    print(stage)


if __name__ == "__main__":
    main()
