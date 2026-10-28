"""Single entry point for every product-demo-generator command (standard library only).

    python run.py setup                 create the tool environment (once per machine)
    python run.py doctor                check ffmpeg, the environment and the browser
    python run.py <command> [args...]   run a command inside the tool environment

Commands: new, film, state, script, tts, transcribe, split, montage, brand, slides, sheet, where.
Run `python run.py <command> --help` for the options of each.

The tool environment (Playwright + Chromium, faster-whisper, Piper TTS) lives in the user's cache
directory, never inside a project: model files and package metadata inside an app repository can
break that app's own tooling. Override its location with PRODUCT_DEMO_GENERATOR_HOME.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PYTHON_VERSION = "3.12"

COMMANDS = {
    "new": "new_project.py",
    "film": "film.py",
    "state": "state_cli.py",
    "script": "render_script.py",
    "tts": "tts_placeholder.py",
    "transcribe": "transcribe.py",
    "split": "split_voice.py",
    "montage": "montage.py",
    "brand": "capture_brand.py",
    "slides": "render_slides.py",
    "sheet": "contact_sheet.py",
    "where": "contact_sheet.py",
}


def home() -> Path:
    if os.environ.get("PRODUCT_DEMO_GENERATOR_HOME"):
        return Path(os.environ["PRODUCT_DEMO_GENERATOR_HOME"]).expanduser()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local / "product-demo-generator"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "product-demo-generator"


def venv_python() -> Path:
    venv = home() / "venv"
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def setup() -> int:
    target = home()
    target.mkdir(parents=True, exist_ok=True)
    python = venv_python()
    uv = shutil.which("uv")
    print(f"tool environment: {target / 'venv'}")
    if not python.is_file():
        if uv:
            subprocess.run([uv, "venv", str(target / "venv"), "--python", PYTHON_VERSION], check=True)
        else:
            subprocess.run([sys.executable, "-m", "venv", str(target / "venv")], check=True)
    requirements = str(SCRIPTS / "requirements.txt")
    if uv:
        subprocess.run([uv, "pip", "install", "--python", str(python), "-r", requirements], check=True)
    else:
        subprocess.run([str(python), "-m", "pip", "install", "-r", requirements], check=True)
    subprocess.run([str(python), "-m", "playwright", "install", "chromium"], check=True)
    return doctor()


def doctor() -> int:
    problems = []
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            problems.append(f"{tool} not found on PATH (Windows: winget install Gyan.FFmpeg; "
                            "macOS: brew install ffmpeg; Linux: apt install ffmpeg)")
    python = venv_python()
    if not python.is_file():
        problems.append(f"tool environment missing: run `python {Path(__file__).name} setup`")
    else:
        check = subprocess.run(
            [str(python), "-c", "import playwright, faster_whisper, piper, num2words; print('ok')"],
            capture_output=True, text=True,
        )
        if check.returncode != 0:
            problems.append("tool environment incomplete: run setup again\n" + check.stderr[-800:])
    if problems:
        print("NOT READY:\n- " + "\n- ".join(problems))
        return 1
    print(f"ready - tool python: {python}")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    command, rest = argv[0], argv[1:]
    if command == "setup":
        return setup()
    if command == "doctor":
        return doctor()
    if command not in COMMANDS:
        print(f"unknown command {command!r}\n{__doc__}")
        return 2
    python = venv_python()
    if not python.is_file():
        print(f"tool environment missing: run `python {Path(__file__).resolve()} setup` first")
        return 1
    if command == "where":
        rest = ["--where", *rest]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(SCRIPTS), "PRODUCT_DEMO_GENERATOR_HOME": str(home()),
           # The app keeps the user's own PYTHONPATH (demokit.config.app_env restores it).
           "PRODUCT_DEMO_GENERATOR_USER_PYTHONPATH": os.environ.get("PYTHONPATH", "")}
    return subprocess.run([str(python), str(SCRIPTS / COMMANDS[command]), *rest], env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
