"""Find background music for the demo: three royalty-free tracks that match its tone and last long
enough to cover the whole video, downloaded for the user to listen to and choose.

    run.py music --demo-dir demo [--tone corporate] [--keywords "piano,ambient"]
    run.py music --demo-dir demo --pick 2          # use candidate 2 for the montage
    run.py music --demo-dir demo --use track.mp3 --credit "Music: ... (CC BY 4.0)"   # your own file

Sources (no account needed): the Openverse catalogue (api.openverse.org: Jamendo, Freesound,
Wikimedia...), then ccMixter (ccmixter.org) when Openverse is slow or finds too little. Only tracks
whose licence allows **commercial use and modification** are kept (the montage trims, fades and
lowers the music): CC0, CC BY, CC BY-SA, never NC or ND. Tracks with vocals are left out (they
fight the voice-over). If both sources fail, the command says so: search the web instead
(references/voice-and-montage.md) and bring the chosen file with `--use`.

The video length is read from montage/plan.json (else estimated from the voice-over); tracks
shorter than it are only proposed when nothing longer matches (they would loop).

Writes `montage/music/candidate-<N>.mp3` and `candidates.md` (title, author, length, licence,
source page, required credit). `--pick N` / `--use` set `montage.music` in demo.toml and write the
credit to `montage/CREDITS.txt` — CC BY / BY-SA require it in the video description or end screen.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from demokit import config as config_module
from demokit.media import duration, voice_file

OPENVERSE = "https://api.openverse.org/v1/audio/"
CCMIXTER = "http://ccmixter.org/api/query"
TONES = {
    "corporate": ["corporate", "business", "inspiring corporate", "motivational", "technology"],
    "upbeat": ["upbeat", "happy", "energetic", "positive"],
    "calm": ["ambient", "calm", "piano", "soft"],
    "tech": ["technology", "electronic", "future", "digital"],
    "cinematic": ["cinematic", "epic", "orchestral", "inspiring"],
    "playful": ["playful", "ukulele", "fun", "quirky"],
}
VOCALS = re.compile(r"\b(vocal|vocals|voice|singing|singer|sung|rap|lyrics|choir|feat|a ?cap+el+a)\b", re.I)
GOOD_LICENSES = {"cc0", "by", "by-sa", "pdm"}
HEADERS = {"User-Agent": "product-demo-generator (https://github.com/CostasSav/product-demo-generator)"}


def video_length(config) -> float:
    plan = config.root / "montage" / "plan.json"
    if plan.is_file():
        return float(json.loads(plan.read_text(encoding="utf-8"))["total_s"])
    m = config.section("montage")
    total = float(m["outro_s"])
    for scene in config.scenes:
        path, _ = voice_file(config.voice_dir, scene.id)
        spoken = duration(path) if path else len(scene.text.split()) / 2.5
        total += max(spoken + float(m["breath_s"]), 2.0)
    return total


def get(url: str, attempts: int = 2) -> object:
    """JSON from a catalogue. Fails fast (20 s, two attempts): a slow source is skipped, not
    waited for."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20) as r:
                raw = r.read()
                try:
                    return json.loads(raw.decode("utf-8"))
                except UnicodeDecodeError:  # some catalogues answer in Latin-1
                    return json.loads(raw.decode("latin-1"))
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < attempts - 1:  # anonymous rate limit: wait as told
                time.sleep(min(float(error.headers.get("Retry-After") or 10), 30))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == attempts - 1:
                raise
            time.sleep(2)
    return {}


def search_openverse(keywords: list[str], pages: int = 2) -> list[dict]:
    found: dict[str, dict] = {}
    failures = 0
    for keyword in keywords:
        for page in range(1, pages + 1):
            query = urllib.parse.urlencode({
                "q": keyword, "category": "music", "license_type": "commercial,modification",
                "page_size": 20, "page": page, "mature": "false"})
            try:
                data = get(f"{OPENVERSE}?{query}")
                failures = 0
            except (OSError, ValueError) as error:
                failures += 1
                print(f"  openverse {keyword!r}: {str(error)[:80]} - skipped")
                if failures >= 2:
                    print("  openverse does not answer: moving on")
                    return list(found.values())
                break
            for track in data.get("results", []):
                found.setdefault(f"openverse:{track['id']}", track)
            if page >= int(data.get("page_count") or 1):
                break
    return list(found.values())


def _playtime_ms(info: object) -> float:
    match = re.search(r"'ps':\s*'(?:(\d+):)?(\d+):(\d+)'", str(info))
    if not match:
        return 0
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return (hours * 3600 + minutes * 60 + seconds) * 1000


def search_ccmixter(keywords: list[str]) -> list[dict]:
    found: dict[str, dict] = {}
    for keyword in keywords:
        tags = "+".join(w for w in keyword.lower().split() if w)
        query = urllib.parse.urlencode({"f": "json", "tags": tags, "limit": 40, "sort": "rank"})
        try:
            data = get(f"{CCMIXTER}?{query}")
        except (OSError, ValueError) as error:
            print(f"  ccmixter {keyword!r}: {str(error)[:80]} - skipped")
            continue
        for upload in data if isinstance(data, list) else []:
            licence_url = upload.get("license_url") or ""
            kind = re.search(r"/(?:licenses|publicdomain)/([a-z-]+)/(\d\.\d)?", licence_url)
            files = [f for f in upload.get("files") or [] if str(f.get("download_url", "")).endswith(".mp3")]
            if not kind or not files:
                continue
            licence = {"zero": "cc0", "by": "by", "by-sa": "by-sa"}.get(kind.group(1))
            if licence is None:  # NC, ND, sampling+...: not usable in a commercial, edited video
                continue
            found.setdefault(f"ccmixter:{upload.get('upload_id')}", {
                "id": upload.get("upload_id"), "title": upload.get("upload_name"),
                "creator": upload.get("user_real_name") or upload.get("user_name"),
                "license": licence, "license_version": kind.group(2) or "",
                "license_url": licence_url, "duration": _playtime_ms(files[0].get("file_format_info")),
                "url": files[0]["download_url"], "foreign_landing_url": upload.get("file_page_url"),
                "tags": [{"name": t} for t in str(upload.get("upload_tags", "")).split(",") if t],
                "source": "ccmixter"})
    return list(found.values())


def score(track: dict, keywords: list[str], length: float) -> float | None:
    seconds = (track.get("duration") or 0) / 1000
    text = " ".join([track.get("title") or "", " ".join(t.get("name", "") for t in track.get("tags") or [])])
    usable = seconds and track.get("url") and track.get("license") in GOOD_LICENSES
    if not usable or VOCALS.search(text):
        return None
    s = 0.0
    words = {w for k in keywords for w in k.lower().split()}
    s += 2.0 * sum(1 for w in words if w in text.lower())
    s += 1.5 if re.search(r"instrumental", text, re.I) else 0.0
    if seconds >= length:
        s += 6.0 - min(2.0, (seconds / length - 1))  # long enough; not absurdly long
    else:
        s -= 6.0 * (1 - seconds / length)  # would loop
    s += 0.5 if track["license"] in ("cc0", "by", "pdm") else 0.0  # simpler credit than BY-SA
    return s


def search(keywords: list[str], length: float, count: int) -> list[dict]:
    tracks = search_openverse(keywords)
    long_enough = [t for t in tracks if score(t, keywords, length) is not None
                   and (t.get("duration") or 0) / 1000 >= length]
    if len(long_enough) < count:
        print(f"  {len(long_enough)} long-enough track(s) on Openverse: also searching ccMixter")
        tracks += search_ccmixter(keywords)
    return tracks


def credit(track: dict) -> str:
    licence = f"CC {track['license'].upper()} {track.get('license_version') or ''}".strip()
    if track["license"] in ("cc0", "pdm"):
        licence = "public domain (CC0)"
    return (f"Music: \"{track.get('title')}\" by {track.get('creator') or 'unknown'} "
            f"({track.get('foreign_landing_url') or track.get('detail_url')}), licensed under "
            f"{licence} ({track.get('license_url')}).")


def download(track: dict, target: Path) -> float:
    request = urllib.request.Request(track["url"], headers=HEADERS)
    with urllib.request.urlopen(request, timeout=120) as response:
        target.write_bytes(response.read())
    return duration(target)


def set_music(config, relative: str, credit_line: str) -> None:
    toml = config.root / "demo.toml"
    text = toml.read_text(encoding="utf-8")
    value = f'music = "{relative}"'
    if re.search(r"(?m)^music\s*=.*$", text):
        text = re.sub(r"(?m)^music\s*=.*$", lambda _: value, text, count=1)
    elif re.search(r"(?m)^\[montage\]\s*$", text):
        text = re.sub(r"(?m)^\[montage\]\s*$", lambda _: "[montage]\n" + value, text, count=1)
    else:
        text = text.rstrip() + f"\n\n[montage]\n{value}\n"
    toml.write_text(text, encoding="utf-8")
    credits = config.root / "montage" / "CREDITS.txt"
    credits.parent.mkdir(parents=True, exist_ok=True)
    credits.write_text((credit_line or "Music: no credit given - check the track's licence") + "\n",
                       encoding="utf-8")
    print(f"montage.music = {relative}")
    print(f"credit (video description or end screen): {credit_line or '- none given, check the licence'}")


def use_file(config, path: Path, credit_line: str) -> int:
    source = path if path.is_absolute() else (Path.cwd() / path)
    if not source.is_file():
        raise SystemExit(f"{source} not found")
    folder = config.root / "montage" / "music"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    if source.resolve() != target.resolve():
        target.write_bytes(source.read_bytes())
    seconds, length = duration(target), video_length(config)
    if seconds < length:
        print(f"note: {seconds / 60:.1f} min of music for a {length / 60:.1f} min video - it will loop")
    set_music(config, f"montage/music/{target.name}", credit_line)
    return 0


def pick(config, number: int) -> int:
    folder = config.root / "montage" / "music"
    data = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    chosen = next((c for c in data["candidates"] if c["number"] == number), None)
    if chosen is None:
        raise SystemExit(f"no candidate {number} (see {folder / 'candidates.md'})")
    if not chosen["file"]:
        raise SystemExit(f"candidate {number} was not downloaded: get it from {chosen['page']}, "
                         "then use --use <file> --credit")
    set_music(config, f"montage/music/{chosen['file']}", chosen["credit"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("--tone", default="corporate", choices=sorted(TONES))
    parser.add_argument("--keywords", default="", help="extra or replacement keywords, comma separated")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--pick", type=int, help="use this candidate for the montage")
    parser.add_argument("--use", type=Path, help="use your own audio file for the montage")
    parser.add_argument("--credit", default="", help="with --use: the credit its licence requires")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    if args.pick:
        return pick(config, args.pick)
    if args.use:
        return use_file(config, args.use, args.credit)

    length = video_length(config)
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()] or TONES[args.tone]
    print(f"video length {length / 60:.1f} min - searching {args.tone!r} music: {', '.join(keywords)}")
    tracks = search(keywords, length, args.count)
    scored = [(s, t) for t in tracks if (s := score(t, keywords, length)) is not None]
    scored.sort(key=lambda x: -x[0])
    chosen, creators = [], set()
    for _, track in scored:  # different authors, for really different moods
        if track.get("creator") in creators:
            continue
        chosen.append(track)
        creators.add(track.get("creator"))
        if len(chosen) == args.count:
            break
    if not chosen:
        print("NO MUSIC FOUND (sources unreachable or no match). Search the web for royalty-free "
              "tracks instead (references/voice-and-montage.md), then `run.py music --use <file> "
              "--credit \"...\"`.")
        return 1

    folder = config.root / "montage" / "music"
    folder.mkdir(parents=True, exist_ok=True)
    entries, lines = [], [f"# Music candidates - {args.tone}, video {length / 60:.1f} min", ""]
    for number, track in enumerate(chosen, start=1):
        file = f"candidate-{number}.mp3"
        try:
            seconds = download(track, folder / file)
        except (OSError, urllib.error.URLError) as error:
            # The site refuses automatic downloads: the user downloads it from its page.
            print(f"  candidate {number}: not downloadable automatically ({error}) - "
                  "listen and download it from its page, then --use <file>")
            seconds = (track.get("duration") or 0) / 1000
            file = ""
        loops = seconds < length
        entry = {"number": number, "file": file, "title": track.get("title"),
                 "creator": track.get("creator"), "seconds": round(seconds, 1),
                 "license": f"{track['license']} {track.get('license_version') or ''}".strip(),
                 "page": track.get("foreign_landing_url"), "source": track.get("source"),
                 "credit": credit(track), "loops": loops,
                 "tags": [t.get("name") for t in (track.get("tags") or [])][:8]}
        entries.append(entry)
        clock = f"{int(seconds // 60)}:{int(seconds % 60):02d}"
        lines += [f"## {number}. {entry['title']} - {entry['creator']}",
                  f"- length {clock}{'  (shorter than the video: it will loop)' if loops else ''}",
                  f"- licence {entry['license']} · source {entry['source']} · listen: {entry['page']}",
                  f"- file: `montage/music/{file}`" if file else "- file: not downloaded",
                  f"- tags: {', '.join(t for t in entry['tags'] if t)}",
                  f"- credit to publish: {entry['credit']}", ""]
        print(f"{number}. {entry['title']} - {entry['creator']} ({clock}, {entry['license']}, "
              f"{entry['source']}){'  [loops]' if loops else ''}\n   {entry['page']}")
    if len(entries) < args.count or not all(e["file"] for e in entries):
        missing = args.count - sum(1 for e in entries if e["file"])
        print(f"ONLY {args.count - missing} OF {args.count} CANDIDATES READY: complete the proposal with "
              "a web search for royalty-free tracks (references/voice-and-montage.md).")
        lines.append(f"Only {args.count - missing} of {args.count} candidates could be downloaded: "
                     "complete with a web search.")
    lines.append("Choose one with `run.py music --pick <N>`, or `--use <file> --credit \"...\"`.")
    (folder / "candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "candidates.json").write_text(json.dumps({"tone": args.tone, "video_s": length,
                                                        "candidates": entries}, indent=1),
                                            encoding="utf-8")
    print(f"-> {folder / 'candidates.md'} - listen, then `run.py music --pick <N>`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
