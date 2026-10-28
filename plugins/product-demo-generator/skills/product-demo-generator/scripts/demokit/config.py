"""A project's demo folder: `demo.toml` (how to run and film the app) and `scenes.json` (the
script: one entry per scene, with its voice-over line and how the montage treats it).

Every relative path in `demo.toml` is relative to the demo folder.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MODES = ("realtime", "accelerated", "slide", "slideshow", "card")

DEFAULTS: dict[str, dict[str, Any]] = {
    "project": {"name": "Demo", "language": "en"},
    "app": {
        "port": 8765,
        "url": "http://127.0.0.1:{port}",
        "start_command": "",
        "safe_command": "",
        "cwd": "..",
        "ready_path": "/",
        "safe_log_marker": "",
        "start_timeout_s": 90,
        "env": {},
    },
    "browser": {"width": 1920, "height": 1080, "zoom": 1.0, "locale": "en-US", "headed": False,
                "timeout_s": 30},
    "filming": {"typing_ms": 75, "action_pause_s": 0.9, "pace": 1.0, "voice_pad_s": 1.0,
                "scroll_container": "", "dialog_selector": "dialog[open], [role=dialog]",
                "confirm_button": "button[type=submit], button:has-text('Confirm')"},
    "state": {"saves_dir": "saves", "busy_command": "", "items": []},
    "live": {"budget_usd": 0.0, "spend_file": "", "spend_field": "cost_usd"},
    "voice": {"tts_voice": "en_US-lessac-medium", "whisper_model": "medium"},
    "montage": {"fps": 30, "breath_s": 0.6, "max_realtime_speedup": 2.0, "music": "",
                "music_gap_db": 10.0, "outro_s": 1.5, "crossfade_s": 0.8,
                "counter_label": "real time", "output": "montage/demo.mp4",
                "slideshow_seconds": 1.5, "font": "", "font_bold": ""},
}


class ConfigError(RuntimeError):
    pass


@dataclass
class Scene:
    id: str
    act: int
    mode: str
    text: str = ""
    title: str = ""
    screen: str = ""
    overlay: str | None = None
    costly: bool = False
    restore_after: str | None = None
    take: str | None = None
    source_scene: str | None = None
    cap_s: float | None = None
    segments: list[list[float | None]] | None = None
    real_minutes: float | None = None
    slide: str | None = None
    group: str | None = None
    images: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scene:
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        scene = cls(**{k: v for k, v in data.items() if k in known},
                    extra={k: v for k, v in data.items() if k not in known})
        if scene.mode not in MODES:
            raise ConfigError(f"scene {scene.id}: mode {scene.mode!r} not in {MODES}")
        if scene.mode == "slide" and not scene.slide:
            raise ConfigError(f"scene {scene.id}: mode 'slide' needs a 'slide' image")
        return scene


@dataclass
class DemoConfig:
    root: Path
    data: dict[str, dict[str, Any]]
    scenes: list[Scene]

    def section(self, name: str) -> dict[str, Any]:
        return self.data[name]

    def path(self, value: str | Path) -> Path:
        """A path from the config, resolved against the demo folder."""
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    def scene(self, scene_id: str) -> Scene:
        for scene in self.scenes:
            if scene.id == scene_id:
                return scene
        raise ConfigError(f"scene {scene_id!r} is not in scenes.json")

    @property
    def scene_ids(self) -> list[str]:
        return [s.id for s in self.scenes]

    @property
    def voice_dir(self) -> Path:
        return self.root / "voice"

    @property
    def takes_dir(self) -> Path:
        return self.root / "takes"

    @property
    def app_url(self) -> str:
        app = self.data["app"]
        return app["url"].format(port=app["port"]).rstrip("/")


def app_env(extra: dict[str, Any] | None = None) -> dict[str, str]:
    """Environment for the user's own commands (the app, state and busy commands): the user's
    environment, without what the tool environment adds. uv's venv launcher sets PYTHONHOME,
    which makes any other Python crash on start ("SRE module mismatch")."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("PYTHONHOME", "UV_INTERNAL__PYTHONHOME", "VIRTUAL_ENV",
                                "PYTHONPATH", "PYTHONEXECUTABLE", "__PYVENV_LAUNCHER__")}
    original = os.environ.get("PRODUCT_DEMO_GENERATOR_USER_PYTHONPATH")
    if original:
        env["PYTHONPATH"] = original
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def _merge(defaults: dict, values: dict) -> dict:
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in defaults.items()}
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(demo_dir: str | Path = "demo") -> DemoConfig:
    root = Path(demo_dir).expanduser().resolve()
    toml_path = root / "demo.toml"
    if not toml_path.is_file():
        raise ConfigError(f"{toml_path} not found — scaffold one with `run.py new`")
    raw = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    data = _merge(DEFAULTS, raw)
    scenes_path = root / "scenes.json"
    scenes: list[Scene] = []
    if scenes_path.is_file():
        entries = json.loads(scenes_path.read_text(encoding="utf-8"))
        entries = entries["scenes"] if isinstance(entries, dict) else entries
        scenes = [Scene.from_dict(e) for e in entries]
        ids = [s.id for s in scenes]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ConfigError(f"scenes.json: duplicate scene ids {sorted(duplicates)}")
    return DemoConfig(root, data, scenes)
