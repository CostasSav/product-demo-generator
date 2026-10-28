"""Film the demo: the live pass (app in normal mode, costly scenes really played, state saved after
each step) or one act's retake (app in safe mode, costly scenes replaced by restoring the state
that follows them).

    run.py film --demo-dir demo --mode live                      # the whole live pass
    run.py film --demo-dir demo --mode live --from 3.2 --restore 03-before-generate
    run.py film --demo-dir demo --mode retake --act 2            # one act, nothing costly
    run.py film --demo-dir demo --mode retake --act 2 --pace 0.8 --duration 2.3=12

The project's `acts.py` (in the demo folder) defines:
    ACTS = {1: act_1, 2: act_2, ...}           # async def act_1(t: Director) -> None
    ACT_START = {1: "00-start", 2: "01-...", ...}  # save restored before each act in a retake

Retake scene durations: the scene's voice (recorded, else placeholder) + filming.voice_pad_s,
so the picture lasts as long as the line it illustrates. Videos and chapters go to
`takes/live/<timestamp>/` or `takes/retakes/<timestamp>-act<N>/`.

Exit codes: 0 done · 3 clean stop (pause, budget, failure: see the message, nothing relaunched).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

from demokit import config as config_module
from demokit.director import CleanStop, Director, log
from demokit.media import duration, voice_file


def load_acts(demo_dir: Path):
    path = demo_dir / "acts.py"
    if not path.is_file():
        raise SystemExit(f"{path} not found: write the acts first (template: templates/acts.py)")
    sys.path.insert(0, str(demo_dir))
    spec = importlib.util.spec_from_file_location("demo_acts", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    if not hasattr(module, "ACTS"):
        raise SystemExit(f"{path} must define ACTS = {{number: async function}}")
    return module


def scene_durations(config, overrides: list[str]) -> dict[str, float]:
    pad = float(config.section("filming")["voice_pad_s"])
    durations = {}
    for scene in config.scenes:
        path, _ = voice_file(config.voice_dir, scene.id)
        if path is not None:
            durations[scene.id] = round(duration(path) + pad, 2)
    for item in overrides:
        scene_id, _, value = item.partition("=")
        if not value:
            raise SystemExit(f"--duration expects SCENE=SECONDS, got {item!r}")
        durations[scene_id.strip()] = float(value)
    return durations


async def run(args: argparse.Namespace) -> int:
    config = config_module.load(args.demo_dir)
    acts = load_acts(config.root)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.mode == "retake":
        if args.act is None:
            raise SystemExit("--act is required for a retake")
        output = config.takes_dir / "retakes" / f"{stamp}-act{args.act}"
        durations = scene_durations(config, args.duration)
    else:
        output = config.takes_dir / "live" / stamp
        durations = scene_durations(config, args.duration) if args.duration else {}
    director = Director(config, args.mode, output, durations, from_scene=args.from_scene,
                        headed=args.headed or None, pace=args.pace)
    numbers = [args.act] if args.act is not None else sorted(acts.ACTS)
    starts = getattr(acts, "ACT_START", {})
    try:
        async with director:
            if args.mode == "retake":
                start = starts.get(args.act)
                if start and (director.snapshots.saves_dir / start / "state.json").is_file():
                    await director.restore(start)
                elif start:
                    log(f"⚠ rehearsal: save {start!r} missing — filming from the current state")
            elif args.restore:
                await director.restore(args.restore, note=f"resume from {args.from_scene}")
            elif not args.from_scene:
                await director.save("00-start")
            for number in numbers:
                if args.from_scene and args.mode == "live":
                    act_scenes = [s.id for s in config.scenes if s.act == number]
                    if act_scenes and all(director._rank(s) < director._rank(args.from_scene)
                                          for s in act_scenes):
                        continue
                await acts.ACTS[number](director)
    except CleanStop as stop:
        print(f"\nCLEAN STOP — {stop.step}: {stop.cause}\nTo resume: {stop.resume}\n"
              f"Videos so far: {output}")
        return 3
    log(f"{args.mode} done — videos in {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("--mode", choices=("live", "retake"), required=True)
    parser.add_argument("--act", type=int)
    parser.add_argument("--from", dest="from_scene", help="live: resume at this scene")
    parser.add_argument("--restore", help="live: save to restore before resuming")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--pace", type=float, help="multiplies every pause (0.7 = faster)")
    parser.add_argument("--duration", action="append", default=[], metavar="SCENE=SECONDS")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
