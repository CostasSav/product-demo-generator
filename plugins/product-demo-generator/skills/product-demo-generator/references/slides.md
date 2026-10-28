# Intro and outro slides in a brand's style

## Capture the brand

`RUN brand https://… [--pages 5]` → `slides/brand/`: screenshots, `styles.json` (fonts, sizes,
most used colours, headings), the header logo when found, and `tokens.css` (a first guess of the
CSS variables). Look at the screenshots before trusting the tokens: the accent colour is the one
used for *emphasis* (a highlighted word, the primary button), not necessarily the most frequent.

Use a brand only with the right to: the user's company, or a client who agreed.

## Design the slides

`slides/slides.html` has one `<section class="slide" data-file="…png">` per image. Replace the
`:root` tokens with the brand's, load its fonts (Google Fonts, or `@font-face` on files), and
write one slide per voice line:

- **Intro** (3 slides is plenty): the situation (a concrete moment, e.g. the request arriving,
  with a card showing it), the cost today (one big number + the long tasks), the product name.
- **Outro** (one slide, two states): the message + 3–4 guarantees, then the same slide with the
  closing line appearing — `outro1.png` / `outro2.png` in the same `group` crossfade, so the line
  fades in exactly when it is said.
- What reads as "the brand": its background and texture, its heading font, ONE accent word per
  headline (italic or colour), small letter-spaced capitals for labels, its card radius and
  shadow, its logo top-left or at the bottom.
- Few words: the voice says the sentence, the slide shows its anchor. No contact block unless the
  user asks for one.
- Never put a real client's name on a slide without the user's explicit agreement.

`RUN slides` renders every section at the video's size (web fonts loaded) — open each PNG and
check: nothing clipped, contrast, the accent word, no leftover template text.

## In scenes.json

```json
{"id": "0.1", "act": 0, "mode": "slide", "slide": "intro1.png", "group": "intro", "text": "…"},
{"id": "0.2", "act": 0, "mode": "slide", "slide": "intro2.png", "group": "intro", "text": "…"},
{"id": "9.1", "act": 9, "mode": "slide", "slide": "outro1.png", "group": "outro", "text": "…"},
{"id": "9.2", "act": 9, "mode": "slide", "slide": "outro2.png", "group": "outro", "text": "…"}
```

Consecutive scenes of a group crossfade (`montage.crossfade_s`), each fade centred on the
boundary, so the voice timing never moves. Between a slide and the app footage the cut is
direct. The outro's last frame is held `montage.outro_s` with the music fading out.
