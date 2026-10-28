# App integration — what `demo.toml` needs from the app

## Starting the app

The director starts and stops the app itself, on its own port, so it always knows which mode is
running. `start_command` / `safe_command` are shell commands run from `app.cwd` with `{port}`
replaced; the director polls `ready_path` until it answers, and kills the whole process tree on
exit (Windows: `taskkill /T`, elsewhere the process group).

- Several processes (API + front-end dev server)? Prefer serving the built front end from the
  API. Otherwise start a small launcher script that starts both and waits — the director stops
  the launcher's whole tree.
- Docker Compose: `start_command = "docker compose up"` with the port mapped; state items on the
  mounted volumes, or `kind = "command"` with `docker compose exec … dump`.
- App already running and impossible to start from a command: leave `start_command` empty — but
  then safe mode cannot be verified; prefer starting it from the director.
- The commands run with the user's environment **minus** the tool environment's variables
  (`demokit.config.app_env`): a Python app gets its own interpreter, not the tool venv.

## Safe mode (retakes)

Retakes replay free actions only; costly scenes are replaced by restoring the state that follows
them. The app must be **unable** to spend in that mode — a demo script clicking the wrong button
must not cost anything. Good patterns, in order of preference:

1. a flag or env var the app already has (`--demo`, `DRY_RUN=1`, `MOCK_LLM=1`);
2. a guard at the single place paid calls go through: refuse with a clear error in safe mode;
3. a stub provider (fake LLM / email backend) selected by env var.

Set `safe_log_marker` to a regex the app prints at start-up in safe mode: the director refuses to
film retakes if it is missing (and refuses the live pass if it is present).

If the app has no costly action at all, leave `safe_command` empty and mark no scene `costly`.

## State

`[[state.items]]` lists everything the screens read. Ask: if I copy only these and restore them
later, does every screen show exactly the same thing? Typical items:

| Storage | Item |
|---|---|
| data folder (JSON, uploads, generated files) | `kind = "folder"`, `path = "../data"` |
| one file (settings, cache index) | `kind = "file"` |
| SQLite | `kind = "sqlite"` (online backup; restored in place, safe while the app runs) |
| Postgres / MySQL | `kind = "command"`, `save = "pg_dump -Fc db -f {dir}/db.dump"`, `restore = "pg_restore --clean --if-exists -d db {dir}/db.dump"` |
| files shared with other records (global settings, validations) | include them, knowing a restore resets them too |

- `exclude` (glob patterns) keeps an item's matching files at their **current** content on every
  restore. Use it for append-only spend or audit logs: the budget must keep counting what was
  really spent, whatever state is restored.
- An item absent at save time is deleted at restore time (restoring "before upload" empties it).
- Every restore first saves the current state as `_before-restore-<timestamp>`.
- Caches keyed on modification times stay valid: copies keep mtimes.

## Busy signal

`busy_command` exits non-zero while a job runs (and prints what runs). It protects two things:
restores are refused while a job could overwrite them, and a stopped live pass waits for running
jobs before stopping the server (a killed paid job is money lost). Examples:

```toml
busy_command = "python -c \"import json,sys; sys.exit(json.load(open('data/job.json'))['status']=='running')\""
busy_command = "curl -sf http://127.0.0.1:8765/api/health/idle"
```

## Spend log

If the app records what it spends (one JSON object per line with a cost field), point
`live.spend_file` / `live.spend_field` at it: chapters record each scene's cost, and costly scenes
stop once `live.budget_usd` is reached. Never let the demo write to that log.

If the app has its own spending caps that are too low for the shoot, raise them temporarily,
never commit the change, and revert it in clean-up.

## Single-page app quirks

- Some routers break when leaving a route by a mere URL change: `t.goto(path, reload=True)`.
- After a restore the director reloads the page; a front end that caches aggressively may need
  a second reload or a route change.
- Long-running screens that stream updates (SSE, websockets) only refresh while something runs:
  if the screen stops updating, check what the app considers "running".
