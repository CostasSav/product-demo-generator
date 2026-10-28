"""The director: starts the app, drives the browser at human speed, films acts and scenes, waits on
the app's real state, saves and restores state, and keeps a journal of every decision.

Two modes:
- `live`: the app runs normally (`app.start_command`); costly scenes (paid API calls, irreversible
  actions, long jobs) are really played, and the state is saved after each step (`save`);
- `retake`: the app runs in its safe mode (`app.safe_command`, nothing paid or irreversible can
  happen); a costly scene is never played — the state that follows it (`restore_after` in
  scenes.json) is restored off camera, and only free actions are filmed.

Rules learned the hard way, enforced here:
- never wait a fixed delay for the app: `wait_until` polls the app's real state;
- a stop (pause, budget, failure) never kills a running job: on exit, the server is only stopped
  once `busy_command` says the app is idle;
- a restore always reloads the page (the front end may cache the old state).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import Locator, Page, async_playwright

from demokit.config import DemoConfig, app_env
from demokit.recorder import OVERLAY_SCRIPT, Recorder
from demokit.state import Snapshots

Mode = Literal["live", "retake"]


class CleanStop(Exception):
    """A step stopped (pause, quota, budget, failure): nothing is relaunched automatically.
    `resume` says how to continue once the cause is fixed."""

    def __init__(self, step: str, cause: str, resume: str) -> None:
        super().__init__(f"{step}: {cause}")
        self.step, self.cause, self.resume = step, cause, resume


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


# --- server -------------------------------------------------------------------------------------


class Server:
    """Starts the app with a shell command and stops its whole process tree."""

    def __init__(self, config: DemoConfig, safe: bool, log_path: Path) -> None:
        app = config.section("app")
        self.config = config
        self.safe = safe
        self.port = int(app["port"])
        self.url = config.app_url
        command = app["safe_command"] if safe and app["safe_command"] else app["start_command"]
        self.command = command.format(port=self.port) if command else ""
        self.cwd = config.path(app["cwd"])
        self.log_path = log_path
        self._process: subprocess.Popen | None = None
        self._log = None

    def start(self) -> None:
        app = self.config.section("app")
        if not self.command:
            log(f"no start command: using the app already running at {self.url}")
            if self.safe and app["safe_log_marker"]:
                log("  ⚠ safe mode cannot be verified for an app started by hand")
            self._wait_ready(None)
            return
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                raise RuntimeError(f"port {self.port} is already in use: stop what runs there, or "
                                   "set another app.port in demo.toml")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("w", encoding="utf-8")
        env = app_env({"PYTHONIOENCODING": "utf-8", **app["env"]})
        extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
                 else {"start_new_session": True})
        self._process = subprocess.Popen(self.command, shell=True, cwd=self.cwd, stdout=self._log,
                                         stderr=subprocess.STDOUT, env=env, **extra)
        self._wait_ready(self._process)
        self._log.flush()
        marker = app["safe_log_marker"]
        if marker:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
            found = re.search(marker, text) is not None
            if found != self.safe:
                self.stop()
                raise RuntimeError(f"unexpected server mode (safe expected: {self.safe}, marker "
                                   f"found: {found}) — see {self.log_path}")
        mode = "SAFE MODE: nothing costly can run" if self.safe else "normal mode: costly steps possible"
        log(f"app ready at {self.url} ({mode})")

    def _wait_ready(self, process: subprocess.Popen | None) -> None:
        app = self.config.section("app")
        deadline = time.monotonic() + float(app["start_timeout_s"])
        ready_url = self.url + "/" + app["ready_path"].lstrip("/")
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                raise RuntimeError(f"the app stopped while starting: {self.log_path}")
            try:
                with urllib.request.urlopen(ready_url, timeout=2):
                    return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError(f"the app does not answer at {ready_url} — see {self.log_path}")

    def stop(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                               capture_output=True)
            else:
                with contextlib.suppress(ProcessLookupError):  # already gone
                    os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
        if self._log is not None:
            self._log.close()
            self._log = None


# --- chapters -----------------------------------------------------------------------------------


@dataclass
class Chapter:
    scene: str
    title: str
    start_s: float
    end_s: float | None = None
    costly: bool = False
    target_s: float | None = None
    notes: list[str] = field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    spent_usd: float | None = None


# --- director -----------------------------------------------------------------------------------


class Director:
    def __init__(self, config: DemoConfig, mode: Mode, output_dir: Path,
                 durations: dict[str, float] | None = None, from_scene: str | None = None,
                 headed: bool | None = None, pace: float | None = None) -> None:
        self.config = config
        self.mode = mode
        self.output_dir = output_dir
        self.durations = durations or {}
        self.from_scene = from_scene
        browser = config.section("browser")
        filming = config.section("filming")
        self.headed = browser["headed"] if headed is None else headed
        self.pace = float(filming["pace"] if pace is None else pace)
        self.typing_ms = float(filming["typing_ms"])
        self.action_pause_s = float(filming["action_pause_s"])
        zoom = float(browser["zoom"])
        self.width, self.height = int(browser["width"]), int(browser["height"])
        # Zoom: the page is laid out on width/zoom CSS pixels and rendered at full resolution, like
        # a browser zoomed in on a 1920×1080 screen — crisp text, no upscaled image.
        self.viewport = {"width": round(self.width / zoom), "height": round(self.height / zoom)}
        self.fps = int(config.section("montage")["fps"])
        self.server = Server(config, safe=(mode == "retake"), log_path=output_dir / "server.log")
        self.snapshots = Snapshots.from_config(config)
        self.journal_path = config.root / "decisions.md"
        self.page: Page = None  # type: ignore[assignment]
        self._playwright = None
        self._browser = None
        self._recorder: Recorder | None = None
        self._chapters: list[Chapter] = []
        self._mouse = (self.viewport["width"] / 2, self.viewport["height"] / 2)

    # -- life cycle -----------------------------------------------------------------------------

    async def __aenter__(self) -> Director:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.server.start()
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=not self.headed)
        context = await self._browser.new_context(
            viewport=self.viewport, device_scale_factor=self.width / self.viewport["width"],
            locale=self.config.section("browser")["locale"], accept_downloads=True,
        )
        await context.add_init_script(OVERLAY_SCRIPT)
        self.page = await context.new_page()
        self.page.set_default_timeout(float(self.config.section("browser")["timeout_s"]) * 1000)
        return self

    async def __aexit__(self, exc_type: type | None, *exc: object) -> None:
        if exc_type is not None:
            await self._let_jobs_finish()
        if self._recorder is not None:
            await self._recorder.stop()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self.server.stop()

    async def _let_jobs_finish(self, max_minutes: float = 30) -> None:
        """After a stop, a job may still run in the app: stopping the server would cut it mid-way
        (and, for a paid job, waste what was spent). Wait until the app is idle."""
        deadline = time.monotonic() + max_minutes * 60
        while time.monotonic() < deadline:
            reason = await asyncio.to_thread(self.snapshots.busy)
            if not reason:
                return
            log(f"    … stopping: waiting for the app to finish ({reason}) before stopping it")
            await asyncio.sleep(10)
        log(f"    ⚠ the app is still busy after {max_minutes:.0f} min: stopping it anyway")

    # -- acts and scenes --------------------------------------------------------------------------

    @asynccontextmanager
    async def act(self, number: int, title: str):
        video = self.output_dir / f"act{number}.mp4"
        self._chapters = []
        self._recorder = Recorder(self.page, video, self.width, self.height, self.fps)
        await self._recorder.start()
        log(f"=== Act {number} — {title}: recording {video.name}")
        try:
            yield
        finally:
            await self.pause(1.5)
            await self._recorder.stop()
            seconds = self._recorder.seconds
            if self._recorder.skipped_frames:
                log(f"    (machine overloaded: {self._recorder.skipped_frames} frames skipped)")
            self._recorder = None
            self._write_chapters(number, title, video, seconds)
            log(f"=== Act {number} done: {seconds:.0f} s of video")

    def _write_chapters(self, number: int, title: str, video: Path, seconds: float) -> None:
        data = {"act": number, "title": title, "video": video.name, "mode": self.mode,
                "duration_s": round(seconds, 2), "scenes": [asdict(c) for c in self._chapters]}
        video.with_suffix(".chapters.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        lines = [f"Act {number} — {title} ({video.name}, {seconds:.1f} s)"]
        for c in self._chapters:
            end = f"{c.end_s:7.1f}" if c.end_s is not None else "      ?"
            target = f" (target {c.target_s:.0f} s)" if c.target_s else ""
            lines.append(f"{c.start_s:7.1f} → {end}  {c.scene:<6} {c.title}"
                         f"{' [costly]' if c.costly else ''}{target}")
            lines.extend(f"{'':22}· {note}" for note in c.notes)
        video.with_suffix(".chapters.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _rank(self, scene_id: str) -> int:
        ids = self.config.scene_ids
        return ids.index(scene_id) if scene_id in ids else -1

    async def should_play(self, scene_id: str) -> bool:
        """Should this scene be played?

        - live, resumed with `--from`: no for the scenes before it;
        - retake: no for a costly scene — the state that follows it (`restore_after`) is restored
          off camera, and the video goes straight on to the next free scene."""
        scene = self.config.scene(scene_id)
        if self.mode == "live":
            return not (self.from_scene and self._rank(scene_id) < self._rank(self.from_scene))
        if not scene.costly:
            return True
        if scene.restore_after:
            if (self.snapshots.saves_dir / scene.restore_after / "state.json").is_file():
                await self.restore(scene.restore_after, note=f"costly scene {scene_id} skipped")
            else:
                # Rehearsal before the live pass: the save does not exist yet.
                log(f"    ⚠ rehearsal: save {scene.restore_after!r} missing — costly scene "
                    f"{scene_id} skipped, the state did not advance")
        return False

    @asynccontextmanager
    async def scene(self, scene_id: str, title: str | None = None):
        known = self.config.scene(scene_id)
        costly = known.costly
        if self.mode == "live" and costly:
            self._check_budget(scene_id)
        recorder = self._recorder
        start = recorder.seconds if recorder else 0.0
        target = self.durations.get(scene_id)
        chapter = Chapter(scene_id, title or known.title or known.screen[:60], round(start, 2),
                          costly=costly, target_s=target, started_at=datetime.now(UTC).isoformat())
        spent_before = self.spent_usd()
        self._chapters.append(chapter)
        log(f"--- {scene_id} {chapter.title}{' [costly]' if costly else ''}")
        began = time.monotonic()
        yield chapter
        # End of scene: hold the picture up to the target duration (voice-over length).
        elapsed = (recorder.seconds - start) if recorder else time.monotonic() - began
        if target is not None:
            if elapsed < target:
                await asyncio.sleep(target - elapsed)
            elif elapsed > target + 0.5:
                chapter.notes.append(f"longer than target: {elapsed:.1f} s for {target:.0f} s")
                log(f"    {scene_id}: {elapsed:.1f} s filmed for a {target:.0f} s target")
        else:
            await self.pause(self.action_pause_s)
        chapter.end_s = round(recorder.seconds if recorder else 0.0, 2)
        chapter.ended_at = datetime.now(UTC).isoformat()
        chapter.spent_usd = round(self.spent_usd() - spent_before, 4)
        if chapter.spent_usd:
            log(f"    $ {scene_id}: {chapter.spent_usd:.2f} $ (total {self.spent_usd():.2f} $)")

    @asynccontextmanager
    async def off_camera(self, reason: str):
        """What happens here is not filmed (long typing, restores, setup)."""
        if self._recorder is not None:
            self._recorder.suspend()
        if self._chapters:
            self._chapters[-1].notes.append(f"cut: {reason}")
        try:
            yield
        finally:
            if self._recorder is not None:
                await self._recorder.resume()

    # -- state ----------------------------------------------------------------------------------

    async def save(self, name: str) -> None:
        """Save the state (live mode only). A save with the same name is replaced: the live pass
        only redoes it when resumed with `--from`."""
        if self.mode != "live":
            return
        folder = await asyncio.to_thread(self.snapshots.save, name, True)
        log(f"    💾 saved {name} → {folder}")

    async def restore(self, name: str, note: str | None = None) -> None:
        async with self.off_camera(note or f"restore {name}"):
            await asyncio.to_thread(self.snapshots.restore, name)
            log(f"    ↺ restored {name}")
            await self.page.reload(wait_until="domcontentloaded")
            await self.page.wait_for_timeout(1500)

    # -- spend ----------------------------------------------------------------------------------

    def spent_usd(self) -> float:
        """Sum of the app's spend log (read only, never written): one JSON object per line."""
        live = self.config.section("live")
        if not live["spend_file"]:
            return 0.0
        path = self.config.path(live["spend_file"])
        if not path.is_file():
            return 0.0
        total = 0.0
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                total += float(json.loads(line).get(live["spend_field"]) or 0.0)
        return total

    def _check_budget(self, scene_id: str) -> None:
        budget = float(self.config.section("live")["budget_usd"] or 0)
        if budget and self.spent_usd() >= budget:
            raise CleanStop(scene_id, f"budget reached ({self.spent_usd():.2f} $ of {budget:.2f} $)",
                            "ask the user before raising live.budget_usd")

    # -- decisions --------------------------------------------------------------------------------

    def decide(self, subject: str, decision: str) -> None:
        """A choice with no exact match in inputs.md, taken by its rules (safest option, anonymised
        when in doubt, consistent with the script): logged in decisions.md and in the chapter."""
        scene = self._chapters[-1].scene if self._chapters else "—"
        if not self.journal_path.is_file():
            self.journal_path.write_text("# Filming decisions — choices without an exact match in "
                                         "inputs.md\n\n", encoding="utf-8")
        with self.journal_path.open("a", encoding="utf-8") as journal:
            journal.write(f"- {datetime.now():%Y-%m-%d %H:%M} · {self.mode} · scene {scene} · "
                          f"{subject} → **{decision}**\n")
        if self._chapters:
            self._chapters[-1].notes.append(f"decision: {subject} → {decision}")
        log(f"    ✎ decision: {subject} → {decision}")

    # -- the app ----------------------------------------------------------------------------------

    async def api_get(self, path: str, retries: int = 8) -> Any:
        """GET on the app (JSON). A transient error never stops filming: stopping the server would
        cut a running job."""
        url = f"{self.server.url}/{path.lstrip('/')}"
        for attempt in range(retries):
            try:
                response = await self.page.context.request.get(url, timeout=60_000)
                break
            except Exception as error:  # local network: try again
                if attempt == retries - 1:
                    raise
                log(f"    (GET {path}: {str(error).splitlines()[0]} — retrying)")
                await asyncio.sleep(5 * (attempt + 1))
        if not response.ok:
            raise RuntimeError(f"GET {path}: {response.status} {await response.text()}")
        return await response.json()

    async def wait_until(self, label: str, check: Callable[[], Awaitable[bool]],
                         timeout_min: float = 60, interval_s: float = 3) -> None:
        """Wait until `check()` returns True. `check` raises `CleanStop` on a pause or a failure.
        No fixed delay: only the app's state decides."""
        log(f"    … waiting: {label}")
        began = time.monotonic()
        while True:
            if await check():
                log(f"    ✓ {label} ({(time.monotonic() - began) / 60:.1f} min)")
                return
            if time.monotonic() - began > timeout_min * 60:
                raise CleanStop(label, f"still running after {timeout_min:.0f} min (nothing was "
                                "stopped in the app)", "check the app, then resume with --from")
            await asyncio.sleep(interval_s)

    # -- gestures ---------------------------------------------------------------------------------

    async def pause(self, seconds: float | None = None) -> None:
        await asyncio.sleep((self.action_pause_s if seconds is None else seconds) * self.pace)

    async def goto(self, path: str, heading: str | re.Pattern | None = None,
                   reload: bool = False, timeout_s: float = 120) -> None:
        """Open a page of the app. `reload` forces a full reload (some single-page apps break
        when leaving a route by a mere URL change). `heading` waits for that heading."""
        await self.page.goto(f"{self.server.url}/{path.lstrip('/')}", wait_until="domcontentloaded")
        if reload:
            await self.page.reload(wait_until="domcontentloaded")
        if heading is not None:
            await self.page.get_by_role("heading", name=heading).first.wait_for(
                timeout=timeout_s * 1000)
        await self.page.wait_for_timeout(800)

    def _scroll_container(self) -> str:
        selector = self.config.section("filming")["scroll_container"]
        return (f"(document.querySelector({json.dumps(selector)}) || document.scrollingElement)"
                if selector else "document.scrollingElement")

    async def scroll(self, pixels: int) -> None:
        await self.page.evaluate(
            f"(p) => {self._scroll_container()}.scrollBy({{top: p, behavior: 'smooth'}})", pixels)
        await asyncio.sleep(0.6 + abs(pixels) / 1200)

    async def scroll_to(self, target: Locator, block: str = "center") -> None:
        await target.wait_for(state="visible")
        await target.evaluate("(e, b) => e.scrollIntoView({behavior: 'smooth', block: b})", block)
        await asyncio.sleep(0.9)

    async def move(self, x: float, y: float) -> None:
        x0, y0 = self._mouse
        distance = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
        steps = max(8, min(45, int(distance / 25)))
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)  # speeds up, then slows down
            await self.page.mouse.move(x0 + (x - x0) * eased, y0 + (y - y0) * eased)
            await asyncio.sleep(0.012)
        self._mouse = (x, y)

    async def hover(self, target: Locator, dwell_s: float = 0.35) -> None:
        await target.wait_for(state="visible")
        box = await target.bounding_box()
        if box is None or box["y"] < 0 or box["y"] + box["height"] > self.viewport["height"]:
            await self.scroll_to(target)
            box = await target.bounding_box()
        assert box is not None
        await self.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await asyncio.sleep(dwell_s * self.pace)

    async def click(self, target: Locator, pause_s: float | None = None) -> None:
        await self.hover(target)
        await target.click()
        await self.pause(pause_s)

    async def type(self, field_: Locator, text: str, paste: bool = False, clear: bool = True) -> None:
        """Human-speed typing; `paste` simulates pasting a prepared text (long inputs)."""
        await self.click(field_, pause_s=0.3)
        if clear:
            await field_.press("Control+a" if sys.platform != "darwin" else "Meta+a")
            await field_.press("Delete")
        if paste:
            await asyncio.sleep(0.4)
            await field_.fill(text)
        else:
            for char in text:
                await self.page.keyboard.type(char)
                delay = self.typing_ms * random.uniform(0.55, 1.45)
                if char in " ,.;:!?":
                    delay *= 1.6
                await asyncio.sleep(delay / 1000)
        await self.pause()

    async def blur(self) -> None:
        """Leave the field (apps that save on blur)."""
        await self.page.keyboard.press("Tab")
        await self.pause(0.8)

    async def confirm(self, read_s: float = 2.2, dialog: str | None = None,
                      button: str | None = None) -> None:
        """A confirmation dialog: let the viewer read it, then confirm."""
        filming = self.config.section("filming")
        window = self.page.locator(dialog or filming["dialog_selector"]).first
        await window.wait_for(state="visible")
        action = window.locator(button or filming["confirm_button"]).first
        await action.wait_for(state="visible")
        deadline = time.monotonic() + 20
        while not await action.is_enabled():
            if time.monotonic() > deadline:
                raise RuntimeError("confirmation dialog: its button never became enabled")
            await asyncio.sleep(0.2)
        await asyncio.sleep(read_s * self.pace)
        await self.click(action, pause_s=0.5)
        await window.wait_for(state="hidden", timeout=120_000)

    async def ghost(self, text: str | None) -> None:
        """A label that follows the cursor (shows what is being dragged); None removes it."""
        await self.page.evaluate("(t) => window.__demoGhost && window.__demoGhost(t)", text)
