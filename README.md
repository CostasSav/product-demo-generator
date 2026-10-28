# product-demo-generator

**Turn your web app into a polished, voiced product demo video in an hour.** Automated Playwright
screen recording, free retakes, AI voice-over (local TTS + Whisper), automatic editing and branded
intro/outro slides — a Claude Code plugin that makes demo videos fast and redoable scene by scene.

You describe the demo; Claude writes the scenario and the scene list, films the app with
Playwright (visible cursor, click highlights, human-speed typing, crisp 1080p), plays costly steps
(paid API calls, long jobs) **once**, then re-films everything else for free from saved app
states. A local text-to-speech placeholder times the first cut; your real voice-over is split per
scene with local Whisper; the montage fits every scene to its line, adds branded intro/outro
slides, music and an outro. Then you review: "at 2:56 the voice is cut" → Claude maps the
timestamp to its scene and source, fixes the cause, and re-cuts only that scene.

Everything runs on your machine. Nothing is uploaded.

## Install

In Claude Code:

```
/plugin marketplace add CostasSav/product-demo-generator
/plugin install product-demo-generator@product-demo-generator
```

Then ask Claude for a demo video: on first use it runs the one-time setup itself
(`run.py setup`, in the plugin's `skills/product-demo-generator/scripts/` folder).

It creates a tool environment in your user cache (`%LOCALAPPDATA%\product-demo-generator` on Windows,
`~/.cache/product-demo-generator` elsewhere; override with `PRODUCT_DEMO_GENERATOR_HOME`) with Playwright +
Chromium, faster-whisper and Piper TTS. Your projects are never touched.

**Requirements:** Python 3.10+ to launch the tools (the environment itself uses Python 3.12,
fetched by [uv](https://docs.astral.sh/uv/) when available), [ffmpeg](https://ffmpeg.org/) on the
PATH, network access to PyPI, the Playwright CDN and huggingface.co for the first setup (Whisper
model and Piper voices are downloaded once and cached).

## Use

Open Claude Code in your app's repository and ask for a demo video (or type `/product-demo-generator`).
Claude follows the pipeline in [SKILL.md](plugins/product-demo-generator/skills/product-demo-generator/SKILL.md):

1. understand the app (how it starts, what is costly, where its state lives);
2. scaffold a `demo/` folder (kept out of Git);
3. write the scenario and the scene list — **you approve it**;
4. write and rehearse the acts for free;
5. **you set the budget** for costly steps, if any;
6. the live pass: costly scenes played once, the app's state saved after each step;
7. placeholder voice and free retakes of every act;
8. intro/outro slides in your brand's style;
9. the montage;
10. **you record the voice-over** from the generated script; it is split per scene;
11. **you review**; Claude fixes by timestamp;
12. clean-up: the app is put back as it was, temporary settings reverted.

No costly step? The fast path skips the live pass: a first cut in under an hour.

## The tools

`run.py <command> --demo-dir demo …` — `setup`, `doctor`, `new`, `film` (live / retake), `state`
(save / restore / list), `script`, `tts`, `transcribe`, `split`, `montage`, `brand`, `slides`,
`sheet` (contact sheets), `where` (what is at 5:38?).

Your app plugs in through `demo/demo.toml`: start commands (normal and safe mode), the items that
make its state (folders, files, SQLite, or your own dump/restore commands), a "busy" command and
an optional spend log. See
[app-integration](plugins/product-demo-generator/skills/product-demo-generator/references/app-integration.md).

## Example

[`examples/notes-app`](examples/notes-app) is a tiny app with one "paid" step and a safe mode,
with its complete demo configuration:

```
cd examples/notes-app
python ../../plugins/product-demo-generator/skills/product-demo-generator/scripts/run.py film --demo-dir demo --mode live
python ../../plugins/product-demo-generator/skills/product-demo-generator/scripts/run.py tts --demo-dir demo
python ../../plugins/product-demo-generator/skills/product-demo-generator/scripts/run.py film --demo-dir demo --mode retake --act 1
python ../../plugins/product-demo-generator/skills/product-demo-generator/scripts/run.py film --demo-dir demo --mode retake --act 2
python ../../plugins/product-demo-generator/skills/product-demo-generator/scripts/run.py slides --demo-dir demo
python ../../plugins/product-demo-generator/skills/product-demo-generator/scripts/run.py montage --demo-dir demo
```

## Tests

```
<tool python> -m pytest tests
```

(`<tool python>` is printed by `run.py doctor`.)

## License

MIT
