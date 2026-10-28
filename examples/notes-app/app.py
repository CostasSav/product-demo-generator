"""A tiny web app to try product-demo-generator on (standard library only).

    python app.py --port 8765          # normal mode: "Generate" runs a slow, "paid" job
    python app.py --port 8765 --safe   # safe mode: "Generate" is refused, nothing is spent

State lives in data/state.json; every generation appends its (fake) cost to data/spend.jsonl.
"""

from __future__ import annotations

import argparse
import html
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

DATA = Path(__file__).resolve().parent / "data"
STATE = DATA / "state.json"
SPEND = DATA / "spend.jsonl"
LOCK = threading.Lock()
SAFE = False
JOB_SECONDS = 6.0

STYLE = """
body { font: 18px/1.5 system-ui, sans-serif; margin: 0; background: #f6f7fb; color: #15161a; }
header { background: #15161a; color: #fff; padding: 14px 32px; font-weight: 600; }
main { max-width: 860px; margin: 40px auto; background: #fff; border-radius: 14px; padding: 36px 44px;
  box-shadow: 0 10px 30px rgba(0,0,0,.06); }
a.button, button { display: inline-block; background: #4f46e5; color: #fff; border: 0; border-radius: 10px;
  padding: 10px 18px; font: inherit; text-decoration: none; cursor: pointer; }
li { margin: 8px 0; } input { font: inherit; padding: 8px 12px; width: 100%; box-sizing: border-box; }
label { display: block; margin: 16px 0 6px; font-weight: 600; }
.progress { height: 10px; background: #e5e7eb; border-radius: 6px; overflow: hidden; margin: 16px 0; }
.progress div { height: 100%; background: #4f46e5; transition: width .4s; }
dialog { border: 0; border-radius: 14px; padding: 28px; box-shadow: 0 20px 60px rgba(0,0,0,.25); }
"""


def load() -> dict:
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"items": [], "job": {"status": "idle", "item": None, "started": None}}


def store(state: dict) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{html.escape(title)}</title>"
            f"<style>{STYLE}</style></head><body><header>Notes</header>"
            f"<main>{body}</main></body></html>").encode()


def run_job(item_id: int) -> None:
    time.sleep(JOB_SECONDS)
    with LOCK:
        state = load()
        for item in state["items"]:
            if item["id"] == item_id:
                item["result"] = f"Summary of “{item['title']}”: three key points, two risks, one decision."
        state["job"] = {"status": "done", "item": item_id, "started": state["job"]["started"]}
        store(state)
        DATA.mkdir(exist_ok=True)
        with SPEND.open("a", encoding="utf-8") as spend:
            spend.write(json.dumps({"cost_usd": 0.05, "item": item_id}) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet
        pass

    def send(self, body: bytes, status: int = 200, kind: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:
        state = load()
        if self.path == "/":
            items = "".join(f'<li><a href="/items/{i["id"]}">{html.escape(i["title"])}</a></li>'
                            for i in state["items"]) or "<li>No item yet.</li>"
            self.send(page("Items", f'<h1>Items</h1><ul>{items}</ul>'
                                    '<a class="button" href="/new">New item</a>'))
        elif self.path == "/new":
            self.send(page("New item", '<h1>New item</h1><form method="post" action="/items">'
                                       '<label for="t">Title</label><input id="t" name="title" required>'
                                       '<p><button type="submit">Create</button></p></form>'))
        elif self.path.startswith("/items/"):
            item = next((i for i in state["items"] if str(i["id"]) == self.path.split("/")[2]), None)
            if item is None:
                self.send(page("Not found", "<h1>Not found</h1>"), 404)
                return
            job = state["job"]
            running = job["status"] == "running" and job["item"] == item["id"]
            if item.get("result"):
                extra = f'<h2>Result</h2><p>{html.escape(item["result"])}</p>'
            elif running:
                extra = ('<h2>Generating…</h2><div class="progress"><div id="bar" style="width:5%">'
                         '</div></div><script>const t0=Date.now();setInterval(async()=>{'
                         'const j=await (await fetch("/api/job")).json();'
                         'document.getElementById("bar").style.width='
                         f'Math.min(95,(Date.now()-t0)/{JOB_SECONDS * 10})+"%";'
                         'if(j.status==="done")location.reload();},500);</script>')
            else:
                extra = ('<button id="go" onclick="document.getElementById(\'confirm\').showModal()">'
                         'Generate</button><dialog id="confirm"><form method="post" '
                         f'action="/items/{item["id"]}/generate"><h3>Generate a summary?</h3>'
                         '<p>This calls a paid model (about $0.05).</p><button type="submit">Confirm'
                         '</button></form></dialog>')
            self.send(page(item["title"], f'<p><a href="/">← Items</a></p>'
                                          f'<h1>{html.escape(item["title"])}</h1>{extra}'))
        elif self.path == "/api/job":
            self.send(json.dumps(state["job"]).encode(), kind="application/json")
        else:
            self.send(page("Not found", "<h1>Not found</h1>"), 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode())
        with LOCK:
            state = load()
            if self.path == "/items":
                new_id = max((i["id"] for i in state["items"]), default=0) + 1
                state["items"].append({"id": new_id, "title": form.get("title", ["Untitled"])[0]})
                store(state)
                self.redirect(f"/items/{new_id}")
                return
            if self.path.endswith("/generate"):
                item_id = int(self.path.split("/")[2])
                if SAFE:
                    self.send(page("Refused", "<h1>Safe mode: generation refused</h1>"), 403)
                    return
                state["job"] = {"status": "running", "item": item_id, "started": time.time()}
                store(state)
                threading.Thread(target=run_job, args=(item_id,), daemon=True).start()
                self.redirect(f"/items/{item_id}")
                return
        self.send(page("Not found", "<h1>Not found</h1>"), 404)


def main() -> None:
    global SAFE
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--safe", action="store_true")
    args = parser.parse_args()
    SAFE = args.safe
    print("SAFE MODE: nothing paid can run" if SAFE else "normal mode", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
