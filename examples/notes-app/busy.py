"""Exit 1 while a generation is running (state.busy_command of the example's demo.toml)."""

import json
import sys
from pathlib import Path

state = Path(__file__).resolve().parent / "data" / "state.json"
job = json.loads(state.read_text(encoding="utf-8"))["job"] if state.is_file() else {}
if job.get("status") == "running":
    print(f"generation running for item {job.get('item')}")
    sys.exit(1)
