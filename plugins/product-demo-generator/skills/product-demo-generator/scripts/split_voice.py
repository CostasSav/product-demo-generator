"""Split the single voice-over recording into one file per scene, aligned on the script.

    run.py split --demo-dir demo voiceover.mp3

Inputs: scenes.json (each scene's line) and voice/transcription.json (`run.py transcribe`).
Alignment is word by word (difflib: tolerant of swallowed or mistranscribed words). Each cut
falls in a silence (ffmpeg silencedetect), never in the middle of a syllable — the **first**
silence after the last word of the scene that ends: Whisper mis-times short words that open a
scene ("One," transcribed "1." with a zero duration), and cutting in the longest nearby silence
left them at the end of the previous scene.

Outputs: voice/<scene>.wav (48 kHz mono) and voice/split.json / split.txt (start, end, share of
the script's words found, warnings). A scene whose words are not in the recording gets no file:
the montage shows its picture without voice.
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import json
import re
import sys
import unicodedata
from pathlib import Path

from demokit import config as config_module
from demokit.media import ffmpeg, silences

WORD_S = 0.33  # to estimate a start or end whose words were not found
MIN_CONFIDENCE = 0.75


def number_words(token: str, language: str) -> list[str]:
    """Whisper writes some numbers as digits ("3. The references"); scripts often spell them."""
    try:
        from num2words import num2words

        spelled = num2words(int(token), lang=language)
    except Exception:  # unsupported language or not a plain integer
        return [token]
    return tokens(spelled, language, numbers=False)


def tokens(text: str, language: str = "en", numbers: bool = True) -> list[str]:
    text = unicodedata.normalize("NFD", text.lower().replace("’", "'"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    out: list[str] = []
    for token in re.split(r"[^a-z0-9]+", text):
        if not token:
            continue
        out.extend(number_words(token, language) if numbers and token.isdigit() else [token])
    return out


def align(texts: list[str], words: list[dict], language: str) -> list[dict | None]:
    """Start, end and confidence of each scene in the recording (None: not spoken)."""
    script, scene_of = [], []
    for index, text in enumerate(texts):
        for token in tokens(text, language):
            script.append(token)
            scene_of.append(index)
    heard, word_of = [], []
    for k, word in enumerate(words):
        for token in tokens(word["word"], language):
            heard.append(token)
            word_of.append(k)
    match: dict[int, int] = {}
    for block in difflib.SequenceMatcher(None, script, heard, autojunk=False).get_matching_blocks():
        for d in range(block.size):
            match[block.a + d] = block.b + d
    bounds: list[dict | None] = []
    for index in range(len(texts)):
        positions = [k for k, s in enumerate(scene_of) if s == index]
        found = [k for k in positions if k in match]
        if not found:
            bounds.append(None)
            continue
        first, last = found[0], found[-1]
        start = words[word_of[match[first]]]["start"] - (first - positions[0]) * WORD_S
        end = words[word_of[match[last]]]["end"] + (positions[-1] - last) * WORD_S
        bounds.append({"start": start, "end": end, "confidence": len(found) / len(positions)})
    return bounds


def cut_between(previous: dict, following: dict,
                pauses: list[tuple[float, float]]) -> tuple[float, float]:
    """Where to cut between two spoken scenes: (time, length of the silence used)."""
    window = (min(previous["end"], following["start"]) - 0.25,
              max(previous["end"], following["start"]) + 0.25)
    candidates = [(s, e) for s, e in pauses if e > window[0] and s < window[1]]
    after_end = [(s, e) for s, e in candidates if e > previous["end"] + 0.05]
    if after_end:
        s, e = min(after_end)
        return (s + e) / 2, e - s
    if candidates:
        s, e = max(candidates, key=lambda p: p[1] - p[0])
        return (s + e) / 2, e - s
    return (previous["end"] + following["start"]) / 2, 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("audio")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    audio = Path(args.audio)
    if not audio.is_absolute() and not audio.is_file():
        audio = config.voice_dir / audio
    transcription = json.loads((config.voice_dir / "transcription.json").read_text(encoding="utf-8"))
    total = float(transcription["duration"])
    scenes = [s for s in config.scenes if s.text]
    bounds = align([s.text for s in scenes], transcription["words"],
                   config.section("project")["language"])
    pauses = silences(audio)

    spoken = [i for i, b in enumerate(bounds) if b is not None]
    cuts: list[tuple[float, float] | None] = [None] * len(scenes)  # cut at the END of scene i
    for i, j in itertools.pairwise(spoken):
        cuts[i] = cut_between(bounds[i], bounds[j], pauses)

    results, lines = [], []
    previous_cut: tuple[float, float] | None = None
    for i, scene in enumerate(scenes):
        bound = bounds[i]
        if bound is None:
            results.append({"scene": scene.id, "absent": True})
            lines.append(f"{scene.id:6}  —  not in the recording: picture without voice")
            continue
        warnings = []
        if bound["confidence"] < MIN_CONFIDENCE:
            warnings.append(f"few words found ({bound['confidence']:.0%}): listen to it")
        start = previous_cut[0] if previous_cut else max(0.0, bound["start"] - 0.3)
        end = cuts[i][0] if cuts[i] else min(total, bound["end"] + 0.6)
        if cuts[i] and cuts[i][1] < 0.12:
            warnings.append("no pause before the next scene: check the cut")
        previous_cut = cuts[i]
        output = config.voice_dir / f"{scene.id}.wav"
        ffmpeg("-i", str(audio), "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-ar", "48000",
               "-ac", "1", str(output))
        results.append({"scene": scene.id, "start": round(start, 3), "end": round(end, 3),
                        "duration": round(end - start, 3), "confidence": round(bound["confidence"], 3),
                        "file": output.name, "warnings": warnings})
        lines.append(f"{scene.id:6} {start:7.2f} → {end:7.2f}  ({end - start:5.2f} s)  "
                     f"{bound['confidence']:4.0%}  {'; '.join(warnings)}")
    (config.voice_dir / "split.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    header = f"Split of {audio.name} ({total:.1f} s) — scene, start → end, duration, words found"
    (config.voice_dir / "split.txt").write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    print(header)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
