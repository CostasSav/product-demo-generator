"""demokit — film a web app with Playwright, cut it to a voice-over, and assemble a clean demo video.

Modules:
- `config`   — `demo.toml` and `scenes.json` of a project's demo folder;
- `state`    — save / restore the app's state at named points (with a safety net);
- `recorder` — CDP screencast → ffmpeg H.264, plus the cursor / click overlay;
- `director` — server, browser, acts and scenes, human-speed gestures, waits on app state;
- `media`    — ffmpeg / ffprobe helpers shared by the voice and montage commands.
"""

import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
