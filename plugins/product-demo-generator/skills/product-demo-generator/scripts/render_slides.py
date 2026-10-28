"""Render the intro / outro slides (`slides/slides.html`) to PNG at the video's size.

    run.py slides --demo-dir demo

Every `<section class="slide" data-file="intro1.png">` of slides.html becomes
`slides/<data-file>`, rendered at browser.width × browser.height, web fonts loaded. scenes.json
points `slide` scenes at these files; consecutive scenes of the same `group` crossfade.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from demokit import config as config_module
from playwright.async_api import async_playwright


async def render(html: Path, width: int, height: int) -> list[Path]:
    written = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.goto(html.as_uri(), wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        sections = page.locator("section.slide[data-file]")
        for i in range(await sections.count()):
            section = sections.nth(i)
            name = await section.get_attribute("data-file")
            target = html.parent / name
            await section.screenshot(path=target)
            written.append(target)
            print(target.name)
        await browser.close()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-dir", type=Path, default=Path("demo"))
    args = parser.parse_args(argv)
    config = config_module.load(args.demo_dir)
    html = config.root / "slides" / "slides.html"
    if not html.is_file():
        raise SystemExit(f"{html} not found (scaffolded by `run.py new`)")
    browser = config.section("browser")
    written = asyncio.run(render(html, int(browser["width"]), int(browser["height"])))
    print(f"{len(written)} slides rendered in {html.parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
