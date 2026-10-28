"""Assemble the demo video: every scene is cut from its take and fitted to its voice-over line.

    run.py montage --demo-dir demo                      # everything
    run.py montage --demo-dir demo --reuse --redo 3.2,3.3   # re-cut only these scenes

Inputs: scenes.json (order, mode, per-scene options), voice/<scene>.wav (else the placeholder),
the takes and their `.chapters.json`, slides for `slide` scenes, music (`montage.music`).

Fitting rules, scene by scene (L = voice length + montage.breath_s, 2 s at least):
- realtime: a take shorter than L holds its last frame; a longer one is sped up to
  montage.max_realtime_speedup at most (beyond, the picture runs on after the voice — warned);
- accelerated (waiting for a job): frozen frames are dropped (mpdecimate) when enough motion
  remains, then the rest is sped up to fill exactly L, with a "real time: X min" counter;
- slide: a still image (slides/<file>), consecutive scenes of the same `group` crossfade, each
  fade centred on the boundary so the voice never moves;
- slideshow: the images of `images` (a glob), spread over the scene;
- card: a plain title card (overlay or screen text) — a placeholder to replace.

Never slowed down. Per-scene options (scenes.json): `take` ("live", "retake" or a folder),
`source_scene`, `cap_s` (keep only the first seconds), `segments` ([[start, end, factor], …]
relative to the scene, negative = from its end, factor null = fill the rest; what is not covered
is dropped — use it to cut loading screens), `real_minutes` (counter value), `overlay` (caption).

Each clip's audio is re-timed to the clip's REAL duration (rounded to frames) — otherwise the
rounding drifts and the voice ends up late. Music: set ~music_gap_db under the voice, ducked
further while the voice speaks (side-chain), faded in, faded out with the outro (fade applied
after the compressor, mixed in a separate pass, limiter without auto-level).

Outputs: the video, and montage/plan.json / plan.txt (per scene: start in the final video, take,
source offsets, speed, warnings) — read by `run.py where` to map a timestamp back to its scene.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from demokit import config as config_module
from demokit.config import DemoConfig, Scene
from demokit.media import duration, escape_text, ffmpeg, font, loudness, voice_file


class Montage:
    def __init__(self, config: DemoConfig) -> None:
        self.config = config
        m = config.section("montage")
        self.fps = int(m["fps"])
        browser = config.section("browser")
        self.width, self.height = int(browser["width"]), int(browser["height"])
        self.breath = float(m["breath_s"])
        self.max_speedup = float(m["max_realtime_speedup"])
        self.crossfade = float(m["crossfade_s"])
        self.counter_label = m["counter_label"]
        self.slideshow_seconds = float(m["slideshow_seconds"])
        self.font = font("regular", m["font"])
        self.font_bold = font("bold", m["font_bold"])
        self.work = config.root / "montage" / "clips"
        self.work.mkdir(parents=True, exist_ok=True)
        self._groups: dict[str, tuple[Path, dict[str, float]]] = {}

    # -- encoding helpers ---------------------------------------------------------------------

    def _encode(self) -> list[str]:
        return ["-r", str(self.fps), "-c:v", "libx264", "-preset", "superfast", "-crf", "18",
                "-pix_fmt", "yuv420p"]

    def overlay_filter(self, text: str | None) -> str:
        if not text:
            return ""
        return (f",drawtext=fontfile='{self.font_bold}':text='{escape_text(text)}':fontsize=34"
                ":fontcolor=white:box=1:boxcolor=0x1e1b4b@0.82:boxborderw=18:x=60:y=h-130")

    def counter_filter(self, minutes: float | None) -> str:
        if not minutes:
            return ""
        value = f"{minutes:.0f} min" if minutes >= 1 else f"{minutes * 60:.0f} s"
        text = f"{self.counter_label}: {value}"
        return (f",drawtext=fontfile='{self.font}':text='{escape_text(text)}':fontsize=28"
                ":fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=12:x=w-tw-50:y=40")

    # -- targets and takes ----------------------------------------------------------------------

    def voice(self, scene: Scene) -> tuple[Path | None, bool, float]:
        path, placeholder = voice_file(self.config.voice_dir, scene.id)
        return path, placeholder, (duration(path) if path else 0.0)

    def target(self, scene: Scene) -> float:
        return max(self.voice(scene)[2] + self.breath, 2.0)

    def take_folder(self, scene: Scene) -> Path | None:
        takes = self.config.takes_dir
        wanted = scene.take or ("live" if scene.costly else "retake")
        if wanted not in ("live", "retake"):
            folder = self.config.path(wanted)
            return folder if folder.is_dir() else None
        source = scene.source_scene or scene.id

        def has_scene(folder: Path) -> bool:
            chapters = folder / f"act{scene.act}.chapters.json"
            if not chapters.is_file():
                return False
            data = json.loads(chapters.read_text(encoding="utf-8"))
            return any(c["scene"] == source for c in data["scenes"])

        retakes = sorted(takes.glob(f"retakes/*-act{scene.act}"), reverse=True)
        lives = sorted(takes.glob("live/*"), reverse=True)
        order = (lives + retakes) if wanted == "live" else (retakes + lives)
        return next((f for f in order if has_scene(f)), None)

    def segment(self, folder: Path, scene: Scene) -> tuple[Path, float, float] | None:
        chapters = folder / f"act{scene.act}.chapters.json"
        video = folder / f"act{scene.act}.mp4"
        if not chapters.is_file() or not video.is_file():
            return None
        source = scene.source_scene or scene.id
        for chapter in json.loads(chapters.read_text(encoding="utf-8"))["scenes"]:
            if chapter["scene"] == source:
                end = chapter["end_s"] if chapter["end_s"] is not None else duration(video)
                return video, chapter["start_s"], end
        return None

    # -- clips ------------------------------------------------------------------------------------

    def clip_video(self, output: Path, source: Path, start: float, end: float, target: float,
                   accelerated: bool, overlay: str | None, minutes: float | None) -> dict:
        info: dict = {"source_s": round(end - start, 2)}
        raw = self.work / f"{output.stem}.raw.mp4"
        base = [f"scale={self.width}:{self.height}", f"fps={self.fps}"]

        def extract(filters: list[str]) -> float:
            ffmpeg("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(source), "-an",
                   "-vf", ",".join(filters), *self._encode(), str(raw))
            return duration(raw)

        useful = extract(base)
        if accelerated and useful > target:
            # Drop frames where nothing changes (waiting, frozen progress bar)… only if enough is
            # left to fill the line: otherwise speed the whole take up, motion included.
            without_still = extract([*base, "mpdecimate=hi=768:lo=320:frac=0.33",
                                     "setpts=N/FRAME_RATE/TB"])
            if without_still >= target:
                useful = without_still
                info["without_still_frames_s"] = round(useful, 2)
            else:
                useful = extract(base)
        factor = useful / target if target > 0 else 1.0
        warnings = []
        if not accelerated and factor > self.max_speedup:
            warnings.append(f"action {useful:.1f} s for {target:.1f} s of voice: ×{self.max_speedup:g}, "
                            "the picture runs on after the voice")
            factor = self.max_speedup
        factor = max(factor, 1.0)  # never slowed down: the last frame is held instead
        final = max(target, useful / factor)
        ffmpeg("-i", str(raw), "-vf",
               f"setpts=PTS/{factor:.4f},tpad=stop_mode=clone:stop_duration={final:.3f}"
               f"{self.overlay_filter(overlay)}{self.counter_filter(minutes)}",
               "-t", f"{final:.3f}", *self._encode(), str(output))
        raw.unlink(missing_ok=True)
        info.update({"speed": f"×{factor:.2f}", "duration_s": round(final, 2), "warnings": warnings})
        return info

    def clip_segments(self, output: Path, source: Path, start: float, end: float, target: float,
                      segments: list, overlay: str | None, minutes: float | None) -> dict:
        length = end - start

        def absolute(x: float | None, default: float) -> float:
            if x is None:
                return default
            return start + (x if x >= 0 else length + x)

        bounds = [(absolute(a, start), absolute(b, end), f) for a, b, f in segments]
        fixed = sum((b - a) / f for a, b, f in bounds if f)
        free = sum(b - a for a, b, f in bounds if not f)
        rest = max(target - fixed, 0.5)
        pieces = []
        for i, (a, b, f) in enumerate(bounds):
            factor = f or max(1.0, free / rest)
            piece = self.work / f"{output.stem}.seg{i}.mp4"
            ffmpeg("-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(source), "-an", "-vf",
                   f"scale={self.width}:{self.height},fps={self.fps},setpts=PTS/{factor:.4f}",
                   *self._encode(), str(piece))
            pieces.append((piece, round(factor, 2)))
        listing = self.work / f"{output.stem}.segments.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p, _ in pieces), encoding="utf-8")
        raw = self.work / f"{output.stem}.raw.mp4"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(raw))
        final = max(target, duration(raw))
        ffmpeg("-i", str(raw), "-vf", f"tpad=stop_mode=clone:stop_duration={final:.3f}"
               f"{self.overlay_filter(overlay)}{self.counter_filter(minutes)}",
               "-t", f"{final:.3f}", *self._encode(), str(output))
        for piece, _ in pieces:
            piece.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
        listing.unlink(missing_ok=True)
        return {"source_s": round(length, 2), "speed": "/".join(f"×{f}" for _, f in pieces),
                "duration_s": round(final, 2), "warnings": [],
                "segments": [[round(a - start, 2), round(b - start, 2)] for a, b, _ in bounds]}

    def clip_card(self, output: Path, title: str, subtitle: str | None, target: float) -> dict:
        vf = (f"drawtext=fontfile='{self.font_bold}':text='{escape_text(title)}':fontsize=64"
              ":fontcolor=white:x=(w-tw)/2:y=(h-th)/2-40")
        if subtitle:
            vf += (f",drawtext=fontfile='{self.font}':text='{escape_text(subtitle)}':fontsize=34"
                   ":fontcolor=0xc4b5fd:x=(w-tw)/2:y=(h/2)+50")
        ffmpeg("-f", "lavfi", "-i",
               f"color=c=0x0b0b12:s={self.width}x{self.height}:r={self.fps}:d={target:.3f}",
               "-vf", vf, *self._encode(), str(output))
        return {"duration_s": round(target, 2), "warnings": ["placeholder card: replace it"]}

    def clip_slideshow(self, output: Path, images: list[Path], target: float,
                       overlay: str | None) -> dict:
        if not images:
            return self.clip_card(output, "Slideshow", "no images found", target) | {
                "warnings": ["slideshow: no image matches `images`"]}
        each = max(self.slideshow_seconds, target / len(images))
        listing = self.work / "slideshow.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\nduration {each:.3f}\n" for p in images)
                           + f"file '{images[-1].as_posix()}'\n", encoding="utf-8")
        total = each * len(images)
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-vf",
               f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
               f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black,fps={self.fps}"
               f"{self.overlay_filter(overlay)}", "-t", f"{total:.3f}", *self._encode(), str(output))
        return {"duration_s": round(total, 2), "images": len(images), "warnings": []}

    def slide_group(self, group: str) -> tuple[Path, dict[str, float]]:
        """The slides of a group end to end, crossfaded, on the exact length of their scenes: each
        fade spills half its length on both sides of the boundary."""
        if group in self._groups:
            return self._groups[group]
        scenes = [s for s in self.config.scenes if s.mode == "slide" and (s.group or s.id) == group]
        targets = [self.target(s) for s in scenes]
        starts = {s.id: sum(targets[:i]) for i, s in enumerate(scenes)}
        d = self.crossfade if len(scenes) > 1 else 0.0
        inputs, filters = [], []
        for i, scene in enumerate(scenes):
            extra = 0.0 if len(scenes) == 1 else (d / 2 if i in (0, len(scenes) - 1) else d)
            image = self.config.root / "slides" / scene.slide
            if not image.is_file():
                raise SystemExit(f"scene {scene.id}: slide {image} not found (run.py slides)")
            inputs += ["-loop", "1", "-framerate", str(self.fps), "-t", f"{targets[i] + extra:.3f}",
                       "-i", str(image)]
            filters.append(f"[{i}:v]scale={self.width}:{self.height},setsar=1,format=yuv420p[s{i}]")
        last = "s0"
        for i in range(1, len(scenes)):
            filters.append(f"[{last}][s{i}]xfade=transition=fade:duration={d}"
                           f":offset={sum(targets[:i]) - d / 2:.3f}[x{i}]")
            last = f"x{i}"
        output = self.work / f"slides_{group}.mp4"
        ffmpeg(*inputs, "-filter_complex", ";".join(filters), "-map", f"[{last}]",
               "-t", f"{sum(targets):.3f}", *self._encode(), str(output))
        self._groups[group] = (output, starts)
        return self._groups[group]

    def clip_slide(self, output: Path, scene: Scene, target: float) -> dict:
        video, starts = self.slide_group(scene.group or scene.id)
        ffmpeg("-i", str(video), "-ss", f"{starts[scene.id]:.3f}", "-t", f"{target:.3f}",
               *self._encode(), str(output))
        return {"duration_s": round(target, 2), "take": f"slides/{scene.slide}", "warnings": []}

    # -- one scene ------------------------------------------------------------------------------

    def build(self, number: int, scene: Scene) -> dict:
        voice_path, placeholder, voice_s = self.voice(scene)
        target = self.target(scene)
        output = self.work / f"{number:03d}_{scene.id}.mp4"
        entry = {"scene": scene.id, "act": scene.act, "mode": scene.mode,
                 "voice_s": round(voice_s, 2), "target_s": round(target, 2)}
        if scene.mode == "slide":
            info = self.clip_slide(output, scene, target)
        elif scene.mode == "card":
            info = self.clip_card(output, scene.overlay or scene.screen,
                                  scene.screen if scene.overlay else None, target)
        elif scene.mode == "slideshow":
            pattern = str(self.config.path(scene.images or "slides/deck/*.png"))
            info = self.clip_slideshow(output, sorted(Path(p) for p in glob.glob(pattern)),
                                       target, scene.overlay)
        else:
            folder = self.take_folder(scene)
            found = self.segment(folder, scene) if folder else None
            if found is None:
                info = self.clip_card(output, scene.screen or scene.id, "take not found", target)
                info["warnings"] = ["take not found: placeholder card"]
            else:
                video, start, end = found
                if scene.cap_s:
                    end = min(end, start + float(scene.cap_s))
                accelerated = scene.mode == "accelerated"
                minutes = scene.real_minutes or ((end - start) / 60 if accelerated else None)
                minutes = minutes if accelerated else None
                if scene.segments:
                    info = self.clip_segments(output, video, start, end, target, scene.segments,
                                              scene.overlay, minutes)
                else:
                    info = self.clip_video(output, video, start, end, target, accelerated,
                                           scene.overlay, minutes)
                info.update({"take": str(folder.relative_to(self.config.root)),
                             "source_video": str(video.relative_to(self.config.root)),
                             "source_start_s": round(start, 2), "source_end_s": round(end, 2)})
        entry.update(info)
        if voice_path is None and scene.text:
            entry["warnings"] = [*entry.get("warnings", []), "no voice yet (run.py tts or split)"]
        elif placeholder:
            entry["warnings"] = [*entry.get("warnings", []), "placeholder voice"]
        return entry


def mix_and_mux(config: DemoConfig, montage: Montage, clips: list[Path], plan: list[dict],
                output: Path) -> float:
    m = config.section("montage")
    work = montage.work
    audios = []
    # Each scene's voice re-timed on the REAL duration of its clip (rounded to frames).
    for clip, entry in zip(clips, plan, strict=True):
        length = duration(clip)
        audio = clip.with_suffix(".wav")
        path, _ = voice_file(config.voice_dir, entry["scene"])
        if path is not None:
            ffmpeg("-i", str(path), "-af", f"apad=whole_dur={length:.4f},atrim=0:{length:.4f}",
                   "-ar", "48000", "-ac", "1", str(audio))
        else:
            ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{length:.4f}", str(audio))
        audios.append(audio)
    (work / "videos.txt").write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    (work / "audios.txt").write_text("".join(f"file '{a.as_posix()}'\n" for a in audios), encoding="utf-8")
    video_only = work / "video_only.mp4"
    voice_only = work / "voice_only.wav"
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(work / "videos.txt"), "-c", "copy", str(video_only))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(work / "audios.txt"), "-c", "copy", str(voice_only))
    outro = float(m["outro_s"])
    total = duration(video_only) + outro
    video_graph = f"[0:v]tpad=stop_mode=clone:stop_duration={outro:.3f}[v]"
    voice = f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={total:.3f}"
    music = config.path(m["music"]) if m["music"] else None
    if music and music.is_file():
        gain = (loudness(voice_only) - float(m["music_gap_db"])) - loudness(music)
        fade = outro + 1.0
        audio_graph = (
            f"{voice},asplit=2[voice][key];"
            f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},"
            f"asetpts=N/SR/TB,volume={gain:.1f}dB,afade=t=in:d=2[m];"
            "[m][key]sidechaincompress=threshold=0.012:ratio=10:attack=10:release=700,"
            # Fade AFTER the compressor: otherwise its recovery when the voice stops cancels it.
            f"afade=t=out:st={total - fade:.3f}:d={fade:.3f}[md];"
            "[voice][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=disabled[a]"
        )
        audio_inputs = ["-i", str(voice_only), "-stream_loop", "-1", "-i", str(music)]
        print(f"music: {music.name}, gain {gain:+.1f} dB, final fade {fade:.1f} s")
    else:
        if m["music"]:
            print(f"music {m['music']} not found: voice only")
        audio_graph = f"{voice}[a]"
        audio_inputs = ["-i", str(voice_only)]
    # Two passes: with a video input in the same graph, ffmpeg dropped the looped music's fade.
    mix = work / "final_mix.wav"
    ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", *audio_inputs,
           "-filter_complex", audio_graph, "-map", "[a]", "-t", f"{total:.3f}", str(mix))
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(video_only), "-i", str(mix), "-filter_complex", video_graph,
           "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "superfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}",
           "-movflags", "+faststart", str(output))
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("--reuse", action="store_true", help="keep the clips already cut")
    parser.add_argument("--redo", default="", help="with --reuse: scenes to re-cut (comma separated)")
    parser.add_argument("--output", type=Path, help="default: montage.output")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    montage = Montage(config)
    plan_path = config.root / "montage" / "plan.json"
    redo = {s.strip() for s in args.redo.split(",") if s.strip()}
    old_plan = (json.loads(plan_path.read_text(encoding="utf-8"))["scenes"]
                if args.reuse and plan_path.is_file() else None)
    if old_plan is not None and [e["scene"] for e in old_plan] != config.scene_ids:
        print("scenes.json changed since the last montage: cutting everything again")
        old_plan = None

    plan, clips = [], []
    for number, scene in enumerate(config.scenes):
        clip = montage.work / f"{number:03d}_{scene.id}.mp4"
        if old_plan is not None and scene.id not in redo and clip.is_file():
            entry = old_plan[number]
        else:
            entry = montage.build(number, scene)
            print(f"{scene.id:6} {scene.mode:11} voice {entry['voice_s']:5.1f} s → clip "
                  f"{entry['duration_s']:5.1f} s {entry.get('speed', '')}  "
                  f"{'; '.join(entry.get('warnings', []))}", flush=True)
        plan.append(entry)
        clips.append(clip)

    output = args.output or config.path(config.section("montage")["output"])
    total = mix_and_mux(config, montage, clips, plan, output)
    at = 0.0
    for clip, entry in zip(clips, plan, strict=True):
        entry["start_in_video_s"] = round(at, 2)
        at += duration(clip)
    plan_path.write_text(json.dumps({"output": str(output), "total_s": round(total, 2),
                                     "scenes": plan}, indent=1), encoding="utf-8")
    lines = [f"Montage: {total / 60:.1f} min — {output.name}"]
    for e in plan:
        start = e["start_in_video_s"]
        lines.append(f"{int(start // 60)}:{start % 60:04.1f}  {e['scene']:6} {e['mode']:11} voice "
                     f"{e['voice_s']:5.1f} s  clip {e['duration_s']:5.1f} s  {e.get('speed', ''):8} "
                     f"{e.get('take', '')}  {'; '.join(e.get('warnings', []))}")
    (config.root / "montage" / "plan.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"montage: {total / 60:.1f} min → {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
