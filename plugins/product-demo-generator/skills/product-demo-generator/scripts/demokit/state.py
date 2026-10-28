"""Save and restore the app's state at named points, so any scene can be re-filmed from the exact
state it started in — without redoing (or re-paying for) what came before.

The state is a list of items declared in `demo.toml` under `[[state.items]]`:

- `kind = "folder"` / `"file"`: copied as is (modification times kept). `exclude` lists glob
  patterns (relative to the item) that are never saved nor restored: what matches keeps its
  *current* content — use it for append-only spend or audit logs, which must keep counting what
  was really spent whatever state is restored;
- `kind = "sqlite"`: copied with SQLite's online backup API (safe while the app is running);
- `kind = "command"`: your own `save` / `restore` shell commands, with `{dir}` replaced by the
  save's folder (Postgres dump, Docker volume, API call…).

An item absent at save time is deleted at restore time: restoring "before upload" really brings
back an empty app.

Guards:
- refused while the app is busy (`busy_command` exits non-zero): a background job would overwrite
  the restored state;
- before every restore, the current state is saved as `_before-restore-<timestamp>`: a wrong
  restore is always undoable (restore that save);
- the current items are first *moved* aside: a locked file (open in another program) makes the
  restore fail before anything is deleted, and what was moved goes back.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from demokit.config import app_env

STATE_FILE = "state.json"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")
SAFETY_PREFIX = "_before-restore-"


class StateRefused(RuntimeError):
    pass


def _timestamp() -> str:
    # Microseconds: two restores within the same second each keep their own safety net.
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _rename_with_retries(source: Path, target: Path, attempts: int = 10) -> None:
    # Windows may lock freshly written files for a moment (antivirus, indexing).
    for attempt in range(attempts):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _excluded(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, p) or fnmatch.fnmatch(Path(relative).name, p)
               for p in patterns)


def _copy_tree(source: Path, target: Path, exclude: list[str]) -> None:
    def ignore(directory: str, names: list[str]) -> list[str]:
        base = Path(directory).relative_to(source)
        return [n for n in names if _excluded((base / n).as_posix(), exclude)]

    shutil.copytree(source, target, copy_function=shutil.copy2, ignore=ignore)


def _excluded_files(folder: Path, exclude: list[str]) -> list[Path]:
    if not exclude or not folder.is_dir():
        return []
    return [p.relative_to(folder) for p in folder.rglob("*")
            if p.is_file() and _excluded(p.relative_to(folder).as_posix(), exclude)]


def _sqlite_copy(source: Path, target: Path) -> None:
    """Online backup (consistent even while the app writes). Connections closed explicitly:
    `with sqlite3.connect()` only commits, and an open handle locks the file on Windows."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def _sqlite_clear(path: Path) -> None:
    """The database did not exist at save time: empty it in place (it may be open)."""
    with closing(sqlite3.connect(path)) as db:
        tables = [r[0] for r in db.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        for table in tables:
            db.execute(f'drop table "{table}"')
        db.commit()


class Snapshots:
    def __init__(self, root: Path, saves_dir: Path, items: list[dict[str, Any]],
                 busy_command: str = "", cwd: Path | None = None) -> None:
        self.root = root
        self.saves_dir = saves_dir
        self.items = items
        self.busy_command = busy_command
        self.cwd = cwd or root
        for i, item in enumerate(items):
            if item.get("kind") not in ("folder", "file", "sqlite", "command"):
                raise StateRefused(f"state item {i}: kind must be folder, file, sqlite or command")

    @classmethod
    def from_config(cls, config: Any) -> Snapshots:
        state = config.section("state")
        app = config.section("app")
        return cls(config.root, config.path(state["saves_dir"]), list(state["items"]),
                   state.get("busy_command", ""), config.path(app.get("cwd", "..")))

    # -- guards ------------------------------------------------------------------------------

    def busy(self) -> str | None:
        """Why the app is busy, or None. A non-zero exit of `busy_command` means busy; its output
        says what is running."""
        if not self.busy_command:
            return None
        result = subprocess.run(self.busy_command, shell=True, cwd=self.cwd, capture_output=True,
                                text=True, env=app_env())
        if result.returncode == 0:
            return None
        return (result.stdout + result.stderr).strip() or "busy_command reported a running job"

    def _check_idle(self, force: bool) -> None:
        if not force and (reason := self.busy()):
            raise StateRefused(f"the app is busy ({reason}) — wait for it to finish, or force "
                               "if the server is stopped and the state is wanted as is")

    def _item_path(self, item: dict[str, Any]) -> Path | None:
        if item["kind"] == "command":
            return None
        p = Path(item["path"]).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    def _key(self, index: int, item: dict[str, Any]) -> str:
        return item.get("name") or f"{index:02d}-{item['kind']}"

    # -- save --------------------------------------------------------------------------------

    def save(self, name: str, replace: bool = False, force: bool = False, *,
             safety: bool = False) -> Path:
        if not safety and not NAME.fullmatch(name):
            raise StateRefused(f"invalid save name {name!r}: letters, digits, '-', '_', '.'")
        self._check_idle(force)
        target = self.saves_dir / name
        if target.exists() and not replace:
            raise StateRefused(f"save {name!r} already exists (replace it explicitly)")
        temporary = target.with_name(f".{name}.saving-{_timestamp()}")
        content = temporary / "content"
        content.mkdir(parents=True)
        recorded = []
        for index, item in enumerate(self.items):
            key = self._key(index, item)
            path = self._item_path(item)
            nature = "absent"
            if item["kind"] == "command":
                folder = content / key
                folder.mkdir()
                self._run(item["save"], folder)
                nature = "command"
            elif path is not None and path.exists():
                if item["kind"] == "sqlite":
                    _sqlite_copy(path, content / key)
                    nature = "sqlite"
                elif path.is_dir():
                    _copy_tree(path, content / key, item.get("exclude", []))
                    nature = "folder"
                else:
                    shutil.copy2(path, content / key)
                    nature = "file"
            recorded.append({"key": key, "kind": item["kind"], "nature": nature,
                             "path": str(path) if path else None})
        meta = {"name": name, "saved_at": datetime.now(UTC).isoformat(), "items": recorded}
        (temporary / STATE_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        _rename_with_retries(temporary, target)
        return target

    # -- restore -----------------------------------------------------------------------------

    def _read(self, name: str) -> tuple[Path, dict[str, Any]]:
        folder = self.saves_dir / name
        meta_path = folder / STATE_FILE
        if not meta_path.is_file():
            raise StateRefused(f"no save named {name!r} (see `state list`)")
        return folder, json.loads(meta_path.read_text(encoding="utf-8"))

    def restore(self, name: str, force: bool = False) -> Path:
        """Restore a save; returns the safety save of the state it replaced."""
        folder, meta = self._read(name)
        self._check_idle(force)
        safety = self.save(f"{SAFETY_PREFIX}{_timestamp()}", force=True, safety=True)
        by_key = {entry["key"]: entry for entry in meta["items"]}
        quarantine = self.saves_dir / f".quarantine-{_timestamp()}"
        moved: list[tuple[Path, Path]] = []

        # 1. Move the current items aside (a locked file fails here, before anything is lost).
        try:
            for index, item in enumerate(self.items):
                path = self._item_path(item)
                # A SQLite database stays in place (the app may hold it open): restored by backup.
                if item["kind"] != "sqlite" and path is not None and path.exists():
                    aside = quarantine / str(index)
                    aside.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), str(aside))
                    moved.append((path, aside))
        except OSError as error:
            for original, aside in reversed(moved):
                shutil.move(str(aside), str(original))
            shutil.rmtree(quarantine, ignore_errors=True)
            raise StateRefused(f"could not move the current state aside ({error}) — a file is "
                               "probably open in another program. Nothing was changed.") from error

        # 2. Put the saved items back; excluded files keep their current content.
        try:
            for index, item in enumerate(self.items):
                key = self._key(index, item)
                entry = by_key.get(key, {"nature": "absent"})
                path = self._item_path(item)
                saved = folder / "content" / key
                if item["kind"] == "command":
                    if entry["nature"] == "command":
                        self._run(item["restore"], saved)
                    continue
                assert path is not None
                if entry["nature"] == "folder":
                    _copy_tree(saved, path, [])
                elif entry["nature"] == "sqlite":
                    _sqlite_copy(saved, path)
                elif item["kind"] == "sqlite" and path.exists():
                    _sqlite_clear(path)
                elif entry["nature"] == "file":
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(saved, path)
                aside = quarantine / str(index)
                for relative in _excluded_files(aside, item.get("exclude", [])):
                    destination = path / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(aside / relative, destination)
        except Exception:
            for item in self.items:
                path = self._item_path(item)
                if path is not None and item["kind"] != "sqlite":
                    _remove(path)
            for original, aside in reversed(moved):
                shutil.move(str(aside), str(original))
            raise
        shutil.rmtree(quarantine, ignore_errors=True)
        return safety

    def list(self) -> list[dict[str, Any]]:
        if not self.saves_dir.is_dir():
            return []
        saves = []
        for folder in self.saves_dir.iterdir():
            meta = folder / STATE_FILE
            if meta.is_file():
                saves.append(json.loads(meta.read_text(encoding="utf-8")))
        return sorted(saves, key=lambda m: m["saved_at"])

    def _run(self, template: str, folder: Path) -> None:
        command = template.replace("{dir}", str(folder))
        result = subprocess.run(command, shell=True, cwd=self.cwd, capture_output=True, text=True,
                                env=app_env())
        if result.returncode != 0:
            raise StateRefused(f"state command failed ({result.returncode}): {command}\n"
                               f"{result.stderr[-1500:]}")
