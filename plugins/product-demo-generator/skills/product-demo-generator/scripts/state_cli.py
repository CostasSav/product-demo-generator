"""Save, restore or list the app's states (items declared under [[state.items]] in demo.toml).

    run.py state --demo-dir demo save 02-after-upload [--replace]
    run.py state --demo-dir demo restore 02-after-upload
    run.py state --demo-dir demo list

Every restore first saves the current state as `_before-restore-<timestamp>`: a wrong restore is
undone by restoring that save. Refused while the app is busy (`state.busy_command`), unless
--force.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demokit import config as config_module
from demokit.state import Snapshots, StateRefused


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("save")
    save.add_argument("name")
    save.add_argument("--replace", action="store_true")
    save.add_argument("--force", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("name")
    restore.add_argument("--force", action="store_true")
    commands.add_parser("list")
    args = parser.parse_args(argv)
    snapshots = Snapshots.from_config(config_module.load(args.demo_dir))
    try:
        if args.command == "save":
            print(f"saved: {snapshots.save(args.name, args.replace, args.force)}")
        elif args.command == "restore":
            safety = snapshots.restore(args.name, args.force)
            print(f"restored {args.name} (previous state kept as {safety.name}) — reload the page")
        else:
            for meta in snapshots.list():
                present = [i["key"] for i in meta["items"] if i["nature"] != "absent"]
                print(f"{meta['saved_at'][:19]}  {meta['name']:<44} {', '.join(present)}")
    except StateRefused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
