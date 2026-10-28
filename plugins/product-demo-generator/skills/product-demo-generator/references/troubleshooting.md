# Troubleshooting — symptoms seen in real shoots, and their fixes

| Symptom | Cause | Fix |
|---|---|---|
| The app crashes on start with "SRE module mismatch" (or another Python crashes) | it inherited the tool venv's `PYTHONHOME` | commands run through `app_env()`; if you start processes yourself, strip `PYTHONHOME` / `UV_INTERNAL__PYTHONHOME` |
| "port already in use" | a previous run's server still alive | stop it (find the PID on the port); the director never reuses a running server |
| Recorder: "buffer too large", a video without index (moov atom missing) | ffmpeg fell behind on a loaded machine | the recorder caps catch-up at 1 s and skips frames; keep heavy jobs out of filmed scenes when possible; an unreadable file is lost — reconstruct the scene |
| A blank page after leaving a route | the single-page app breaks on URL-only navigation | `t.goto(path, reload=True)` |
| The screen stops updating during a long job | the front end only streams while it thinks something runs | wait on the app's state, then reload; check what "running" means for the app |
| A restore is refused: "a file is probably open" | a document is open in another program (Office, viewer) | close it; nothing was changed |
| A restore is refused: "the app is busy" | a job is running | wait; never `--force` while the server runs |
| A script restored a fixed save at the end and lost later work | it should give back the state it started from | restore the `_before-restore-…` save taken when it started |
| Whisper cut a short word into the previous scene | Whisper mis-times "One" / numbers | the split cuts in the first silence after a scene's last word; re-run `split` |
| The voice drifts behind the picture over the video | clip durations rounded to frames | the montage re-times each scene's audio on its real clip length — do not concatenate audio yourself |
| The music fade-out is missing | fade before the ducking compressor, or mixed with the video in one graph | the montage fades after the compressor, in a separate audio pass |
| Downloads from huggingface.co fail (Whisper model, Piper voice) | proxy / firewall / sandbox | retry with network access; models are cached once (`~/.cache/huggingface`, `<tool home>/voices`); `transcribe` uses the cached model first |
| Package metadata or model files inside the project broke the app's own scanners | ML tooling installed in the repo | the tool environment lives in the user cache (`PRODUCT_DEMO_GENERATOR_HOME`), never in the project |
| Windows: `PermissionError` renaming a fresh save | antivirus / indexer lock | renames are retried; if it persists, exclude the saves folder from indexing |
| Windows: a path like `#/route` mangled in Git Bash | MSYS path conversion | prefix with `MSYS_NO_PATHCONV=1` |
| Accents garbled in logs | console code page | the tools force UTF-8 output; set `PYTHONUTF8=1` for your own scripts |
