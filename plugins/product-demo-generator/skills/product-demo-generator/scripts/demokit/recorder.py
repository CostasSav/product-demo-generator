"""Video recorder and page overlay (visible cursor, click ripple, highlighted target).

Not Playwright's built-in video (VP8 around 1 Mbit/s: text blurs when scrolling). Chromium's frames
come through the DevTools protocol (`Page.startScreencast`, high-quality JPEG at real pixels) and
are pushed to ffmpeg at a fixed frame rate, encoded in H.264. Chromium only sends a frame when the
page changes: in between, the last frame is repeated, so the video follows the wall clock — which
is what makes scene durations match the voice-over.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import shutil
import time
from pathlib import Path

from playwright.async_api import CDPSession, Page

# Injected before any page script (and again on every navigation): a visible cursor, a ripple on
# click and a halo on the clicked element. Modal `<dialog>`s live in the top layer, above any
# z-index: the cursor is moved inside the open dialog while there is one.
OVERLAY_SCRIPT = r"""
(() => {
  if (window.__demoOverlay) return;
  window.__demoOverlay = true;
  const ACCENT = "rgba(109, 40, 217, .9)";
  const CSS = `
    #demo-cursor { position: fixed; left: 0; top: 0; width: 30px; height: 30px;
      z-index: 2147483647; pointer-events: none; will-change: transform; }
    #demo-cursor svg { filter: drop-shadow(0 2px 3px rgba(0,0,0,.45)); }
    #demo-cursor.demo-down svg { transform: scale(.86); transform-origin: 3px 2px; }
    .demo-ripple { position: fixed; z-index: 2147483646; pointer-events: none; border-radius: 50%;
      border: 3px solid ${ACCENT}; width: 14px; height: 14px; margin: -7px 0 0 -7px;
      animation: demo-ripple .65s ease-out forwards; }
    @keyframes demo-ripple { to { width: 64px; height: 64px; margin: -32px 0 0 -32px; opacity: 0; } }
    .demo-target { outline: 3px solid ${ACCENT} !important; outline-offset: 3px !important;
      box-shadow: 0 0 0 9px rgba(109, 40, 217, .16) !important; border-radius: 6px; }
    #demo-ghost { position: fixed; z-index: 2147483645; pointer-events: none; display: flex;
      gap: 6px; align-items: center; padding: 8px 12px; border-radius: 10px; font: 600 14px system-ui;
      background: rgba(255,255,255,.96); color: #312e81; border: 1px solid rgba(109,40,217,.5);
      box-shadow: 0 8px 24px rgba(0,0,0,.18); transform: translate(18px, 18px); }
  `;
  const SVG = `<svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
    <path d="M3 2 L3 24 L9 18.5 L13 27 L17 25.2 L13.2 16.8 L21.5 16.8 Z"
      fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  let x = -100, y = -100, cursor = null, ghost = null;

  function host() { return document.querySelector("dialog[open]") || document.body; }
  function place() {
    if (!document.body) return;
    if (!cursor) {
      const style = document.createElement("style");
      style.textContent = CSS;
      document.head.appendChild(style);
      cursor = document.createElement("div");
      cursor.id = "demo-cursor";
      cursor.innerHTML = SVG;
    }
    const h = host();
    if (cursor.parentNode !== h) h.appendChild(cursor);
    cursor.style.transform = `translate(${x - 3}px, ${y - 2}px)`;
    if (ghost) {
      if (ghost.parentNode !== h) h.appendChild(ghost);
      ghost.style.left = x + "px";
      ghost.style.top = y + "px";
    }
  }
  function targetOf(element) {
    return element && element.closest
      ? element.closest("button, a, input, textarea, select, label, summary, " +
                        "[role=button], [role=checkbox], [role=tab], [role=option]")
      : null;
  }
  addEventListener("mousemove", (e) => { x = e.clientX; y = e.clientY; place(); }, true);
  addEventListener("mousedown", (e) => {
    x = e.clientX; y = e.clientY; place();
    cursor && cursor.classList.add("demo-down");
    const ripple = document.createElement("div");
    ripple.className = "demo-ripple";
    ripple.style.left = x + "px";
    ripple.style.top = y + "px";
    host().appendChild(ripple);
    setTimeout(() => ripple.remove(), 700);
    const target = targetOf(e.target);
    if (target) {
      target.classList.add("demo-target");
      setTimeout(() => target.classList.remove("demo-target"), 1100);
    }
  }, true);
  addEventListener("mouseup", () => cursor && cursor.classList.remove("demo-down"), true);
  new MutationObserver(place).observe(document, { childList: true, subtree: true, attributes: true,
    attributeFilter: ["open"] });
  window.__demoGhost = (text) => {
    if (text == null) { ghost && ghost.remove(); ghost = null; return; }
    ghost = document.createElement("div");
    ghost.id = "demo-ghost";
    ghost.textContent = text;
    place();
  };
  window.__demoCursor = (cx, cy) => { x = cx; y = cy; place(); };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", place);
  else place();
})();
"""


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError("ffmpeg not found on PATH (run `run.py doctor`)")
    return path


class Recorder:
    """One MP4 per act. `suspend()` / `resume()` cut the picture without closing the file
    (off-camera restore or typing): the video only keeps what is filmed, and chapter timestamps
    follow *video* time."""

    def __init__(self, page: Page, output: Path, width: int = 1920, height: int = 1080,
                 fps: int = 30, jpeg_quality: int = 92, crf: int = 16) -> None:
        self.page = page
        self.output = output
        self.width, self.height, self.fps = width, height, fps
        self.jpeg_quality = jpeg_quality
        self.crf = crf
        self._cdp: CDPSession | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._last: bytes | None = None
        self._writer: asyncio.Task | None = None
        self._active = False
        self._acks: set[asyncio.Future] = set()
        self._frames = 0
        self.skipped_frames = 0

    @property
    def seconds(self) -> float:
        """Duration already written to the video."""
        return self._frames / self.fps

    async def start(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self._process = await asyncio.create_subprocess_exec(
            ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "image2pipe", "-framerate", str(self.fps), "-c:v", "mjpeg", "-i", "-",
            # limited range, like every other clip of the montage (JPEG frames are full range)
            "-vf", f"scale={self.width}:{self.height}:flags=lanczos:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "superfast", "-crf", str(self.crf),
            "-tune", "stillimage", "-r", str(self.fps), "-movflags", "+faststart",
            str(self.output),
            stdin=asyncio.subprocess.PIPE,
        )
        self._cdp = await self.page.context.new_cdp_session(self.page)
        self._cdp.on("Page.screencastFrame", self._on_frame)
        await self._cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": self.jpeg_quality, "maxWidth": self.width,
             "maxHeight": self.height, "everyNthFrame": 1},
        )
        # First frame: a screenshot, in case the page does not move right away.
        self._last = await self.page.screenshot(type="jpeg", quality=self.jpeg_quality)
        self._active = True
        self._writer = asyncio.create_task(self._write())

    def _on_frame(self, event: dict) -> None:
        self._last = base64.b64decode(event["data"])
        if self._cdp is not None:
            ack = asyncio.ensure_future(
                self._cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
            )
            self._acks.add(ack)  # keep a reference until it is sent
            ack.add_done_callback(self._acks.discard)

    async def _write(self) -> None:
        """One frame every 1/fps s, waiting for ffmpeg to absorb the previous one.

        On a loaded machine ffmpeg can fall behind. We catch up by one second at most, then
        resync the clock — skipped frames rather than a buffer growing without bound (which ends
        in "buffer too large" and a video file without its index)."""
        assert self._process is not None and self._process.stdin is not None
        step = 1 / self.fps
        next_at = time.monotonic()
        while True:
            now = time.monotonic()
            if now < next_at:
                await asyncio.sleep(next_at - now)
            elif now - next_at > 1.0:
                self.skipped_frames += int((now - next_at) / step)
                next_at = now
            if self._active and self._last is not None:
                self._process.stdin.write(self._last)
                self._frames += 1
                await self._process.stdin.drain()
            next_at += step

    def suspend(self) -> None:
        self._active = False

    async def resume(self) -> None:
        # Start again from a fresh frame: the last one received may predate the cut.
        self._last = await self.page.screenshot(type="jpeg", quality=self.jpeg_quality)
        self._active = True

    async def stop(self) -> None:
        self._active = False
        if self._writer is not None:
            self._writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer
        if self._cdp is not None:
            try:
                await self._cdp.send("Page.stopScreencast")
                await self._cdp.detach()
            except Exception:  # page already closed: nothing to stop
                pass
        if self._process is not None and self._process.stdin is not None:
            self._process.stdin.close()
            await self._process.wait()
