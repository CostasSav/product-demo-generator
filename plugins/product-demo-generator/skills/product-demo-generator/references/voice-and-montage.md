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

**It is a draft, never the final voice.** A synthetic voice makes a demo sound cheap and costs
it credibility; the user's own voice — or a colleague's — even recorded on a phone, is the single
biggest quality gain of the whole video. Ask for the recording as soon as the scene lines are
final (step 7), ask again before delivery, and flag it in the hand-over if the user chose to keep
the placeholder. The montage prints a warning while any scene still uses it.

## Real voice-over

1. `RUN script` → `voice/voiceover.md`: the script, plus why and how to record (quiet small room,
   phone 15–20 cm from the mouth or a headset, one take in order, a second of silence between
   lines, repeat a sentence after a slip). Send it to the user.
2. `RUN transcribe <file>` (faster-whisper, local; `voice.whisper_model`: medium is accurate,
   small is faster).
3. `RUN split <file>` → `voice/<id>.wav` + `voice/split.txt`. Read the warnings: "few words found"
   (listen to it), "no pause before the next scene" (check the cut). A line not found in the
   recording has no file: the scene keeps its picture without voice — tell the user.
   Cuts go in the **first** silence after a scene's last word, so short opening words ("One,",
   "Two,") stay with their scene even when Whisper mis-times them.
4. Recorded files always win over placeholders.

## Music

Propose **three** tracks and let the user choose by ear.

1. Agree on the tone: default **corporate** (calm, positive, unobtrusive). Others: `upbeat`,
   `calm`, `tech`, `cinematic`, `playful`, or `--keywords "piano,minimal"`.
2. `RUN music --tone <tone>` searches Openverse (Jamendo, Freesound, Wikimedia…), then ccMixter,
   keeps only licences allowing **commercial use and modification** (CC0, CC BY, CC BY-SA — never
   NC or ND), drops tracks with vocals, prefers tracks at least as long as the video (from
   `montage/plan.json`, else estimated) and three different authors, downloads them to
   `montage/music/` and writes `candidates.md` (length, licence, listen link, credit).
3. Fewer than three ready (a catalogue unreachable, a site refusing automatic downloads)?
   Complete with your own web search:
   - where: Pixabay Music (own licence: free commercial use, no credit), Free Music Archive and
     Jamendo (filter CC BY / CC0), Incompetech — Kevin MacLeod (CC BY), the YouTube Audio Library
     (for videos published on YouTube);
   - check on the track's page: the licence allows commercial use and editing, the length covers
     the video (or loops cleanly), no vocals;
   - give the page link: the user listens and downloads it (never work around a site's download
     protection).
4. Present the three: title, author, length, licence, link, and one line on why it fits the tone.
5. The user's choice: `RUN music --pick N`, or `RUN music --use <file> --credit "Music: …"`.
   Either sets `montage.music` and writes the credit to `montage/CREDITS.txt` — CC BY and BY-SA
   require it in the video description or on the end screen: tell the user.

In the montage the music is looped if shorter than the video, sits `music_gap_db` under the
voice's loudness, ducks further while the voice speaks, fades in over 2 s and fades out with the
outro (`outro_s` of last frame, music only).

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
