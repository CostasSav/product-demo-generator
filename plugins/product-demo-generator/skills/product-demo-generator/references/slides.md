# Intro and outro slides

The slides frame the demo: a short intro (the problem, how it is done today, the product) and an
outro (what the demo showed, the closing line). They should look like **the product being shown**,
not like a generic template.

## Where the style comes from

Ask the user once, before writing the slides: "By default the intro and outro take the look of
your app. Do you have a design system or brand guidelines you would rather use?"

| Source | Command | When |
|---|---|---|
| **the app** (default) | `RUN style --pages /,<page with a result>` | always works; the slides match what the viewer sees next |
| a design-system file | `RUN style --tokens path/to/tokens.css` (or `.json`) | the user has CSS variables or JSON tokens (W3C, Style Dictionary, Tokens Studio, shadcn/Tailwind HSL triplets) |
| a brand website | `RUN style --url https://…` | the video represents a company or a brand distinct from the app |
| guidelines given in words or a PDF | edit `slides/style/tokens.css` by hand | colours, fonts, logo given by the user |

`RUN style` writes `slides/style/`:
- `tokens.css` — `--bg --surface --ink --muted --accent --accent-ink --radius --font-heading
  --font-body`, the only variables the template uses (a tokens file also adds all its own
  variables as `--ds-*`, usable for finer touches);
- `fonts.css` + `fonts/` — the web fonts the app serves itself, so the slides use the real
  typeface (a Google Font the app loads from Google is not downloaded: add its `<link>` to the
  slides);
- `screen-N.png` — screenshots of the pages read, shown in browser frames on the slides: pick
  pages that show the product at its best (a list with data, a result), not an empty state;
- `styles.json` — what was measured (buttons, cards, colours, fonts), `logo.*` when one is found.

From the app, the capture starts it in safe mode, reads the pages and stops it — it never clicks.
If safe mode marks the screen (a banner, a watermark), use `--normal`. Read the printed tokens
against the screenshots: the accent is the colour of the app's buttons; if the app has none,
the most frequent saturated colour is used — check it.

## Writing the slides

`slides/slides.html` (scaffolded) holds five slides, one per voice line; each
`<section class="slide" data-file="…png">` becomes one image:

1. `intro1` hero — the problem in one sentence (one phrase in the accent colour), who has it,
   and the real product in a browser frame;
2. `intro2` today — the manual steps (three cards) and what they cost, only if the user gives a
   figure; never invent one;
3. `intro3` product — the product's name and promise, full bleed on the accent colour, with two
   screenshots;
4. `outro1` / `outro2` recap — what the demo showed (three benefits, checked), the final screen;
   `outro2` adds the closing band, so the line appears when it is said (the two slides share a
   `group` and crossfade).

Rules:
- Few words: the voice says the sentence, the slide shows its anchor.
- Text from the scene lines and inputs only: no invented figures, customers or quotes.
- No contact block, URL or logo of another company unless the user asks for it.
- Change the layout when the content calls for it (two steps instead of three, a single
  screenshot): the template is a starting point, the style tokens are what keep it consistent.
- Use a brand only with the right to (the user's company, or a client who agreed).

`RUN slides` renders every section at the video's size, fonts loaded. Open each PNG: nothing
clipped, the accent word, readable contrast on the accent slide, no leftover template text, no
"run.py style →" placeholder (a missing screenshot).

## In scenes.json

```json
{"id": "0.1", "act": 0, "mode": "slide", "slide": "intro1.png", "group": "intro", "text": "…"},
{"id": "0.2", "act": 0, "mode": "slide", "slide": "intro2.png", "group": "intro", "text": "…"},
{"id": "0.3", "act": 0, "mode": "slide", "slide": "intro3.png", "group": "intro", "text": "…"},
{"id": "9.1", "act": 9, "mode": "slide", "slide": "outro1.png", "group": "outro", "text": "…"},
{"id": "9.2", "act": 9, "mode": "slide", "slide": "outro2.png", "group": "outro", "text": "…"}
```

Consecutive scenes of a group crossfade (`montage.crossfade_s`), each fade centred on the
boundary, so the voice timing never moves. Between a slide and app footage the cut is direct. The
last frame is held `montage.outro_s` with the music fading out.
