"""Look at a video without watching it: contact sheets of frames, and "what is at 5:38?".

    run.py sheet video.mp4 --at 1:28,1:30.5,1:33 [--width 480] [--out sheet.png]
    run.py sheet video.mp4 --from 12 --to 24 --every 1          # one frame per second
    run.py where --demo-dir demo 5:38                           # scene, take, source second

`where` reads montage/plan.json: it names the scene playing at that time in the final video, the
take and the second of the source video it comes from — the starting point of every fix asked as
"at 5:38 there is a loading page".
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

from demokit import config as config_module
from demokit.media import duration, ffmpeg, font


def seconds(value: str) -> float:
    parts = [float(p) for p in value.strip().split(":")]
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def clock(value: float) -> str:
    return f"{int(value // 60)}:{value % 60:04.1f}"


def sheet(video: Path, times: list[float], width: int, output: Path) -> Path:
    # A time past the end shows the last frame (ffmpeg would write nothing).
    last = max(duration(video) - 0.1, 0.0)
    times = [min(t, last) for t in times]
    with tempfile.TemporaryDirectory() as folder:
        frames = []
        for i, t in enumerate(times):
            frame = Path(folder) / f"f{i:03d}.png"
            label = clock(t).replace(":", "\\:")
            ffmpeg("-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-vf",
                   f"scale={width}:-2,drawtext=fontfile='{font()}':text='{label}':fontsize=22"
                   ":fontcolor=white"
                   ":box=1:boxcolor=black@0.6:boxborderw=6:x=8:y=8", str(frame))
            frames.append(frame)
        columns = min(3, len(frames))
        rows = math.ceil(len(frames) / columns)
        layout = "|".join(_cell(i, columns) for i in range(len(frames)))
        inputs = [arg for f in frames for arg in ("-i", str(f))]
        if len(frames) == 1:
            ffmpeg(*inputs, str(output))
        else:
            ffmpeg(*inputs, "-filter_complex",
                   f"xstack=inputs={len(frames)}:layout={layout}:fill=black", str(output))
    print(f"{output} — {len(times)} frames, {rows} row(s)")
    return output


def _cell(index: int, columns: int) -> str:
    x = "+".join(["w0"] * (index % columns)) or "0"
    y = "+".join(["h0"] * (index // columns)) or "0"
    return f"{x}_{y}"


def where(demo_dir: Path, at: float) -> int:
    config = config_module.load(demo_dir)
    plan = json.loads((config.root / "montage" / "plan.json").read_text(encoding="utf-8"))
    entries = plan["scenes"]
    for i, entry in enumerate(entries):
        start = entry["start_in_video_s"]
        end = entries[i + 1]["start_in_video_s"] if i + 1 < len(entries) else plan["total_s"]
        if start <= at < end:
            offset = at - start
            print(f"{clock(at)} is scene {entry['scene']} ({entry['mode']}), "
                  f"{offset:.1f} s into it ({clock(start)} → {clock(end)})")
            print(f"  voice {entry['voice_s']} s · clip {entry['duration_s']} s · speed "
                  f"{entry.get('speed', '×1')}")
            if "source_video" in entry:
                print(f"  take {entry['take']}: {entry['source_video']} "
                      f"{entry['source_start_s']} → {entry['source_end_s']} s")
                print("  to look at the source: run.py sheet "
                      f"{config.root / entry['source_video']} --from {entry['source_start_s']} "
                      f"--to {entry['source_end_s']} --every 1")
            for warning in entry.get("warnings", []):
                print(f"  warning: {warning}")
            return 0
    print(f"{clock(at)} is after the end ({clock(plan['total_s'])}): the outro")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--where", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("target", help="video (sheet) or timestamp m:ss (where)")
    parser.add_argument("--at", default="", help="timestamps, comma separated (m:ss or seconds)")
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--every", type=float, default=1.0)
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.where:
        return where(args.demo_dir, seconds(args.target))
    video = Path(args.target)
    if args.at:
        times = [seconds(t) for t in args.at.split(",") if t.strip()]
    elif args.start is not None and args.end is not None:
        a, b = seconds(args.start), seconds(args.end)
        times = [a + i * args.every for i in range(int((b - a) / args.every) + 1)]
    else:
        raise SystemExit("give --at, or --from and --to")
    if len(times) > 24:
        raise SystemExit(f"{len(times)} frames: too many for one sheet (24 at most)")
    sheet(video, times, args.width, args.out or video.with_suffix(".sheet.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
