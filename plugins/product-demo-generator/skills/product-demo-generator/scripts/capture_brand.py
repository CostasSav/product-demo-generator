"""Capture a brand's visual identity from its website, for intro and outro slides in its style.

    run.py brand --demo-dir demo https://example.com [--pages 5]

Writes to `slides/brand/`:
- `screen<N>.png`: the site, one screenful at a time (look at them: layout, rhythm, imagery);
- `styles.json`: computed fonts and sizes of body / headings / buttons, the most used colors,
  the web fonts loaded, the first headings;
- `logo*` : the header's logo (image or inline SVG) when one is found;
- `tokens.css`: a first guess of the CSS variables used by `slides/slides.html` (background, ink,
  muted text, accent, heading and body fonts) — check it against the screenshots.

Only use a brand you are entitled to use (your company, your client with their consent).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from demokit import config as config_module
from playwright.async_api import async_playwright

CONSENT = ["Accept all", "Accept", "Allow all", "I agree", "OK", "Tout accepter", "Accepter",
           "J'accepte", "Alle akzeptieren", "Aceptar", "Accetta"]

STYLES_JS = r"""() => {
  const pick = (sel) => { const e = document.querySelector(sel); if (!e) return null;
    const c = getComputedStyle(e);
    return {font: c.fontFamily, size: c.fontSize, weight: c.fontWeight, color: c.color,
            background: c.backgroundColor, letterSpacing: c.letterSpacing,
            transform: c.textTransform, style: c.fontStyle}; };
  const out = {};
  for (const s of ["html", "body", "h1", "h2", "h3", "p", "a", "button", "header", "footer", "em", "i"])
    out[s] = pick(s);
  const colors = {};
  for (const e of document.querySelectorAll("*")) { const c = getComputedStyle(e);
    for (const v of [c.color, c.backgroundColor, c.borderTopColor])
      if (v && !v.endsWith(", 0)") && v !== "rgba(0, 0, 0, 0)") colors[v] = (colors[v] || 0) + 1; }
  out.colors = Object.entries(colors).sort((a, b) => b[1] - a[1]).slice(0, 30);
  out.fonts = [...new Set([...document.fonts].filter(f => f.status === "loaded")
    .map(f => f.family.replace(/["']/g, "")))];
  out.headings = [...document.querySelectorAll("h1, h2, h3")].slice(0, 15)
    .map(e => e.tagName + ": " + e.innerText.replace(/\s+/g, " ").slice(0, 100));
  const logo = document.querySelector(
    "header a img, header img, header svg, [class*=logo] img, [class*=logo] svg, img[alt*=logo i]");
  out.logo = logo ? (logo.tagName.toLowerCase() === "svg" ? {svg: logo.outerHTML}
                                                           : {src: logo.currentSrc || logo.src}) : null;
  return out;
}"""


def clean_font(family: str) -> str:
    first = family.split(",")[0].strip().strip("\"'")
    match = re.fullmatch(r"__(.+?)_[0-9a-f]{4,}", first)  # Next.js font names
    return (match.group(1) if match else first).replace("_Fallback", "")


def rgb(value: str) -> tuple[int, int, int] | None:
    numbers = re.findall(r"[\d.]+", value)
    if len(numbers) >= 4 and float(numbers[3]) == 0:
        return None  # fully transparent: not a colour of the page
    if value.startswith("rgb") and len(numbers) >= 3:
        return tuple(int(float(n)) for n in numbers[:3])  # type: ignore[return-value]
    return None


def hex_of(color: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def saturation(color: tuple[int, int, int]) -> float:
    high, low = max(color), min(color)
    return 0.0 if high == 0 else (high - low) / high


def tokens(styles: dict) -> str:
    body = styles.get("body") or {}
    page = styles.get("html") or {}
    background = rgb(body.get("background", "")) or rgb(page.get("background", "")) or (255, 255, 255)
    ink = rgb(body.get("color", "")) or (17, 17, 17)
    weighted = Counter()
    for value, count in styles.get("colors", []):
        color = rgb(value)
        if color and saturation(color) > 0.45 and max(color) > 40:
            weighted[color] += count
    accent = weighted.most_common(1)[0][0] if weighted else (79, 70, 229)
    second = next((c for c, _ in weighted.most_common(6)
                   if sum(abs(a - b) for a, b in zip(c, accent, strict=True)) > 120), accent)
    heading = clean_font((styles.get("h1") or styles.get("h2") or body).get("font", "Georgia"))
    text = clean_font(body.get("font", "system-ui"))
    return f""":root {{
  /* First guess from the site's computed styles — check it against the screenshots. */
  --bg: {hex_of(background)};
  --ink: {hex_of(ink)};
  --muted: color-mix(in srgb, var(--ink) 55%, var(--bg));
  --accent: {hex_of(accent)};
  --accent-2: {hex_of(second)};
  --font-heading: "{heading}", Georgia, serif;
  --font-body: "{text}", system-ui, sans-serif;
}}
"""


async def capture(url: str, output: Path, pages: int) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(2000)
        for label in CONSENT:
            try:
                await page.get_by_role("button", name=label, exact=True).first.click(timeout=800)
                await page.wait_for_timeout(800)
                break
            except Exception:  # no such consent button on this site
                continue
        height = await page.evaluate("document.body.scrollHeight")
        for i, y in enumerate(range(0, min(height, 1080 * pages), 1080)):
            await page.evaluate(f"window.scrollTo(0, {y})")
            await page.wait_for_timeout(900)
            await page.screenshot(path=output / f"screen{i}.png")
        await page.evaluate("window.scrollTo(0, 0)")
        styles = await page.evaluate(STYLES_JS)
        await browser.close()
    logo = styles.pop("logo", None)
    if logo and logo.get("svg"):
        (output / "logo.svg").write_text(logo["svg"], encoding="utf-8")
        styles["logo_file"] = "logo.svg"
    elif logo and logo.get("src"):
        source = urllib.parse.urljoin(url, logo["src"])
        suffix = Path(urllib.parse.urlparse(source).path).suffix or ".png"
        try:
            request = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                (output / f"logo{suffix}").write_bytes(response.read())
            styles["logo_file"] = f"logo{suffix}"
        except OSError as error:
            styles["logo_error"] = f"{source}: {error}"
    (output / "styles.json").write_text(json.dumps(styles, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    (output / "tokens.css").write_text(tokens(styles), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("url")
    parser.add_argument("--pages", type=int, default=5, help="screenfuls to capture")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    output = config.root / "slides" / "brand"
    output.mkdir(parents=True, exist_ok=True)
    asyncio.run(capture(args.url, output, args.pages))
    print(f"brand captured in {output}: screenshots, styles.json, tokens.css"
          f"{', logo' if any(output.glob('logo*')) else ' (no logo found)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
