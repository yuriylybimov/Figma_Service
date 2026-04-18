# Figma_Service

Bridge: Claude writes a Figma Plugin API script, `run.py` pastes it into
the Scripter community plugin via a headless-ish Firefox, Scripter executes it.

Four commands: `login` (one-time), `hello` (toast smoke test),
`exec-inline` (run JS, return value inline, ≤500 B status doc), and
`exec` (run JS, write result to file, no practical size cap).

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
- Target payload ceiling: ~5 MB (document-level; not enforced host-side).
  Transport scales linearly; a 5 MB dump takes ~25 s of wire time plus mount.
- On wrapper error (user exception, serialize failure, etc.), **no file is
  written** — the status doc on stdout describes what happened.

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

`__FS::` is reserved. Do not emit `figma.notify("__FS::…")` from your own
code — it will confuse the bridge's MutationObserver collector.

## How it works

`run.py` drives a persistent Firefox profile under `./profile/`. Each command
opens the configured Figma file, finds the Scripter iframe, writes the script
atomically via Monaco's `model.setValue()`, and clicks the `.button.run` control.
Before clicking Run, a `MutationObserver` is installed on the Figma page that
captures every `__FS::<rid>:…::SF__` toast at DOM-insert time (so Figma's ~6 s
auto-dismiss doesn't race us). The wrapper emits a BEGIN header + N base64
chunks of the JSON status doc; the bridge reassembles, verifies sha256, and for
`exec` writes just the `result` value atomically to `--out`.

## Layout

- `run.py` — CLI entry, v2 protocol models, bridge, commands.
- `wrapper.js` — mode-agnostic JS wrapper template (markers: `__RID__`,
  `__INLINE_CAP__`, `__SENTINEL_PREFIX__`, `__SENTINEL_CLOSING__`,
  `__CHUNK_B64_BYTES__`, `/*__USER_JS__*/`).
- `tests/` — host-side unit tests (pytest). E2E is manual against a real Figma file.
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

## Deferred

Module split into `src/figma_service/{bridge,scripter,protocol,session,host_io,wrapper}.py`,
high-throughput transport via `figma.showUI` hidden iframe, retry policy
keyed off the kind enum, console.log capture in the wrapper, `--code-file`
glob for batch execution.
