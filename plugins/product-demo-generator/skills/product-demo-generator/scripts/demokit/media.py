"""ffmpeg / ffprobe helpers shared by the voice and montage commands."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FONT_CANDIDATES = {
    "regular": [
        "C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ],
    "bold": [
        "C:/Windows/Fonts/seguisb.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ],
}


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def loudness(path: Path) -> float:
    """Integrated loudness (LUFS, EBU R128)."""
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stderr
    values = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    if not values:
        raise RuntimeError(f"could not measure the loudness of {path}")
    return float(values[-1])


def silences(path: Path, noise_db: float = -35, min_s: float = 0.12) -> list[tuple[float, float]]:
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af",
         f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return list(zip(starts, ends, strict=False))


def escape_text(text: str) -> str:
    """Text for ffmpeg's drawtext filter."""
    return (text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")
            .replace("%", "\\%").replace(",", "\\,"))


def font(kind: str = "regular", configured: str = "") -> str:
    """A font file for drawtext, escaped for the filter graph."""
    candidates = ([configured] if configured else []) + FONT_CANDIDATES[kind]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            path = Path(candidate).as_posix()
            return path.replace(":", "\\:") if sys.platform == "win32" else path
    raise RuntimeError(f"no {kind} font found: set montage.font / montage.font_bold in demo.toml")


def voice_file(voice_dir: Path, scene_id: str) -> tuple[Path | None, bool]:
    """The voice of a scene: the recorded one (`voice/<id>.wav`) if any, else the placeholder
    (`voice/placeholder/<id>.wav`). Returns (path or None, is_placeholder)."""
    recorded = voice_dir / f"{scene_id}.wav"
    if recorded.is_file():
        return recorded, False
    placeholder = voice_dir / "placeholder" / f"{scene_id}.wav"
    if placeholder.is_file():
        return placeholder, True
    return None, False
