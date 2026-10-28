"""Scaffold a project's demo folder from the templates.

    run.py new --demo-dir demo [--gitignore]

Creates demo.toml, scenes.json, acts.py, scenario.md, inputs.md and slides/slides.html (never
overwrites an existing file), plus the working folders. The demo folder will hold saves of the
app's state, recordings and voice files: it should not be committed. `--gitignore` adds it to the
repository's .gitignore; without it, the command only warns when it is not ignored.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
FILES = ["demo.toml", "scenes.json", "acts.py", "scenario.md", "inputs.md", "slides/slides.html"]
FOLDERS = ["voice/placeholder", "takes/live", "takes/retakes", "saves", "montage",
           "slides/style"]


def git_root(path: Path) -> Path | None:
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def is_ignored(root: Path, path: Path) -> bool:
    probe = path / "demo.toml"
    result = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(probe)])
    return result.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("--gitignore", action="store_true", help="add the folder to .gitignore")
    args = parser.parse_args(argv)
    target = args.demo_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS:
        (target / folder).mkdir(parents=True, exist_ok=True)
    for name in FILES:
        destination = target / name
        if destination.exists():
            print(f"kept     {destination}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATES / name, destination)
        print(f"created  {destination}")
    root = git_root(target)
    if root is not None and not is_ignored(root, target):
        relative = target.relative_to(root).as_posix()
        if args.gitignore:
            gitignore = root / ".gitignore"
            existing = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
            gitignore.write_text(existing + ("" if existing.endswith("\n") or not existing else "\n")
                                 + f"/{relative}/\n", encoding="utf-8")
            print(f"added /{relative}/ to {gitignore}")
        else:
            print(f"WARNING: {relative}/ is not ignored by git — it will hold app-state saves and "
                  "videos. Re-run with --gitignore, or ignore it yourself.")
    print(f"next: fill {target / 'scenario.md'} and {target / 'scenes.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
