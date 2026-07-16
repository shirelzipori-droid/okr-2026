"""Restore an internal OKR 2026 snapshot by code (e.g. V0).

Usage:
  python restore_okr_version.py V0
  python restore_okr_version.py --list
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from okr_2026_versions import SNAPSHOTS, get_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore OKR 2026 snapshot by internal code")
    parser.add_argument("code", nargs="?", help="Snapshot code, e.g. V0")
    parser.add_argument("--list", action="store_true", help="List known snapshot codes")
    args = parser.parse_args()

    if args.list or not args.code:
        print("OKR 2026 internal snapshots:\n")
        for snap in SNAPSHOTS.values():
            print(f"  {snap.code:4}  tag={snap.tag}  ({snap.date})")
            print(f"       {snap.notes}\n")
        if not args.code and not args.list:
            parser.print_help()
        return

    snap = get_snapshot(args.code)
    print(f"Checking out {snap.code} → tag {snap.tag}")
    print(f"  {snap.notes}")
    subprocess.run(["git", "fetch", "origin", "tag", snap.tag, "--force"], check=True)
    subprocess.run(["git", "checkout", snap.tag], check=True)
    print(f"\nDone. You are now on snapshot {snap.code} ({snap.tag}).")
    print("To return to latest main: git checkout main")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
