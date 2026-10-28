import json
import sqlite3
import sys

import pytest
from demokit.state import SAFETY_PREFIX, Snapshots, StateRefused


def snapshots(tmp_path, items, busy=""):
    return Snapshots(tmp_path, tmp_path / "saves", items, busy, cwd=tmp_path)


def test_save_and_restore_a_folder(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.txt").write_text("v1")
    s = snapshots(tmp_path, [{"name": "data", "kind": "folder", "path": "data"}])
    s.save("one")
    (data / "a.txt").write_text("v2")
    (data / "new.txt").write_text("later")
    s.restore("one")
    assert (data / "a.txt").read_text() == "v1"
    assert not (data / "new.txt").exists()


def test_an_item_absent_at_save_time_is_deleted_at_restore(tmp_path):
    s = snapshots(tmp_path, [{"name": "data", "kind": "folder", "path": "data"}])
    s.save("empty")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x").write_text("x")
    s.restore("empty")
    assert not (tmp_path / "data").exists()


def test_excluded_files_keep_their_current_content(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "spend.jsonl").write_text('{"cost_usd": 1}\n')
    (data / "state.json").write_text("before")
    s = snapshots(tmp_path, [{"name": "data", "kind": "folder", "path": "data",
                              "exclude": ["spend.jsonl"]}])
    saved = s.save("before")
    assert not (saved / "content" / "data" / "spend.jsonl").exists()
    (data / "spend.jsonl").write_text('{"cost_usd": 1}\n{"cost_usd": 2}\n')
    (data / "state.json").write_text("after")
    s.restore("before")
    assert (data / "state.json").read_text() == "before"
    assert (data / "spend.jsonl").read_text().count("cost_usd") == 2


def test_every_restore_keeps_a_safety_save(tmp_path):
    (tmp_path / "f.txt").write_text("saved")
    s = snapshots(tmp_path, [{"name": "f", "kind": "file", "path": "f.txt"}])
    s.save("one")
    (tmp_path / "f.txt").write_text("current")
    safety = s.restore("one")
    assert safety.name.startswith(SAFETY_PREFIX)
    s.restore(safety.name)
    assert (tmp_path / "f.txt").read_text() == "current"


def test_sqlite_items_use_the_backup_api(tmp_path):
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as c:
        c.execute("create table t (v text)")
        c.execute("insert into t values ('saved')")
    s = snapshots(tmp_path, [{"name": "db", "kind": "sqlite", "path": "app.db"}])
    s.save("one")
    with sqlite3.connect(db) as c:
        c.execute("update t set v = 'changed'")
    s.restore("one")
    with sqlite3.connect(db) as c:
        assert c.execute("select v from t").fetchone()[0] == "saved"


def test_command_items_receive_the_save_folder(tmp_path):
    (tmp_path / "value.txt").write_text("saved")
    py = sys.executable
    item = {"name": "cmd", "kind": "command",
            "save": f'"{py}" -c "import shutil; shutil.copy(\'value.txt\', r\'{{dir}}/v.txt\')"',
            "restore": f'"{py}" -c "import shutil; shutil.copy(r\'{{dir}}/v.txt\', \'value.txt\')"'}
    s = snapshots(tmp_path, [item])
    s.save("one")
    (tmp_path / "value.txt").write_text("changed")
    s.restore("one")
    assert (tmp_path / "value.txt").read_text() == "saved"


def test_refused_while_the_app_is_busy(tmp_path):
    busy = f'"{sys.executable}" -c "import sys; print(\'job running\'); sys.exit(1)"'
    s = snapshots(tmp_path, [{"name": "f", "kind": "file", "path": "f.txt"}], busy=busy)
    with pytest.raises(StateRefused, match="job running"):
        s.save("one")
    s.save("one", force=True)


def test_names_are_validated_and_never_overwritten_silently(tmp_path):
    s = snapshots(tmp_path, [])
    with pytest.raises(StateRefused):
        s.save("../escape")
    s.save("one")
    with pytest.raises(StateRefused):
        s.save("one")
    s.save("one", replace=True)
    assert [m["name"] for m in s.list()] == ["one"]
    assert json.loads((tmp_path / "saves" / "one" / "state.json").read_text())["name"] == "one"


def test_sqlite_restores_while_the_app_holds_the_database_open(tmp_path):
    from contextlib import closing

    db = tmp_path / "app.db"
    app = sqlite3.connect(db)  # the running app keeps its connection
    app.execute("create table t (v text)")
    app.execute("insert into t values ('saved')")
    app.commit()
    s = snapshots(tmp_path, [{"name": "db", "kind": "sqlite", "path": "app.db"}])
    s.save("one")
    app.execute("update t set v = 'changed'")
    app.commit()
    s.restore("one")
    assert app.execute("select v from t").fetchone()[0] == "saved"
    app.close()
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("select v from t").fetchone()[0] == "saved"
