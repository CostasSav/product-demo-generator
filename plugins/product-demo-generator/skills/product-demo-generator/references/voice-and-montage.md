# Voice-over and montage

## Scene modes (scenes.json)

| mode | picture | fitted to the voice by |
|---|---|---|
| `realtime` | the action as filmed | holding the last frame, or speeding up to ×2 (`max_realtime_speedup`) |
| `accelerated` | a wait (job running) | dropping frozen frames, then speeding up to fill the line exactly; "real time: X" counter |
| `slide` | a still from `slides/` | its length; same `group` → crossfades centred on boundaries |
| `slideshow` | images matching `images` (glob) | spread over the line, `slideshow_seconds` each at least |
| `card` | a plain title card | placeholder only — replace before delivery |

Scene length in the montage = voice + `breath_s` (2 s minimum). Pictures are never slowed down.

Per-scene montage options:
- `take`: `"live"`, `"retake"` or a folder (default: live for costly scenes, else the latest
  retake of the act; falls back to the other if the scene is missing);
- `source_scene`: use another scene's footage (e.g. a final screen held for a lost wait);
- `cap_s`: keep only the first seconds of the take (cut before a crash or a blank screen);
- `segments`: `[[start, end, factor], …]` relative to the scene (negative = from its end, null
  end = to the end, null factor = fill the remaining time); **what is not listed is dropped**:
  `[[11.1, null, null]]` drops an 11 s loading screen; `[[0, -30, null], [-30, null, 10]]`
  shows the last 30 s at ×10 and squeezes the rest;
- `real_minutes`: counter value when the take does not tell the real duration;
- `overlay`: a caption at the bottom (key point of the scene, short).

## Writing the lines

One line per scene, written for the ear: short sentences, the benefit before the feature, numbers
spelled the way they are said. Estimate 150 words per minute. A scene without voice still needs
an entry (empty `text`).

## Placeholder voice (Piper)

`RUN tts` writes `voice/placeholder/<id>.wav` for every line (voice: `voice.tts_voice`, any Piper
voice — en_US-lessac-medium, en_GB-alan-medium, fr_FR-siwis-medium, de_DE-thorsten-medium…). It
times the retakes and gives a watchable first cut before anyone records. `--full` writes one file
with every line, to test the split.

## Real voice-over

1. `RUN script` → `voice/voiceover.md`: the user records it in one take, in order, about one
   second of silence between lines, never reading scene numbers.
2. `RUN transcribe <file>` (faster-whisper, local; `voice.whisper_model`: medium is accurate,
   small is faster).
3. `RUN split <file>` → `voice/<id>.wav` + `voice/split.txt`. Read the warnings: "few words found"
   (listen to it), "no pause before the next scene" (check the cut). A line not found in the
   recording has no file: the scene keeps its picture without voice — tell the user.
   Cuts go in the **first** silence after a scene's last word, so short opening words ("One,",
   "Two,") stay with their scene even when Whisper mis-times them.
4. Recorded files always win over placeholders.

## Music and outro

`montage.music`: any audio file, looped. It sits `music_gap_db` under the voice's loudness,
ducks further while the voice speaks, fades in over 2 s and fades out with the outro
(`outro_s` of last frame, music only). Ask the user for the track (licensed for this use).

## Review loop

- `montage/plan.txt`: per scene, its start in the video, take, speed and warnings.
- `RUN where 5:38` → scene, offset, take and source seconds, plus the command to look at the
  source frames.
- `RUN sheet <video> --at 1:28,1:30,1:33` or `--from 12 --to 24 --every 1` → one image to read.

Typical remarks and fixes:

| Remark | Cause | Fix |
|---|---|---|
| "a loading page from 1:28 to 1:33" | the take starts before the page is ready | `segments: [[<seconds of loading>, null, null]]` |
| "too fast at the end of the generation" | uniform speed-up of a long wait | `segments` with a slower last part |
| "the voice is cut mid-sentence ("One…")" | split cut after a short word | re-run `split` (first-silence rule), `--reuse --redo` the scenes around it |
| "black screen at the end of the scene" | the take shows a crash after the action | `cap_s` before it |
| "we don't see the step-by-step progress" | the live take was lost | reconstruct (filming.md), point `take` to it |
| "the picture runs on after the voice" | action much longer than the line | trim the action in a retake, or `--pace 0.7` |

After a fix: `RUN montage --reuse --redo <ids>` (all scenes whose voice or take changed), then a
sheet at the same timestamp before saying it is fixed.
