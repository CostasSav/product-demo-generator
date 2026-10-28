from demokit.config import load
from music_search import _playtime_ms, credit, score, set_music

KEYWORDS = ["corporate", "business"]


def track(**fields):
    base = {"title": "Corporate Morning", "license": "by", "license_version": "4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/", "duration": 240_000,
            "url": "https://example.org/a.mp3", "creator": "Someone",
            "foreign_landing_url": "https://example.org/track", "tags": [{"name": "instrumental"}]}
    return base | fields


def test_only_licences_allowing_commercial_use_and_editing():
    assert score(track(), KEYWORDS, 120) is not None
    assert score(track(license="cc0"), KEYWORDS, 120) is not None
    assert score(track(license="by-nc"), KEYWORDS, 120) is None
    assert score(track(license="by-nd"), KEYWORDS, 120) is None


def test_tracks_with_vocals_are_left_out():
    assert score(track(title="Corporate Anthem (feat. Jo)"), KEYWORDS, 120) is None
    assert score(track(title="Twitter A Cappella"), KEYWORDS, 120) is None
    assert score(track(tags=[{"name": "vocals"}]), KEYWORDS, 120) is None


def test_a_track_covering_the_video_beats_a_shorter_one():
    long_enough = score(track(duration=300_000), KEYWORDS, 280)
    too_short = score(track(duration=120_000), KEYWORDS, 280)
    assert long_enough > too_short


def test_credit_names_title_author_licence_and_source():
    line = credit(track())
    assert '"Corporate Morning" by Someone' in line and "CC BY 4.0" in line
    assert "https://example.org/track" in line
    assert "public domain" in credit(track(license="cc0"))


def test_ccmixter_playtime():
    assert _playtime_ms("{'ps': '3:45', 'mime_type': 'audio/mpeg'}") == 225_000
    assert _playtime_ms("{'ps': '1:02:03'}") == 3_723_000
    assert _playtime_ms("{}") == 0


def test_choosing_a_track_sets_the_config_and_the_credit(tmp_path):
    (tmp_path / "demo.toml").write_text('[app]\nport = 9000\n\n[montage]\nfps = 30\n', encoding="utf-8")
    config = load(tmp_path)
    set_music(config, "montage/music/candidate-2.mp3", "Music: X by Y (CC BY 4.0)")
    assert load(tmp_path).section("montage")["music"] == "montage/music/candidate-2.mp3"
    assert (tmp_path / "montage" / "CREDITS.txt").read_text(encoding="utf-8").startswith("Music: X")
    set_music(config, "montage/music/other.mp3", "Music: Z")  # replaced, not duplicated
    text = (tmp_path / "demo.toml").read_text(encoding="utf-8")
    assert text.count("music =") == 1 and 'music = "montage/music/other.mp3"' in text
