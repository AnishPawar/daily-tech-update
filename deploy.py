#!/usr/bin/env python3
"""Publish dashboard.html to GitHub Pages by committing it as index.html and pushing.

Run after refresh.py. No-ops cleanly if there's nothing new to publish.

Both this Mac (via a local scheduled task) and GitHub Actions can trigger this
independently, so before committing we fast-forward to origin/main -- a
no-op if we're already current, and otherwise picks up whichever side
published most recently instead of failing with a rejected push. It's a
fast-forward only merge: if history has genuinely diverged (or a local edit
is in the way) it fails safely without touching anything, and the push
below will then fail with a clear error instead.
"""
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard.html"
INDEX = ROOT / "index.html"
SUMMARY = ROOT / "summary.json"


def run(*args, check=True):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=check)


def main() -> int:
    if not DASHBOARD.exists():
        print("deploy.py: dashboard.html not found — run refresh.py first", file=sys.stderr)
        return 1

    fetch = run("git", "fetch", "origin", "main", check=False)
    if fetch.returncode == 0:
        sync = run("git", "merge", "--ff-only", "origin/main", check=False)
        if sync.returncode != 0:
            print(f"deploy.py: could not fast-forward to origin/main, continuing anyway:\n{sync.stderr}", file=sys.stderr)
    else:
        print(f"deploy.py: git fetch failed, continuing anyway:\n{fetch.stderr}", file=sys.stderr)

    shutil.copyfile(DASHBOARD, INDEX)

    tracked = ["index.html"]
    if SUMMARY.exists():
        tracked.append("summary.json")

    run("git", "add", *tracked)
    status = run("git", "status", "--porcelain", "--", *tracked)
    if not status.stdout.strip():
        print("deploy.py: no changes to publish, skipping commit/push")
        return 0

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    run("git", "commit", "-m", f"Daily refresh: {timestamp}")

    push = run("git", "push", check=False)
    if push.returncode != 0:
        print(f"deploy.py: git push failed:\n{push.stderr}", file=sys.stderr)
        return 1

    print(f"deploy.py: published index.html ({timestamp})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
