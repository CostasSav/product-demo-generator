# Filming — acts, scenes, live pass, retakes

## The director (`t` in acts.py)

| Call | What it does |
|---|---|
| `async with t.act(n, title)` | one video `act<n>.mp4` + `act<n>.chapters.json/txt` |
| `async with t.scene(id)` | a chapter; in retakes it lasts at least the scene's voice + `voice_pad_s` |
| `await t.should_play(id)` | False for a costly scene in retakes (its `restore_after` is restored off camera) or before `--from` in the live pass |
| `async with t.off_camera(reason)` | the picture freezes out of the video (long typing, setup) |
| `await t.save(name)` / `t.restore(name)` | live only / anywhere (off camera, page reloaded) |
| `await t.wait_until(label, check, timeout_min)` | polls `check()`; raise `CleanStop` inside on failure |
| `await t.api_get(path)` | JSON GET on the app, retried on transient errors |
| `t.decide(subject, decision)` | logs a choice not settled by inputs.md (`decisions.md` + chapter) |
| `t.goto(path, heading=…, reload=False)` | open a page, wait for its heading |
| `t.click(locator)`, `t.hover`, `t.move(x, y)` | eased cursor moves, ripple and highlight on click |
| `t.type(field, text, paste=False)` | human-speed typing (`filming.typing_ms`); `paste` for long text |
| `t.blur()`, `t.scroll(px)`, `t.scroll_to(locator)` | leave a field (save-on-blur apps), smooth scrolls |
| `t.confirm(read_s=2.2)` | waits for the confirmation dialog, lets it be read, confirms |
| `t.ghost(text)` | a label following the cursor (drag and drop) |
| `t.pause(s)` | pauses scale with `--pace` |
| `t.page` | the raw Playwright page |

Locators: prefer roles and labels (`get_by_role("button", name="Create")`, `get_by_label`), as a
user would read the screen. An `id` with dots or quotes: `page.locator('[id="a.b"]')`.

## Writing an act

```python
async def act_2(t):
    await t.goto("/projects", heading="Projects")        # set-up, before the video starts
    async with t.act(2, "Generate the report"):
        async with t.scene("2.1"):
            await t.click(t.page.get_by_role("link", name=PROJECT))
        await t.save("02-before-generate")                # the live pass can resume here
        if await t.should_play("2.2"):                    # costly: live pass only
            async with t.scene("2.2"):
                await t.click(t.page.get_by_role("button", name="Generate"))
                await t.confirm()
                await t.wait_until("report", report_done, timeout_min=40)
            await t.save("02-after-generate")             # = restore_after of 2.2
        async with t.scene("2.3"):
            ...
```

- Waiting: read the app's own truth (an API, a job table, a log file on disk), not the screen.
  When the API can be slow under load, read the file the app writes directly.
- A long job the viewer should see progressing: stay on the progress screen during the scene;
  the montage drops frozen frames and speeds it up with a "real time" counter.
- Typing a paragraph: `paste=True`, or type the first words on camera and the rest off camera.
- A choice the inputs do not settle: the safest option (spends nothing, sends nothing, anonymised,
  consistent with the scenario), and `t.decide(...)` — never stop to ask during a live pass.
- Showing a gesture whose effect would cost money in a retake (e.g. ticking "rewrite with AI"
  that triggers a paid job on validation): show the gesture, then restore the save that follows
  instead of validating.

## Rehearsal (free)

Before the live pass: `RUN state save 00-start`, then `RUN film --mode retake --act N --headed`
for each act. Costly scenes are skipped with a "rehearsal" warning (their saves do not exist yet),
so later scenes may run on an un-advanced state — enough to fix selectors and timings.

## Live pass

`RUN film --mode live` saves `00-start`, then plays every act. Run it in the background; follow
its output. Each costly scene checks the budget first; chapters record each scene's spend.

Stops (exit code 3, `CLEAN STOP — …` with the way to resume):
- rate limit / subscription window: wait, then
  `RUN film --mode live --from 3.2 --restore 03-before-generate`;
- budget / credit / quota: stop and report to the user — never raise a budget yourself;
- failure: restore the save before the scene, try once more with `--from`; if it fails again,
  stop and report.

Write `demo/report.md` afterwards: scenes filmed and their takes, spend per scene, incidents and
how they were handled, saves made, app bugs seen (with the scene where they show).

## Retakes

`RUN film --mode retake --act N [--pace 0.8] [--duration 2.3=12]` restores the act's start
(`ACT_START`), plays free scenes, restores `restore_after` for costly ones. Scene length = its
voice (recorded, else placeholder) + `voice_pad_s`; a scene that runs longer is noted in the
chapters (the montage speeds it up to ×2 at most).

Hiding something in a retake (an error the live pass hit, a failed job): restore a save taken
after it, or skip the scene and let the montage use the live take for it (`"take": "live"`).

## Lost or unusable footage

If a live take is lost (crash, corrupted file) but its result was saved, reconstruct the screen
instead of paying again: on the safe server, restore the save *before* the step, then replay the
app's real event log (job started / done, in order, with compressed timing) by writing the same
records the app writes, copying each result from the save *after* the step as it "completes".
The screen updates as it did live. End by restoring the state you started from — not a fixed
save: the app may have moved on since.
