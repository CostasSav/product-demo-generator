import json
import os

import pytest
from demokit.config import ConfigError, app_env, load


def write(tmp_path, toml="", scenes=None):
    (tmp_path / "demo.toml").write_text(toml, encoding="utf-8")
    if scenes is not None:
        (tmp_path / "scenes.json").write_text(json.dumps({"scenes": scenes}), encoding="utf-8")


def test_defaults_fill_what_the_project_does_not_set(tmp_path):
    write(tmp_path, '[app]\nport = 9000\n[browser]\nzoom = 1.25\n')
    config = load(tmp_path)
    assert config.app_url == "http://127.0.0.1:9000"
    assert config.section("browser")["zoom"] == 1.25
    assert config.section("browser")["width"] == 1920
    assert config.section("montage")["crossfade_s"] == 0.8


def test_scenes_are_validated(tmp_path):
    write(tmp_path, "", [{"id": "1.1", "act": 1, "mode": "fast"}])
    with pytest.raises(ConfigError, match="mode"):
        load(tmp_path)
    write(tmp_path, "", [{"id": "1.1", "act": 1, "mode": "realtime"},
                         {"id": "1.1", "act": 1, "mode": "realtime"}])
    with pytest.raises(ConfigError, match="duplicate"):
        load(tmp_path)


def test_unknown_scene_keys_are_kept_as_extra(tmp_path):
    write(tmp_path, "", [{"id": "1.1", "act": 1, "mode": "realtime", "note": "x"}])
    assert load(tmp_path).scene("1.1").extra == {"note": "x"}


def test_the_app_never_inherits_the_tool_environment(monkeypatch):
    monkeypatch.setenv("PYTHONHOME", "/tool/python")
    monkeypatch.setenv("UV_INTERNAL__PYTHONHOME", "/tool/python")
    monkeypatch.setenv("PYTHONPATH", "/tool/scripts")
    monkeypatch.setenv("PRODUCT_DEMO_GENERATOR_USER_PYTHONPATH", "/user/path")
    env = app_env({"MY_FLAG": 1})
    assert "PYTHONHOME" not in env and "UV_INTERNAL__PYTHONHOME" not in env
    assert env["PYTHONPATH"] == "/user/path"
    assert env["MY_FLAG"] == "1"
    assert env["PATH"] == os.environ["PATH"]
