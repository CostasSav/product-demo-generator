"""Local transcription of the voice-over (faster-whisper), word by word, with timestamps.

    run.py transcribe --demo-dir demo voiceover.mp3 [--model medium]

Nothing leaves the machine (the model is downloaded once from huggingface.co). Writes
`voice/transcription.json`: the words with their start, end and probability.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from demokit import config as config_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("audio", help="file in voice/ (or any path)")
    parser.add_argument("--model", help="whisper model (default: voice.whisper_model)")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    audio = Path(args.audio)
    if not audio.is_absolute() and not audio.is_file():
        audio = config.voice_dir / audio
    if not audio.is_file():
        raise SystemExit(f"{audio} not found")

    import numpy as np
    from faster_whisper import WhisperModel

    began = time.monotonic()
    name = args.model or config.section("voice")["whisper_model"]
    try:  # the cached model first: no network round trip, works offline
        model = WhisperModel(name, device="cpu", compute_type="int8", local_files_only=True)
    except Exception:  # not cached (or incomplete): download it
        print(f"downloading whisper model {name} (once)…", flush=True)
        model = WhisperModel(name, device="cpu", compute_type="int8")
    # Decoded by ffmpeg: some PyAV builds refuse faster-whisper's own decoding.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    signal = np.frombuffer(raw, dtype=np.float32)
    segments, info = model.transcribe(
        signal, language=config.section("project")["language"], word_timestamps=True,
        vad_filter=False, beam_size=5, condition_on_previous_text=False,
    )
    words = []
    for segment in segments:
        for word in segment.words or []:
            words.append({"word": word.word.strip(), "start": round(word.start, 3),
                          "end": round(word.end, 3), "probability": round(word.probability, 3)})
        print(f"{segment.end:7.1f} s  {segment.text.strip()[:90]}", flush=True)
    output = config.voice_dir / "transcription.json"
    output.write_text(json.dumps({"audio": str(audio), "duration": info.duration, "words": words},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(words)} words in {time.monotonic() - began:.0f} s → {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
