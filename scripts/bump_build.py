"""Increase the build number in version.json (run before `docker compose up --build`).

    python scripts/bump_build.py            # build 4 -> 5
    python scripts/bump_build.py --version 1.1.0
"""
import argparse
import json
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "version.json"

ap = argparse.ArgumentParser()
ap.add_argument("--version", help="also set the version string")
args = ap.parse_args()

info = json.loads(FILE.read_text(encoding="utf-8"))
info["build"] = int(info.get("build", 0)) + 1
if args.version:
    info["version"] = args.version
FILE.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
print(f"{info['version']} build {info['build']}")
