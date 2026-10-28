"""Placeholder voice-over with Piper (local text-to-speech, nothing leaves the machine).

    run.py tts --demo-dir demo [--voice en_US-lessac-medium] [--scenes 1.1,1.2] [--full]

Writes `voice/placeholder/<scene>.wav` for every scene with a line. Retakes and the montage use
them until the real recording is split into `voice/<scene>.wav`, which always wins. `--full` also
writes `voice/placeholder/full.wav` (every line in order, one second apart) — handy to test the
transcription and split before the real recording exists.

Voices: https://huggingface.co/rhasspy/piper-voices (e.g. en_US-lessac-medium, en_GB-alan-medium,
fr_FR-siwis-medium, de_DE-thorsten-medium, es_ES-davefx-medium). The first use downloads the voice
into the tool directory (needs network access to huggingface.co).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import wave
from pathlib import Path

from demokit import config as config_module
from demokit.media import ffmpeg

PLACEHOLDER_WARNING = """
!! PLACEHOLDER VOICE - for timing only. A synthetic voice makes a demo sound cheap and costs it
!! credibility: record the real voice-over (voice/voiceover.md, `run.py script`), even with a phone
!! in a quiet room - it is the single biggest quality gain of the whole video."""


def voices_dir() -> Path:
    default = Path.home() / ".cache" / "product-demo-generator"
    return Path(os.environ.get("PRODUCT_DEMO_GENERATOR_HOME", default)) / "voices"


def load_voice(name: str):
    from piper import PiperVoice

    folder = voices_dir()
    model = folder / f"{name}.onnx"
    if not model.is_file() or not model.with_suffix(".onnx.json").is_file():
        folder.mkdir(parents=True, exist_ok=True)
        print(f"downloading Piper voice {name} → {folder}")
        subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir",
                        str(folder), name], check=True)
    return PiperVoice.load(str(model))


def synthesize(voice, text: str, output: Path) -> None:
    raw = output.with_suffix(".raw.wav")
    with wave.open(str(raw), "wb") as file:
        voice.synthesize_wav(text, file)
    # 48 kHz mono like a real recording; a short breath of silence at the end.
    ffmpeg("-i", str(raw), "-af", "apad=pad_dur=0.25", "-ar", "48000", "-ac", "1", str(output))
    raw.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("--voice", help="Piper voice (default: voice.tts_voice in demo.toml)")
    parser.add_argument("--scenes", default="", help="only these scenes (comma separated)")
    parser.add_argument("--full", action="store_true", help="also write one file with every line")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    voice = load_voice(args.voice or config.section("voice")["tts_voice"])
    wanted = {s.strip() for s in args.scenes.split(",") if s.strip()}
    output_dir = config.voice_dir / "placeholder"
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for scene in config.scenes:
        if not scene.text or (wanted and scene.id not in wanted):
            continue
        path = output_dir / f"{scene.id}.wav"
        synthesize(voice, scene.text, path)
        written.append(path)
        print(f"{scene.id:6} {path.name}")
    if args.full and written:
        listing = output_dir / "full.txt"
        silence = output_dir / "_gap.wav"
        ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "1.0", str(silence))
        entries = []
        for path in written:
            entries += [f"file '{path.as_posix()}'", f"file '{silence.as_posix()}'"]
        listing.write_text("\n".join(entries) + "\n", encoding="utf-8")
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
               str(output_dir / "full.wav"))
        listing.unlink()
        silence.unlink()
        print(f"full file: {output_dir / 'full.wav'}")
    print(f"{len(written)} placeholder lines in {output_dir}")
    print(PLACEHOLDER_WARNING)
    return 0


if __name__ == "__main__":
    sys.exit(main())
