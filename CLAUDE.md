# CLAUDE.md — Figma_Service

## What This Is

A Python + JavaScript bridge that automates Figma via the **Scripter** community plugin.
Playwright drives a persistent Firefox profile; user code is injected into Monaco, executed in Scripter's sandbox, and results are returned over the `console.log` sentinel protocol.

---

## Token-Saving Rules

- Read only the files needed for the task. Prefer `Grep` over `Read` for locating symbols.
- Use `offset`/`limit` when reading large files.
- Default model: **Sonnet 4.6**. No extended thinking unless explicitly requested.
- Avoid re-reading files unless necessary (file changed or context may be stale)
- Avoid creating docs unless they provide long-term value
- Keep CLI behavior stable unless explicitly changing it
- Prefer small, incremental changes over large rewrites
- Do not perform any Git operations. Do not create branches, commits, or pull requests. Do not run git commands. All Git-related actions are handled manually outside of this environment.
- Focus only on code and runtime behavior.
- Avoid workflow or process suggestions unless explicitly asked.

---

## Command Conventions

Use high-level command prefixes:

- read_*      → read-only operations (no side effects)
- sync_*      → create or update data (must be idempotent)
- validate_*  → safety and consistency checks
- cmd_*       → user-facing orchestration commands
- plan_*      → preview or planning (no changes)

Rules:
- prefer these commands over free-form instructions
- do not invent new prefixes
- keep commands small and focused
- avoid combining multiple responsibilities in one command
- do not execute large multi-step plans at once

Execution:
- run commands step by step
- start with the smallest useful slice
- validate before sync when possible
- support dry-run / plan before applying changes

---

## Commands

```bash
# Setup (one-time)
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
playwright install firefox
cp .env.example .env        # then set FIGMA_FILE_URL

# Login (one-time; opens Firefox for manual sign-in)
python run.py login

# Smoke test
python run.py hello -m "bridge alive"

# Execute JS inline (≤500 B result)
python run.py exec-inline --code 'return 42;'

# Execute JS to file (≤65 KB result)
python run.py exec --code 'return bigResult();' --out /tmp/r.json

# Read sub-app queries (8 commands)
python run.py read ping
python run.py read document-summary --out /tmp/doc.json

# Tests
pytest tests/ -v
```

---

## Architecture

```
run.py              CLI entry (Typer); re-exports all symbols from siblings for test stability
protocol.py         v2 wire format: Pydantic models, sentinel constants, _reassemble_chunks
transport.py        Playwright + Scripter: launch Firefox, find iframe, inject wrapper, collect sentinels
host_io.py          Code resolution (--code / --code-file / stdin), atomic writes, logging
read_handlers.py    8 read-only Figma query commands with baked JS templates
wrapper.js          Static JS template injected into Scripter sandbox; includes polyfills
tests/              35 pytest unit tests (no Playwright; fully offline)
profile/            Firefox persistent profile — gitignored, holds Figma login session
docs/               Superpowers planning docs — gitignored
```

---

## Critical Patterns & Gotchas

### Wrapper injection
`wrapper.js` is a static template with marker substitution at runtime (`RID`, sentinels, inline cap, chunk bytes). User code goes at `/*__USER_JS__*/`. Scripter sandbox lacks `TextEncoder`, `btoa`, `crypto.subtle` — wrapper includes polyfills for all three. **Never remove them.**

### Sentinel / chunked transport
Wrapper emits `BEGIN` header + N base64 chunks via `console.log`:
```
__FS::RID:C:i:<base64>::SF__
```
`_reassemble_chunks` validates transport SHA256 before decoding. Two distinct hashes exist: **transport** (chunks in flight) and **on-disk** (written file). Do not conflate them.

### Inline vs file mode
No explicit mode flag — determined by `inline_cap` passed to `_bridge_exec`. 500 B → inline, 65536 B → file. Both emit v2 status docs discriminated by `mode` field.

### Two timeouts
- `--mount-timeout` (default 30 s): Scripter iframe discovery + Monaco mount only.
- `--timeout` (default 10 s): script execution from Run-click through BEGIN receipt.

### Atomic writes
Temp file: `.result.json.<pid>.tmp`. Stages: open → write → fsync → chmod 0o600 → rename. Each failure names the failed stage in `detail`. No partial files under the target name.

### Console collector ordering
`page.on("console", handler)` registered **before** `page.goto` — no sentinel can slip through a race. This replaced the earlier `figma.notify` + MutationObserver path, which dropped messages on toast auto-dismiss.

### TTY refusal
`--code-file -` (stdin) errors immediately if `isatty() == True`. Not a bug.

### Re-exports in run.py
`run.py` re-exports all symbols from protocol/transport/host_io/read_handlers so `import run; run.ExecErr` stays stable for tests regardless of internal refactoring.

---

## Protocol v2 Summary

Every command emits **exactly one JSON status doc** on stdout. Exit 0 = ok, exit 1 = error.

```json
{
  "version": "2",
  "request_id": "<uuid>",
  "elapsed_ms": 1234,
  "status": "ok" | "error",
  "mode": "inline" | "file",
  "result": "..." | null,
  "path": "/tmp/r.json" | null,
  "sha256": "...",
  "logs": [],
  "kind": null | "<error_kind>"
}
```

10 error kinds: `script_error`, `timeout`, `mount_timeout`, `input_too_large`, `output_too_large`, `input_read_failed`, `output_write_failed`, `parse_failed`, `hash_mismatch`, `browser_error`.

---

## Environment

```
FIGMA_FILE_URL=https://www.figma.com/file/...   # required
PROFILE_DIR=./profile                            # default
```

---

## Development Phases

| Phase | Scope |
|-------|-------|
| 0 | login, hello |
| 1.5 | exec-inline + exec, v2 protocol |
| 2 (thin slice) | read sub-app (8 commands) |
| C (current) | payload validation on real files |

---

## Testing

Tests are fully offline (no Playwright). Modules:
- `test_protocol.py` — Pydantic model invariants, discriminated unions
- `test_host_io.py` — code resolution, atomic writes, TTY refusal
- `test_reassembly.py` — chunked reassembly, SHA256, corruption handling
- `test_wrapper_load.py` — wrapper.js template markers, no hardcoded sentinels

`conftest.py` adds parent dir to `sys.path` so `import run` works directly.
