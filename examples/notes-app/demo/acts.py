"""The acts of the demo: what is clicked, typed and waited for, scene by scene.

`t` is the Director (demokit/director.py). Rules:
- every filmed action sits inside `async with t.scene("<id>")`, ids from scenes.json;
- a costly scene starts with `if await t.should_play("<id>"):` — in retakes it is skipped and its
  `restore_after` save is restored off camera;
- in the live pass, `await t.save("<name>")` after each step that changes the state (and before
  each costly scene): the retakes restart from these saves;
- wait on the app's real state with `t.wait_until(...)`, never with a fixed sleep;
- a choice not settled by inputs.md: take the safest option and log it with `t.decide(...)`.
"""

from __future__ import annotations

from demokit.director import CleanStop, Director

ITEM_TITLE = "Quarterly report"  # inputs come from inputs.md, never invented here


async def act_1(t: Director) -> None:
    await t.goto("/", heading="Items")
    async with t.act(1, "Discover the app"):
        async with t.scene("1.1"):
            await t.hover(t.page.get_by_role("link", name="New item"))
            await t.pause(1.5)
        async with t.scene("1.2"):
            await t.click(t.page.get_by_role("link", name="New item"))
            await t.type(t.page.get_by_label("Title"), ITEM_TITLE)
            await t.click(t.page.get_by_role("button", name="Create"))
            await t.page.get_by_role("heading", name=ITEM_TITLE).wait_for()
    await t.save("01-after-create")


async def act_2(t: Director) -> None:
    await t.goto("/", heading="Items")
    async with t.act(2, "Generate"):
        async with t.scene("2.1"):
            await t.click(t.page.get_by_role("link", name=ITEM_TITLE))
            await t.save("02-before-generate")
        if await t.should_play("2.2"):
            async with t.scene("2.2"):
                await t.click(t.page.get_by_role("button", name="Generate"))
                await t.confirm()

                async def done() -> bool:
                    job = await t.api_get("api/job")
                    if job["status"] == "failed":
                        raise CleanStop("generation", job.get("error") or "failed",
                                        "restore 02-before-generate, then --from 2.2")
                    return job["status"] == "done"

                await t.wait_until("generation", done, timeout_min=30)
            await t.save("02-after-generate")
        async with t.scene("2.3"):
            await t.page.reload()
            await t.scroll_to(t.page.get_by_role("heading", name="Result"))
            await t.pause(2)


ACTS = {1: act_1, 2: act_2}
# Save restored at the start of each act in a retake (the state the act starts from).
ACT_START = {1: "00-start", 2: "01-after-create"}
