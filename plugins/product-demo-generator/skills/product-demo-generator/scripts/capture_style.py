"""Capture the visual style used by the intro and outro slides.

    run.py style --demo-dir demo [--pages /,/items/1] [--normal]   # default: the app itself
    run.py style --demo-dir demo --tokens design/tokens.json   # the user's design system
    run.py style --demo-dir demo --url https://brand.example   # a brand's website

By default the slides look like **the app being demoed**: the app is started (safe mode, as for
retakes — or the running one if demo.toml has no start command), its pages are read for colours,
fonts and corner radius, and screenshotted so the slides can show the real product. A design
system file (CSS custom properties, or JSON tokens: W3C / Style Dictionary / Tokens Studio /
shadcn-style HSL triplets) or a brand website can be used instead, when the user provides one.

Writes to `slides/style/`:
- `tokens.css`: the variables `slides/slides.html` uses (`--bg --surface --ink --muted --accent
  --accent-ink --radius --font-heading --font-body`), then every variable found in a tokens file;
- `fonts.css`: `@font-face` rules for the web fonts the app serves itself (files in `fonts/`);
- `screen-<N>.png`: screenshots (the app's pages, or the site);
- `styles.json`: what was measured, `logo.*` when a logo is found, `source.txt`.

Check `tokens.css` against the screenshots: it is a measured first guess, not a verdict.
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
from demokit.director import Server
from playwright.async_api import async_playwright

DEFAULTS = {"--bg": "#FFFFFF", "--surface": "#F5F6F8", "--ink": "#14161A", "--muted": "#5F6570",
            "--accent": "#2563EB", "--accent-ink": "#FFFFFF", "--radius": "12px",
            "--font-heading": "system-ui, sans-serif", "--font-body": "system-ui, sans-serif"}
CONSENT = ["Accept all", "Accept", "Allow all", "I agree", "OK", "Tout accepter", "Accepter",
           "J'accepte", "Alle akzeptieren", "Aceptar", "Accetta"]

MEASURE_JS = r"""() => {
  const css = (e) => getComputedStyle(e);
  const pick = (sel) => { const e = document.querySelector(sel); if (!e) return null; const c = css(e);
    return {font: c.fontFamily, size: c.fontSize, weight: c.fontWeight, color: c.color,
            background: c.backgroundColor, radius: c.borderTopLeftRadius}; };
  const out = {};
  for (const s of ["html", "body", "h1", "h2", "h3", "p", "header", "nav", "main"]) out[s] = pick(s);
  const backgrounds = {}, colors = {};
  for (const e of document.querySelectorAll("*")) { const c = css(e);
    const area = e.getBoundingClientRect().width * e.getBoundingClientRect().height;
    if (c.backgroundColor && !c.backgroundColor.endsWith(", 0)"))
      backgrounds[c.backgroundColor] = (backgrounds[c.backgroundColor] || 0) + Math.min(area, 2e5);
    colors[c.color] = (colors[c.color] || 0) + 1; }
  out.backgrounds = Object.entries(backgrounds).sort((a, b) => b[1] - a[1]).slice(0, 20);
  out.colors = Object.entries(colors).sort((a, b) => b[1] - a[1]).slice(0, 20);
  out.buttons = [...document.querySelectorAll(
      "button, [role=button], input[type=submit], a[class*=btn], a[class*=button]")]
    .slice(0, 40).map(e => { const c = css(e);
      return {background: c.backgroundColor, color: c.color, radius: c.borderTopLeftRadius,
              text: (e.innerText || e.value || "").trim().slice(0, 30)}; });
  out.cards = [...document.querySelectorAll("[class*=card], section, article, dialog, form")]
    .slice(0, 30).map(e => { const c = css(e);
      return {background: c.backgroundColor, radius: c.borderTopLeftRadius, shadow: c.boxShadow}; });
  out.fonts = [...new Set([...document.fonts].filter(f => f.status === "loaded")
    .map(f => f.family.replace(/["']/g, "")))];
  out.fontFaces = [];
  for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch { continue; }
    for (const r of rules) if (r instanceof CSSFontFaceRule) {
      const urls = [...r.style.getPropertyValue("src").matchAll(/url\(["']?([^"')]+)["']?\)/g)]
        .map(m => new URL(m[1], sheet.href || location.href).href);
      out.fontFaces.push({family: r.style.getPropertyValue("font-family").replace(/["']/g, "").trim(),
        weight: r.style.getPropertyValue("font-weight") || "400",
        style: r.style.getPropertyValue("font-style") || "normal", urls}); } }
  const logo = document.querySelector(
    "header a img, header img, header svg, nav img, nav svg, " +
    "[class*=logo] img, [class*=logo] svg, img[alt*=logo i]");
  out.logo = logo ? (logo.tagName.toLowerCase() === "svg" ? {svg: logo.outerHTML}
                                                           : {src: logo.currentSrc || logo.src}) : null;
  return out;
}"""


# --- colours ------------------------------------------------------------------------------------


def rgb(value: str) -> tuple[int, int, int] | None:
    numbers = re.findall(r"[\d.]+", value or "")
    if not (value or "").startswith("rgb") or len(numbers) < 3:
        return None
    if len(numbers) >= 4 and float(numbers[3]) < 0.5:
        return None  # transparent or nearly: not a colour of the page
    return tuple(int(float(n)) for n in numbers[:3])  # type: ignore[return-value]


def rgb_any(value: str) -> tuple[int, int, int] | None:
    """#RGB / #RRGGBB / rgb() colours (other notations: None)."""
    value = value.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
        return tuple(int(c * 2, 16) for c in value[1:])  # type: ignore[return-value]
    return rgb(value)


def hex_of(color: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def saturation(color: tuple[int, int, int]) -> float:
    high, low = max(color), min(color)
    return 0.0 if high == 0 else (high - low) / high


def luminance(color: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum(abs(x - y) for x, y in zip(a, b, strict=True))


def clean_font(family: str) -> str:
    first = family.split(",")[0].strip().strip("\"'")
    match = re.fullmatch(r"__(.+?)_[0-9a-f]{4,}", first)  # Next.js font names
    name = (match.group(1) if match else first).replace("_Fallback", "")
    generic = {"system-ui", "sans-serif", "serif", "-apple-system", "ui-sans-serif", "monospace"}
    return "system-ui" if name in generic else f'"{name}"'


def font_stack(family: str) -> str:
    name = clean_font(family)
    return "system-ui, sans-serif" if name == "system-ui" else f"{name}, system-ui, sans-serif"


def tokens_from_measure(m: dict) -> dict[str, str]:
    t = dict(DEFAULTS)
    body, page = m.get("body") or {}, m.get("html") or {}
    bg = rgb(body.get("background", "")) or rgb(page.get("background", "")) or (255, 255, 255)
    ink = rgb(body.get("color", "")) or ((20, 22, 26) if luminance(bg) > 0.4 else (240, 240, 240))
    t["--bg"], t["--ink"] = hex_of(bg), hex_of(ink)
    # Surface: the largest background that is close to, but not, the page background (cards).
    for value, _ in m.get("backgrounds", []):
        color = rgb(value)
        if color and color != bg and distance(color, bg) < 90 and saturation(color) < 0.25:
            t["--surface"] = hex_of(color)
            break
    else:
        t["--surface"] = "color-mix(in srgb, var(--ink) 5%, var(--bg))"
    # Muted text: a frequent text colour between ink and background.
    for value, _ in m.get("colors", []):
        color = rgb(value)
        # between ink and background: far enough from the ink, closer to the background than it
        if (color and saturation(color) < 0.25 and distance(color, ink) > 60
                and 120 < distance(color, bg) < distance(ink, bg) - 60):
            t["--muted"] = hex_of(color)
            break
    else:
        t["--muted"] = "color-mix(in srgb, var(--ink) 60%, var(--bg))"
    # Accent: the background of the app's buttons (its primary action colour).
    buttons = Counter()
    for button in m.get("buttons", []):
        color = rgb(button.get("background", ""))
        if color and saturation(color) > 0.3:
            buttons[color] += 1
    if not buttons:
        for value, count in m.get("colors", []):
            color = rgb(value)
            if color and saturation(color) > 0.45:
                buttons[color] += count
    if buttons:
        accent = buttons.most_common(1)[0][0]
        t["--accent"] = hex_of(accent)
        t["--accent-ink"] = "#FFFFFF" if luminance(accent) < 0.45 else "#111111"
    radii = [b.get("radius") for b in m.get("buttons", []) + m.get("cards", []) if b.get("radius")]
    pixels = [float(r[:-2]) for r in radii if r.endswith("px") and float(r[:-2]) > 0]
    if pixels:
        t["--radius"] = f"{min(max(Counter(pixels).most_common(1)[0][0] * 1.5, 6), 32):.0f}px"
    heading = (m.get("h1") or m.get("h2") or body or {}).get("font")
    if heading:
        t["--font-heading"] = font_stack(heading)
    if body.get("font"):
        t["--font-body"] = font_stack(body["font"])
    return t


# --- design-system files ------------------------------------------------------------------------

SLOTS = [  # (variable, name keywords in priority order, kind)
    ("--accent", ["primary", "accent", "brand", "action"], "color"),
    ("--bg", ["background", "bg", "canvas", "page"], "color"),
    ("--surface", ["surface", "card", "panel", "elevated", "secondary"], "color"),
    ("--ink", ["foreground", "text", "ink", "fg", "on-background"], "color"),
    ("--muted", ["muted", "subtle", "secondary-text", "text-secondary", "tertiary"], "color"),
    ("--accent-ink", ["primary-foreground", "on-primary", "accent-foreground"], "color"),
    ("--radius", ["radius"], "size"),
    ("--font-heading", ["heading", "display", "title"], "font"),
    ("--font-body", ["body", "sans", "base", "text"], "font"),
]
MUTED_WORDS = ("muted", "subtle", "secondary", "tertiary", "disabled", "placeholder")
HSL_TRIPLET = re.compile(r"^-?\d+(\.\d+)?\s+\d+(\.\d+)?%\s+\d+(\.\d+)?%$")


def flatten(data: object, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        if "$value" in data or "value" in data:
            value = data.get("$value", data.get("value"))
            if isinstance(value, str | int | float):
                out[prefix] = str(value)
            return out
        for key, value in data.items():
            if not str(key).startswith("$"):
                out.update(flatten(value, f"{prefix}-{key}" if prefix else str(key)))
    elif isinstance(data, str | int | float):
        out[prefix] = str(data)
    return out


def read_tokens(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        flat = flatten(json.loads(text))
        return {k.lower().replace(".", "-").replace("_", "-"): v for k, v in flat.items()}
    found = re.findall(r"--([\w-]+)\s*:\s*([^;}{]+);", text)
    return {name.lower(): value.strip() for name, value in found}


def normalise(value: str, kind: str) -> str | None:
    value = value.strip()
    if kind == "color":
        if HSL_TRIPLET.match(value):
            return f"hsl({value})"  # shadcn/Tailwind style "222 84% 5%"
        if re.match(r"^(#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\(|oklch\(|oklab\(|lab\(|color\()", value):
            return value
        return None
    if kind == "size":
        return value if re.match(r"^[\d.]+(px|rem|em)$", value) else None
    if kind != "font" or re.match(r"^[\d.]", value):
        return None
    if "," not in value:  # a bare family name: quote it and add fallbacks
        return f'"{value.strip(chr(34) + chr(39))}", system-ui, sans-serif'
    return value


def tokens_from_file(found: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    t, mapping = dict(DEFAULTS), {}
    used: set[str] = set()
    for variable, keywords, kind in SLOTS:
        candidates = [n for n in found if n not in used and (kind != "font" or "font" in n)]
        for keyword in keywords:
            names = [n for n in candidates if keyword in n.split("-") or n.endswith(keyword)]
            if variable == "--accent":
                names = [n for n in names if "foreground" not in n and "text" not in n]
            if variable == "--bg":
                names = [n for n in names if "foreground" not in n]
            if variable == "--ink":  # the main text colour, not its muted variants
                names = [n for n in names if not any(m in n for m in MUTED_WORDS)]
            value = next(((n, normalise(found[n], kind)) for n in sorted(names, key=len)
                          if normalise(found[n], kind)), None)
            if value:
                t[variable] = value[1]
                mapping[variable] = value[0]
                used.add(value[0])
                break
    # Derived slots: a heading font defaults to the body font, the text on the accent to the
    # colour that contrasts with it.
    if "--font-heading" not in mapping and "--font-body" in mapping:
        t["--font-heading"] = t["--font-body"]
    accent = rgb_any(t["--accent"])
    if "--accent-ink" not in mapping and accent:
        t["--accent-ink"] = "#FFFFFF" if luminance(accent) < 0.45 else "#111111"
    return t, mapping


# --- capture --------------------------------------------------------------------------------------


async def measure(urls: list[str], output: Path, consent: bool) -> dict:
    merged: dict = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        for i, url in enumerate(urls, start=1):
            await page.goto(url, wait_until="networkidle", timeout=60_000)
            await page.wait_for_timeout(1200)
            if consent:
                for label in CONSENT:
                    try:
                        await page.get_by_role("button", name=label, exact=True).first.click(timeout=600)
                        await page.wait_for_timeout(600)
                        break
                    except Exception:  # no such consent button on this page
                        continue
            await page.screenshot(path=output / f"screen-{i}.png")
            result = await page.evaluate(MEASURE_JS)
            if not merged:
                merged = result
            else:  # later pages add their buttons, cards and fonts
                for key in ("buttons", "cards", "fontFaces"):
                    merged[key] += result.get(key, [])
        await browser.close()
    return merged


def download_fonts(faces: list[dict], output: Path) -> int:
    folder = output / "fonts"
    rules, count = [], 0
    for face in faces[:16]:
        url = next((u for u in face["urls"]
                    if u.split("?")[0].endswith((".woff2", ".woff", ".ttf", ".otf"))), None)
        if not url:
            continue
        name = Path(urllib.parse.urlparse(url).path).name
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=20) as response:
                folder.mkdir(exist_ok=True)
                (folder / name).write_bytes(response.read())
        except OSError:
            continue
        rules.append(f'@font-face {{ font-family: "{face["family"]}"; font-weight: {face["weight"]}; '
                     f'font-style: {face["style"]}; src: url("fonts/{name}"); }}')
        count += 1
    (output / "fonts.css").write_text("\n".join(rules) + "\n", encoding="utf-8")
    return count


def save_logo(logo: dict | None, base_url: str, output: Path) -> str | None:
    if not logo:
        return None
    if logo.get("svg"):
        (output / "logo.svg").write_text(logo["svg"], encoding="utf-8")
        return "logo.svg"
    source = urllib.parse.urljoin(base_url, logo.get("src", ""))
    suffix = Path(urllib.parse.urlparse(source).path).suffix or ".png"
    try:
        with urllib.request.urlopen(urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=20) as response:
            (output / f"logo{suffix}").write_bytes(response.read())
        return f"logo{suffix}"
    except (OSError, ValueError):
        return None


def write_tokens(output: Path, tokens: dict[str, str], source: str,
                 extra: dict[str, str] | None = None) -> None:
    lines = [f"/* Slide tokens — {source}. A measured first guess: check against the screenshots. */",
             ":root {"]
    lines += [f"  {k}: {v};" for k, v in tokens.items()]
    if extra:
        lines.append("  /* every variable of the design system, usable in slides.html */")
        lines += [f"  --ds-{k}: {v};" for k, v in extra.items()]
    lines.append("}")
    (output / "tokens.css").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    parser.add_argument("site", nargs="?", help="a brand website (same as --url)")
    parser.add_argument("--url", help="capture a brand website instead of the app")
    parser.add_argument("--tokens", type=Path, help="design-system file (.css or .json) to use")
    parser.add_argument("--pages", default="/", help="app pages to read, comma separated")
    parser.add_argument("--screens", type=int, default=3, help="website screenfuls to capture")
    parser.add_argument("--normal", action="store_true",
                        help="start the app in normal mode (if safe mode shows a banner on screen)")
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    output = config.root / "slides" / "style"
    output.mkdir(parents=True, exist_ok=True)
    url = args.url or args.site

    if args.tokens:
        found = read_tokens(args.tokens)
        tokens, mapping = tokens_from_file(found)
        write_tokens(output, tokens, f"from {args.tokens.name}", found)
        (output / "fonts.css").write_text("", encoding="utf-8")
        (output / "source.txt").write_text(f"design system: {args.tokens.resolve()}\n", encoding="utf-8")
        print(f"{len(found)} variables read from {args.tokens}")
        for variable, _, _ in SLOTS:
            print(f"  {variable:15} ← {mapping.get(variable, '(default)'):35} {tokens[variable]}")
        print("unmatched slots keep a neutral default — set them by hand in tokens.css if needed")
        return 0

    server = None
    if url:
        urls = [url]
        source = f"website {url}"
    else:
        # Safe mode by default; --normal when safe mode marks the screens (a banner, a watermark):
        # the capture only reads pages, it never clicks.
        server = Server(config, safe=not args.normal, log_path=output / "server.log")
        server.start()
        urls = [config.app_url + "/" + p.strip().lstrip("/") for p in args.pages.split(",") if p.strip()]
        source = f"the app ({', '.join(urls)})"
    try:
        measured = asyncio.run(measure(urls, output, consent=bool(url)))
    finally:
        if server is not None:
            server.stop()
    if url and args.screens > 1:
        asyncio.run(_scroll_screens(url, output, args.screens))
    tokens = tokens_from_measure(measured)
    fonts = download_fonts(measured.get("fontFaces", []), output)
    logo = save_logo(measured.pop("logo", None), urls[0], output)
    measured["logo_file"] = logo
    (output / "styles.json").write_text(json.dumps(measured, ensure_ascii=False, indent=1), encoding="utf-8")
    write_tokens(output, tokens, f"measured on {source}")
    (output / "source.txt").write_text(source + "\n", encoding="utf-8")
    print(f"style captured from {source} → {output}")
    for key, value in tokens.items():
        print(f"  {key:15} {value}")
    print(f"  {fonts} web font file(s) saved, logo: {logo or 'none found'}, "
          f"{len(list(output.glob('screen-*.png')))} screenshot(s)")
    return 0


async def _scroll_screens(url: str, output: Path, count: int) -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        for i in range(1, count):
            await page.evaluate(f"window.scrollTo(0, {900 * i})")
            await page.wait_for_timeout(800)
            await page.screenshot(path=output / f"screen-{i + 1}.png")
        await browser.close()


if __name__ == "__main__":
    sys.exit(main())
