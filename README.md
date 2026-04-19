# Figma_Service

Bridge: Claude writes a Figma Plugin API script, `run.py` pastes it into
the Scripter community plugin via a headless-ish Firefox, Scripter executes it.

Top-level commands: `login` (one-time), `hello` (toast smoke test),
`exec-inline` (run JS, return value inline, ≤500 B), and
`exec` (run JS, write result to file, ≤64 KiB).

`read` sub-app: eight read-only Figma queries — document, selection, pages,
variable collections, local styles, and components — each emitting a v2 status doc.

## Quickstart

```bash
cd ~/Documents/claude/Figma_Service

# 1. Install deps
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
playwright install firefox

# 2. One-time setup
cp .env.example .env
python run.py login
#  → Firefox opens. Sign in to Figma, install Scripter from Community,
#    create an empty design file, and paste its URL into .env as FIGMA_FILE_URL.
#    Close the browser when done.

# 3. Smoke test
python run.py hello -m "bridge alive"

# 4. Inline execution
python run.py exec-inline --code 'return figma.currentPage.children.length;'

# 5. File-based execution for large results
python run.py exec --code 'return figma.root.children.map(p => p.name);' --out /tmp/pages.json
cat /tmp/pages.json
```

## Protocol v2

Every command emits exactly one JSON status doc on stdout, logs to stderr,
exits 0 on `ok` or 1 on any `error`. All docs carry:

- `version: 2`
- `request_id`: 16-char hex nonce (per-invocation; enables cross-run isolation)
- `status`: `"ok"` or `"error"`

### Success shapes (discriminated on `mode`)

**`exec-inline`** →
```
{"status":"ok", "mode":"inline", "version":2, "request_id":"<hex>",
 "result":<any>, "elapsed_ms":<n>, "logs":[]}
```

**`exec`** →
```
{"status":"ok", "mode":"file", "version":2, "request_id":"<hex>",
 "result_path":"/abs/path", "bytes":<n>, "sha256":"<hex>",
 "elapsed_ms":<n>, "logs":[]}
```

The on-disk file at `result_path` contains **only the user's `result` value**,
pretty-printed (`indent=2`, `ensure_ascii=False`) with a trailing newline,
written atomically with mode `0o600`.

### Error shape

```
{"status":"error", "version":2, "request_id":"<hex>|null",
 "kind":"<enum>", "message":"<short>", "detail":"<optional>",
 "elapsed_ms":<n>}
```

`kind` ∈ {
`user_exception`, `payload_too_large`, `serialize_failed`,
`timeout`, `injection_failed`, `scripter_unreachable`,
`chunk_incomplete`, `chunk_corrupt`,
`input_read_failed`, `output_write_failed`
}.

`detail` uses stable key=value schemas for machine-readable kinds:

| kind | detail schema |
|---|---|
| `timeout` | `stage=<begin\|chunk_stream> elapsed_ms=<m> timeout_s=<t>` |
| `chunk_incomplete` | `got=<n> expected=<N> missing=<i,j,k,…>` |
| `chunk_corrupt` | `stage=<b64_decode\|length_mismatch\|sha256_mismatch\|json_parse> …` |
| `payload_too_large` | `bytes=<n> cap=<c>` (UTF-8 bytes of the serialized status doc) |
| `input_read_failed` | `path=<p> error=<class>: <msg>` |
| `output_write_failed` | `path=<p> stage=<open\|write\|fsync\|chmod\|rename> error=<class>: <msg>` |

## `exec-inline`

```bash
python run.py exec-inline --code 'return 42;'
python run.py exec-inline --code-file ./snippet.js
echo 'return 7;' | python run.py exec-inline --code-file -
```

- Status doc is capped at **500 UTF-8 bytes**. Oversized results produce
  `payload_too_large` — the output is never truncated. Switch to `exec`.
- Piping code via `--code-file -` is refused when stdin is a TTY
  (`kind:"input_read_failed"`, detail `RefuseTTY`).

## `exec`

```bash
python run.py exec --code-file ./snippet.js --out ./result.json
python run.py exec --code 'return bigThing();' --out ./result.json
```

- `--out` is **required**. Parent directory must exist. Writes are atomic
  (tmp file + `os.replace`); partial files never appear under the target name.
- **Hard cap: 64 KiB (65 536 B) per serialized result.** Measured in UTF-8
  bytes of the wrapper's ok status doc. Oversize results fail fast with
  `kind:"payload_too_large"` *before* chunked transport begins — no file is
  written. This is the console.log transport ceiling in Phase 1.5;
  MB-scale results need the deferred hidden-iframe transport (see *Deferred*).
- On wrapper error (user exception, serialize failure, etc.), **no file is
  written** — the status doc on stdout describes what happened.

## `read <tool>`

```bash
python run.py read ping
python run.py read document-summary --out /tmp/doc.json
python run.py read page-nodes-summary --page-id 12:4455 --out /tmp/nodes.json
python run.py read variable-collection-detail --collection-id VariableCollectionId:67:1933 --out /tmp/vars.json
python run.py read local-styles-summary --kind paint --out /tmp/styles.json
python run.py read components-summary --page-id 12:4455 --offset 0 --limit 50 --out /tmp/comps.json
```

All `read` commands share: `-f / --file`, `--timeout` (default 10 s),
`--mount-timeout` (default 30 s), `--quiet`, and optional `--out` for file mode.
Omit `--out` to get inline mode (capped at 500 B; useful only for small results like `ping`).

## Integrity

Two sha256 hashes serve distinct purposes:

- **Transport hash** (in the wrapper's BEGIN header): the bridge verifies the
  reassembled chunk bytes against this before decoding. Mismatch →
  `chunk_corrupt`. Internal; not in the user-visible status doc.
- **On-disk hash** (in `ExecOkFile.sha256`): the bridge computes this after
  writing the file. You can verify with `shasum -a 256 <result_path>`.

These differ because the on-disk file contains only `result`, not the full
wrapper envelope. Transport hash → bytes in flight; on-disk hash → bytes at rest.

## Two timeouts, on purpose

`--timeout` (default 10 s) covers only the script's execution — from Run
click through BEGIN to last chunk received. `--mount-timeout` (default 30 s)
covers Scripter frame discovery + Monaco mount only. Firefox launch and the
initial `page.goto` use Playwright's own defaults.

## `--code-file -` (stdin)

Either command accepts `--code-file -` to read JS from stdin. If stdin is a
TTY, the command refuses (no prompt) with `input_read_failed`.

## Reserved sentinel

`__FS::` is reserved. Do not emit `console.log("__FS::…")` from your own
code — it will confuse the bridge's sentinel collector.

## How it works

`run.py` drives a persistent Firefox profile under `./profile/`. Each command
opens the configured Figma file, finds the Scripter iframe, writes the script
atomically via Monaco's `model.setValue()`, and clicks the `.button.run` control.
Before clicking Run, a `page.on("console")` handler is registered on the
Playwright page; Playwright routes `console.log` calls from the Scripter iframe
to this handler. The wrapper emits a BEGIN header + N base64 chunks of the JSON
status doc via `console.log`; the bridge reassembles, verifies sha256, and for
`exec` writes just the `result` value atomically to `--out`.

## Layout

- `run.py` — CLI entry; top-level commands (`exec-inline`, `exec`, `login`, `hello`);
  re-exports sibling module symbols for backward compatibility.
- `read_handlers.py` — `read` sub-app: eight read-only Figma queries, `_dispatch_read`
  helper, all JS templates, shared pagination-slice constant.
- `transport.py` — Playwright driver: launch Firefox, mount Scripter, inject wrapper,
  collect `console.log` sentinels, reassemble chunks.
- `protocol.py` — v2 wire format: sentinel constants, cap values, Pydantic status doc
  models, chunk reassembly logic.
- `host_io.py` — host-side I/O: logging, code-source resolution (`--code` / `--code-file`
  / stdin), atomic file writes.
- `wrapper.js` — mode-agnostic JS wrapper template injected into Scripter (markers:
  `__RID__`, `__INLINE_CAP__`, `__CHUNK_B64_BYTES__`, `/*__USER_JS__*/`).
- `tests/` — unit tests (pytest): protocol models, chunk reassembly, host I/O, wrapper
  template. E2E is manual against a real Figma file.
- `pyproject.toml` — Python ≥3.10. Runtime deps: playwright, typer,
  python-dotenv, pydantic. Dev deps: pytest.
- `profile/` — Firefox user-data-dir (gitignored; holds session + Scripter).
- `.env` — `FIGMA_FILE_URL`, `PROFILE_DIR` (gitignored).

## Tests

```bash
pytest tests/ -v
```

Unit tests cover protocol models, host I/O, and chunk reassembly. The full
E2E matrix (against a real Figma file) lives in the phase 1.5 implementation
plan's verification section.

## CLI Reference

### Top-level

**`login`**
One-time setup: opens headed Firefox so you can sign in, install Scripter, and copy the file URL.
No flags.

**`hello`**
Toast smoke test — pastes `figma.notify(<message>)` and runs it.
Flags: `-m / --message` (default `"bridge alive"`), `-f / --file`, `--timeout`, `--mount-timeout`, `--quiet`.

**`exec-inline`**
Run a JS snippet; emit the result inline in the status doc (≤500 B).
Flags: `--code / -c` or `--code-file` (one required), `-f`, `--timeout`, `--mount-timeout`, `--quiet`.
Output: inline `{"status":"ok","mode":"inline","result":<any>,…}`.

**`exec`**
Run a JS snippet; write the result to a file (≤64 KiB).
Flags: `--code / -c` or `--code-file` (one required), `--out` (required), `-f`, `--timeout`, `--mount-timeout`, `--quiet`.
Output: `{"status":"ok","mode":"file","result_path":"…","bytes":<n>,"sha256":"…",…}`.

### `read` sub-app (`python run.py read …`)

All `read` commands accept `-f / --file`, `--timeout`, `--mount-timeout`, `--quiet`.
`--out` is optional unless noted; omit for inline mode (500 B cap).

**`read ping`**
Confirms the bridge is alive; returns current page name.
Flags: `--out?`. Output: `{"ping":true,"pageName":"…"}`.

**`read document-summary`**
Document name, type, page list, and current page id.
Flags: `--out?`. Output: `{"name":"…","pages":[…],"currentPageId":"…"}`.

**`read selection-info`**
Id, type, geometry, and parent of every selected node on the current page.
Flags: `--out?`. Output: array of node objects (empty array if nothing selected).

**`read page-nodes-summary`**
Top-level children of a page with id, name, type, child count, and geometry.
Flags: `--page-id?` (defaults to current page), `--out?`.
Output: `{"pageId":"…","pageName":"…","nodes":[…]}`.

**`read variable-collections-summary`**
All local variable collections: id, name, modes, variable count.
Flags: `--out?`. Output: array of collection summary objects.

**`read variable-collection-detail`**
Full expansion of one collection: all variables with values-by-mode, scopes, type.
Flags: `--collection-id` (required), `--out` (required — payload reliably exceeds 500 B).
Output: `{"id":"…","modes":[…],"variables":[…]}`.

**`read local-styles-summary`**
Local styles of one kind, paginated.
Flags: `--kind paint|text|effect|grid` (required), `--offset` (default 0), `--limit?`, `--out?`.
Output: `{"kind":"…","total":<n>,"offset":<n>,"limit":<n>,"items":[…]}`.

**`read components-summary`**
Components and component sets on a page, paginated.
Flags: `--page-id?`, `--offset` (default 0), `--limit?`, `--out?`.
Output: `{"pageId":"…","total":<n>,"offset":<n>,"limit":<n>,"items":[…]}`.

## Deferred

- **Hidden-iframe transport via `figma.showUI`** — the realistic MB-scale
  path past the 64 KiB console.log cap. Carries its own protocol bump; the
  sentinel grammar already leaves room for a second `transport` value in the
  BEGIN header.
- Retry policy keyed off the `kind` enum.
- `--code-file` glob for batch execution.
- Pagination for `page-nodes-summary` (needed only for pages with >~340 direct children).
