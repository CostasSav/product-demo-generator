---
name: product-demo-generator
description: >-
  Turn a web app into a clean, voiced product demo video, fast - scenario and scene list,
  automated filming with Playwright (visible cursor, human-speed typing, crisp 1080p), one live
  pass for costly steps then free retakes from saved app states, placeholder voice-over (local
  TTS), real voice-over split per scene (local Whisper), automatic montage fitted to the voice,
  branded intro and outro slides, and a timestamp-driven review loop. Use when the user wants to
  film, record or produce a demo, walkthrough, screencast or product video of an app they run
  locally.
argument-hint: "[path of the app's repository]"
---

# App → clean demo video

You produce a demo video of a web app the user runs locally, end to end, the way a careful
human editor would — but scripted, so every scene can be redone in minutes.

`RUN` below means: `python <this skill's folder>/scripts/run.py` — installed as a plugin, that is
`python "${CLAUDE_PLUGIN_ROOT}/skills/product-demo-generator/scripts/run.py"`. Every command takes
`--demo-dir <folder>` (default `demo`, relative to the current directory) and `--help`.

Read the reference for a phase when you reach it, not before:
[app-integration](references/app-integration.md) ·
[filming](references/filming.md) ·
[voice-and-montage](references/voice-and-montage.md) ·
[slides](references/slides.md) ·
[troubleshooting](references/troubleshooting.md)

## The pipeline

There are four **gates** where the user decides. Never pass a gate without their answer.

0. **Setup, once per machine.** `RUN doctor`; if not ready, `RUN setup` (Playwright + Chromium,
   faster-whisper, Piper TTS, in the user's cache — never inside the project) and install
   ffmpeg if missing. Needs network access to PyPI, the Playwright CDN and huggingface.co.

1. **Understand the app.** Read its README and code to answer, in writing: how it starts (command,
   port), which actions are *costly* (paid API calls, emails or messages sent, irreversible
   writes, jobs longer than a minute), whether it has a **safe mode** that refuses them, where its
   state lives (folders, SQLite, a server database), how to tell it is busy, and whether it logs
   what it spends. → [app-integration](references/app-integration.md). If a costly action has no
   safe mode, propose the smallest way to add one and ask before changing the app.

2. **Scaffold.** `RUN new --demo-dir demo --gitignore` creates `demo.toml`, `scenes.json`,
   `acts.py`, `scenario.md`, `inputs.md`, `slides/slides.html`. The folder will hold saves of the
   app's data and recordings: it must stay out of Git (the flag edits `.gitignore`; say so).
   Fill `demo.toml` from step 1.

3. **Script — GATE 1.** Write `scenario.md` (audience, promise, length, acts), `inputs.md` (every
   text typed, file uploaded and option picked — fictional or anonymised data only) and
   `scenes.json` (one entry per voice line: id, act, mode, screen, text; `costly` +
   `restore_after` for costly scenes). Show the user the scene table — which scenes are costly
   (with time and cost estimates) and which are replayable for free — and **wait for approval**.

4. **Acts and rehearsal.** Write `acts.py` (template rules at its top: one `t.scene()` per scene,
   `t.should_play()` before costly scenes, `t.save()` after every state change, `t.wait_until()`
   on the app's real state, never a fixed sleep). Rehearse each act for free:
   `RUN state save 00-start`, then `RUN film --mode retake --act N` (costly scenes are skipped
   with a warning). Fix selectors until every act runs clean. Check frames with `RUN sheet`.
   → [filming](references/filming.md)

5. **Budget — GATE 2.** If any scene costs money, get an explicit amount from the user. Set
   `live.budget_usd` (and `live.spend_file` if the app logs its spend). If the app has its own
   spending caps that must be raised for the shoot, raise them **without committing** and note
   it for clean-up.

6. **Live pass.** `RUN film --mode live` (run it in the background and follow its log). It saves
   `00-start`, plays everything, saves after each step. Stops are clean and never relaunch
   anything by themselves:
   - provider rate limit / subscription window → wait for it to reopen, then resume with
     `--from <scene> --restore <save before it>`;
   - budget reached, credit exhausted, quota → **stop and tell the user**;
   - a scene fails → one new attempt after restoring the save before it, then stop and report.
   Log every choice not settled by `inputs.md` with `t.decide()` (safest option, anonymised when
   in doubt). Write a short report: scenes filmed, spend, incidents, saves, app bugs seen.

7. **Placeholder voice and retakes.** `RUN script` (recording script `voice/voiceover.md`),
   `RUN tts` (placeholder lines with Piper), then `RUN film --mode retake --act N` for each act:
   every scene now lasts as long as its line. Retakes never spend anything.

8. **Brand slides.** Ask whose brand frames the video (the user's company, usually) and its site.
   `RUN brand <url>`, adapt `slides/slides.html` (tokens, fonts, one slide per intro/outro line),
   `RUN slides`, look at every PNG. → [slides](references/slides.md)

9. **Montage.** `RUN montage`, then look at it: `RUN sheet demo/montage/demo.mp4 --at …` on each
   scene boundary. Fix what you see before showing it (`montage/plan.txt` lists every scene, its
   take, speed and warnings). → [voice-and-montage](references/voice-and-montage.md)

10. **Real voice — GATE 3.** The user records `voice/voiceover.md` in one take and drops the file
   in `voice/`. `RUN transcribe <file>`, `RUN split <file>`, read `voice/split.txt` (warnings,
   missing lines), then `RUN montage`. Optionally re-run the retakes so each scene matches the
   real line exactly, then the montage again.

11. **Review loop — GATE 4.** The user watches and says "at 2:56 …". For each remark:
   `RUN where 2:56` (scene, take, source seconds) → look (`RUN sheet <source> --from --to`) →
   fix the cause (scene options, voice split, a retake) → `RUN montage --reuse --redo <ids>` →
   look again at the same timestamp before saying it is fixed.

12. **Clean-up.** Restore the app's real state if the demo changed it, revert temporary settings
   (caps raised in step 5), list app bugs found while filming and propose a separate commit for
   each (ask first), and hand over: video path, length, spend, what is left to the user.

**Fast path** (no costly scene): skip gate 2 and the live pass; `RUN state save 00-start`,
retakes only, placeholder voice, montage — a first cut in under an hour.

## Rules

- Never show real client or personal data unless the user explicitly provides it for the demo.
- Never play a costly scene outside the live pass, and never relaunch a paid step on your own
  after a stop (only a rate-limit wait-and-resume is automatic).
- Never wait on a fixed delay for the app; never stop the server while a job runs (the director
  waits for `busy_command`).
- Every restore first saves the current state (`_before-restore-…`): use it to undo a mistake.
  A script that restores to run something must give back the state it *started from*.
- Do not change the app's code to make filming easier without asking; app bugs seen while
  filming are reported with a proposed fix.
- Look at frames (`RUN sheet`) before claiming a scene or a fix is right.
- Nothing is uploaded or published: the video stays on the user's machine.
