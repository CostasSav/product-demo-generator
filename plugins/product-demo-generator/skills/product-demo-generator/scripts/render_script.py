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
## Why your own voice

The video currently uses a synthetic placeholder voice, for timing only. A real voice — yours, or
a colleague's — is what makes a demo credible: viewers forgive a slight accent or a breath, not a
robotic read. No studio needed.

## How to record

- **Where:** a small, quiet room with soft furnishings (a bedroom beats a meeting room); close
  the windows, mute notifications. A phone's voice-memo app is fine, held 15–20 cm from your
  mouth, slightly to the side; a headset or USB microphone is better.
- **How:** read the script aloud once to warm up, then record at a calm pace (about 150 words a
  minute), smiling slightly — it shows in the voice.
- Record **everything in one take, in order**, as a single audio file (wav, mp3 or m4a).
- Leave **about one second of silence between two scenes**; never read the scene numbers.
- Short opening words ("One," "Two,") are fine — the split keeps them with their scene.
- A slip? Pause, say the whole sentence again and carry on; tell Claude which lines you repeated,
  so the split of those scenes can be checked.
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
