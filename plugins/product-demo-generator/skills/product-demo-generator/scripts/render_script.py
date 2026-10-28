"""Turn scenes.json into the voice-over recording script (`voice/voiceover.md`).

    run.py script --demo-dir demo [--wpm 150]

The script lists every line in order, act by act, with what is on screen, and the recording
rules that make the automatic split reliable.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from demokit import config as config_module

RULES = """\
## How to record

- Record **everything in one take, in order**, as a single audio file (wav, mp3 or m4a).
- Leave **about one second of silence between two scenes**; never read the scene numbers.
- Short opening words ("One," "Two,") are fine — the split keeps them with their scene.
- A line you skip is not a problem: that scene keeps its picture without voice.
- Put the file in `voice/` and tell Claude its name.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("--wpm", type=float, default=150.0, help="speaking rate for the estimate")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    lines = [f"# Voice-over — {config.section('project')['name']}", "", RULES]
    words = 0
    act = None
    for scene in config.scenes:
        if scene.act != act:
            act = scene.act
            lines += ["", f"## Act {act}", ""]
        count = len(scene.text.split())
        words += count
        lines += [f"**{scene.id}** · _{scene.mode}_ · {scene.screen}", "",
                  f"> {scene.text}" if scene.text else "> _(no voice)_", ""]
    minutes = words / args.wpm
    lines.insert(2, f"{len(config.scenes)} scenes · {words} words · about {minutes:.1f} min of "
                    f"voice at {args.wpm:.0f} words/min\n")
    output = config.voice_dir / "voiceover.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{output} — {words} words, ~{minutes:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
