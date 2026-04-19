# Phase 1.5 — `exec` subcommand & protocol v2

**Date:** 2026-04-18
**Status:** Approved (spec). Ready for implementation plan.
**Supersedes (where it overlaps):** Phase 1 plan at `~/.claude/plans/yes-please-recursive-treasure.md`. Carries forward the protocol shape, exit-code semantics, sentinel mechanism, and `_scripter_frame` / `_write_script` / `_run` helpers from Phase 0/1; bumps the protocol to v2 as documented below.

## Context

Phase 1 shipped `exec-inline` with a 500-byte payload cap. The cap exists because Figma's toast UI (the only realistic exfiltration channel from the plugin sandbox) truncates around the visible threshold and the wire format embeds the result inline in a single sentinel toast. That works for IDs, counts, and short summaries; it doesn't work for variable exports, page-snapshot dumps, or component inventories.

This spec adds a second subcommand, `exec`, that lifts the cap to ~5 MB by chunking the payload across many sentinel toasts and writing the assembled result to a host-side file. It bumps the protocol to **v2** to add four new error kinds, a `request_id` for correlation, and a discriminated-union status doc.

The design path is grow-friendly: the sentinel grammar leaves room for a future high-throughput channel (e.g., `figma.showUI` hidden iframe) without breaking the protocol.

## Goals

- New `exec` subcommand, file-based output via `--out <path>`.
- `--code-file <path>` (and `--code-file -` for stdin) on both `exec` and `exec-inline`.
- Protocol v2: `request_id`, discriminated `ExecOk*` shapes, four new error kinds, sha256 integrity check.
- Initial payload target: ~5 MB. No hard host-side cap.
- Backward-incompatible at the version field, but no live consumers exist outside this codebase.

## Non-goals

- No second injection / `clientStorage`-backed transport (its quota doesn't actually scale past ~5 MB; no win).
- No `figma.showUI` iframe channel in this phase (left as a grow path for a future phase).
- No module split into `src/figma_service/{bridge,scripter,protocol,session}.py` (deferred — too much surface to combine with v2 in one phase).
- No retries (the kind enum already separates retryable from non-retryable cases for a future phase).
- No streaming / unbounded output (everything fits in memory once before file write).

## CLI surface

```
python run.py exec-inline --code 'return 42;'
python run.py exec-inline --code-file ./snippet.js
python run.py exec-inline --code-file -                  # reads from stdin
python run.py exec       --code-file ./snippet.js --out ./result.json
python run.py exec       --code-file -            --out ./result.json
python run.py exec       --code 'return bigThing();' --out ./result.json
```

### `exec-inline` (existing, lightly extended)

- Adds `--code-file <path>` as a mutually-exclusive alternative to `--code`. Exactly one required. `-` means stdin.
- **Hard guarantee:** if `TextEncoder.encode(JSON.stringify(statusDoc)).byteLength` exceeds the 500 B cap, the command fails with `status:"error", kind:"payload_too_large"`, exit 1. **Output is never truncated.** Users who hit this switch to `exec`.

### `exec` (new)

- Mutually-exclusive `--code <inline>` / `--code-file <path>`; `-` means stdin. Exactly one required.
- **Required** `--out <path>`. Writes result as UTF-8 JSON, mode `0o600`. Parent directory must exist.
- Atomic replace: write to `.<name>.<pid>.tmp` in the same directory, then `os.replace`. Partial files never appear under the target name.
- stdout emits the status doc (Protocol section) — both on success and on failure. **Never the result itself.**
- Same `--timeout` (default 10 s) and `--mount-timeout` (default 30 s) as `exec-inline`.
- Target payload ceiling: ~5 MB. No hard cap enforced host-side; transport latency scales linearly above that.

### Shared I/O rules

- `--code-file` reads as UTF-8. Failures (missing, permission, decode) → `input_read_failed`, exit 1. Status doc emitted to stdout.
- `--out` write failures (parent missing, unwritable, disk full, atomic-rename failure) → `output_write_failed`, exit 1.
- `--code-file -` with `sys.stdin.isatty() == True` → fail fast with `input_read_failed`, detail `"path=- error=RefuseTTY: refusing to read code from interactive TTY; pipe input or use --code"`.
- Same exit semantics (0 on `ok`, 1 on any `error`), same `--quiet`, same `-f/--file` for Figma URL override.
- Missing-required (neither `--code` nor `--code-file`) is handled by Typer (exit 2), not the JSON protocol.

## Protocol v2

`PROTOCOL_VERSION = 2`. All sentinels and status docs carry `request_id`: a 16-char hex nonce generated host-side per invocation (`secrets.token_hex(8)`) and threaded into the wrapper via template substitution. The bridge filters every observed sentinel by `request_id`; sentinels from prior runs are discarded.

**Byte counts.** Every byte measurement (the 500 B cap on `exec-inline`, the `bytes` field in BEGIN, payload-size comparisons) is a UTF-8 byte count. Wrapper uses `new TextEncoder().encode(payload).byteLength`, never `.length` (which counts UTF-16 code units and undercounts multi-byte characters).

### Status doc — discriminated union on `mode`

```python
class ExecOkInline(BaseModel):
    status:     Literal["ok"]     = "ok"
    mode:       Literal["inline"] = "inline"
    version:    int = 2
    request_id: str
    result:     Any                # required; the decoded JSON value
    elapsed_ms: int
    logs:       list[str] = Field(default_factory=list)  # reserved for a future phase

class ExecOkFile(BaseModel):
    status:      Literal["ok"]   = "ok"
    mode:        Literal["file"] = "file"
    version:     int = 2
    request_id:  str
    result_path: str               # required
    bytes:       int               # required; UTF-8 bytes of the on-disk file
    sha256:      str               # required; hex digest of the on-disk file
    elapsed_ms:  int
    logs:        list[str] = Field(default_factory=list)  # reserved for a future phase

ExecOk = Annotated[Union[ExecOkInline, ExecOkFile], Field(discriminator="mode")]

class ExecErr(BaseModel):
    status:     Literal["error"] = "error"
    version:    int = 2
    request_id: str | None = None  # None if failure happened before wrapper attached an id
    kind:       Literal[
        # Carried from v1:
        "user_exception", "payload_too_large", "serialize_failed",
        "timeout", "injection_failed", "scripter_unreachable",
        # New in v2:
        "chunk_incomplete", "chunk_corrupt",
        "input_read_failed", "output_write_failed",
    ]
    message:    str
    detail:     str | None = None
    elapsed_ms: int | None = None
```

**Invariants** (enforced by the discriminated union):
- `ExecOkInline`: `result` required; no `result_path/bytes/sha256` field exists.
- `ExecOkFile`: `result_path/bytes/sha256` all required; no `result` field exists.

### Standardized `detail` schemas

Key=value, space-separated, stable per kind:

| kind | detail schema |
|---|---|
| `timeout` | `stage=<begin\|chunk_stream> elapsed_ms=<m> timeout_s=<t>` |
| `chunk_incomplete` | `got=<n> expected=<N> missing=<i,j,k,…> elapsed_ms=<m>` |
| `chunk_corrupt` | `stage=<b64_decode\|length_mismatch\|sha256_mismatch\|json_parse> bytes_got=<n> bytes_want=<N> sha256_got=<hex> sha256_want=<hex>` (only fields relevant to the stage are emitted) |
| `input_read_failed` | `path=<p> error=<exception_class>: <msg>` |
| `output_write_failed` | `path=<p> stage=<open\|write\|fsync\|chmod\|rename> error=<exception_class>: <msg>` |

Other kinds keep free-form `detail` (for `user_exception` it's the JS stack; for `injection_failed` / `scripter_unreachable` it's a traceback / context dump).

### Sentinel grammar — unified for both commands

```
__FS::<rid>:BEGIN:{"version":2,"chunks":N,"bytes":B,"sha256":"<hex>","transport":"chunked_toast"}::SF__
__FS::<rid>:C:0:<base64>::SF__
__FS::<rid>:C:1:<base64>::SF__
…
__FS::<rid>:C:N-1:<base64>::SF__
```

- `BEGIN` header is plain JSON (can't contain `::SF__`, fits in <200 B).
- Each `C:<i>:<base64>` carries base64-encoded raw-JSON bytes. Base64 protects against `::SF__` appearing in user strings. `i` is decimal, 0-indexed.
- Initial base64 chunk size: **2 KB per toast** (≈1.5 KB raw JSON). Implementation verifies the real notify ceiling on a cold session and locks the value.
- Both `exec-inline` and `exec` use this grammar. For tiny `exec-inline` payloads, N is typically 1 (BEGIN + 1 chunk). The cost of one extra toast for inline calls is negligible; one parser in the bridge.

## Wrapper JS

The wrapper is **mode-agnostic**. It never knows whether it's running under `exec-inline` or `exec`. It emits the same raw status payload. Only difference at wrap time is the `INLINE_CAP` value substituted into the template (500 for `exec-inline`, `Infinity` for `exec`).

### Wire payload from wrapper — no `mode`, no `result_path`

```json
{"status":"ok","version":2,"request_id":"<rid>","result":<value>,"elapsed_ms":<n>}
{"status":"error","version":2,"request_id":"<rid>","kind":"…","message":"…","detail":"…","elapsed_ms":<n>}
```

On `exec-inline`, host validates the raw payload directly into `ExecOkInline` — Pydantic's default `mode="inline"` fills the discriminator without explicit injection. On `exec`, host extracts the `result` value from the validated payload, JSON-encodes it canonically (see "What `--out` contains" below), writes that to `--out`, computes sha256 of the on-disk bytes, and builds `ExecOkFile` — discarding the rest of the wrapper's status envelope.

### Emission pipeline inside the wrapper

1. Serialize: `const json = JSON.stringify(statusDoc)`.
2. Measure bytes: `const bytes = new TextEncoder().encode(json)` → `bytes.byteLength`.
3. **Cap check (exec-inline only).** If `bytes.byteLength > INLINE_CAP` and `status === "ok"`, replace the payload with an `ExecErr(kind:"payload_too_large", message:"result <n>B exceeds cap <cap>B")` and continue with that. The cap applies to the full serialized status doc, matching v1 semantics.
4. Compute sha256: `await crypto.subtle.digest("SHA-256", bytes)` → hex digest.
5. Base64-encode the raw JSON bytes via chunk-wise `btoa(String.fromCharCode.apply(null, bytes.subarray(i, i+0x8000)))` (avoids stack overflow on large arrays). `Buffer` is not assumed.
6. Split the base64 string into 2 KB segments.
7. Emit `figma.notify(__FS::<rid>:BEGIN:<header_json>::SF__)`.
8. For `i in 0..N-1`: `figma.notify(__FS::<rid>:C:<i>:<segment>::SF__)`.

### Wrapper-side error paths

- `JSON.stringify` throws (cycle, BigInt) → caught, re-emit as `serialize_failed`.
- User code throws → `user_exception` with `e.stack.slice(0,2000)` in `detail`.
- `crypto.subtle.digest` missing or throws → `injection_failed` with detail naming the missing API. Bridge re-surfaces.
- The wrapper emits exactly one logical response (BEGIN + N chunks) per run, even when that response is an error.

## Bridge reassembly

### The dismissal-race problem

Figma toasts auto-dismiss after ~6 s by default. A 5 MB payload (≈2,500 chunks at 2 KB) emits over 25+ s — earlier toasts vanish from the DOM before later ones arrive. Polling `document.body.textContent` for "all N chunks present at once" is a losing race.

### Collector pattern (the fix)

Before executing the wrapper, Playwright runs an installer (`page.evaluate(INSTALL_COLLECTOR_JS, rid)`) on the main Figma page that:

- Installs a `MutationObserver` on `document.body` watching for added subtrees whose text contains `__FS::<rid>:`.
- On every match, extracts the `textContent` and pushes it into `window.__FS_collected`, deduplicated by full sentinel text.
- Exposes `window.__FS_snapshot()` returning `[...window.__FS_collected]`.
- Filters by `rid` at observer level — sentinels from any prior run are ignored.

Because toasts are DOM nodes when they appear, the observer catches them synchronously at insert time, before Figma's dismiss timer kicks in. Once observed, the text lives in the JS array regardless of subsequent toast removal.

### Reassembly flow

```
1. page.evaluate(INSTALL_COLLECTOR_JS, rid)
2. _write_script + _run             # from Phase 0/1, unchanged
3. phase A — wait for BEGIN
     poll every 100 ms: snapshot = page.evaluate("__FS_snapshot()")
     scan for "__FS::<rid>:BEGIN:" sentinel
     parse header JSON: extract chunks=N, bytes=B, sha256
     deadline: --timeout
     on phase-A timeout → ExecErr(kind="timeout",
         detail="stage=begin elapsed_ms=<m> timeout_s=<t>")
4. phase B — wait for chunks
     poll every 100 ms: snapshot = page.evaluate("__FS_snapshot()")
     extract sentinels matching "__FS::<rid>:C:<i>:" → indices into a set
     deadline: remaining --timeout budget after phase A
     on phase-B timeout → ExecErr(kind="chunk_incomplete",
         detail="got=<n> expected=<N> missing=<i,j,k,…> elapsed_ms=<m>")
5. reassemble:
     for i in 0..N-1: extract base64 for chunk i, concatenate
     base64-decode → raw bytes; on error: chunk_corrupt stage=b64_decode
     verify len(bytes) == header.bytes; on mismatch: stage=length_mismatch
     verify hashlib.sha256(bytes).hexdigest() == header.sha256;
                                                 stage=sha256_mismatch
     json.loads(bytes.decode("utf-8")); on failure: stage=json_parse
6. map decoded payload:
     status=="error" → ExecErr(..., request_id=rid)
     status=="ok" + exec-inline → ExecOkInline(result=..., mode="inline")
     status=="ok" + exec → extract result, json.dumps(result, indent=2,
                                                ensure_ascii=False) + "\n",
                            write resulting bytes to --out atomically,
                            compute hashlib.sha256 of the on-disk bytes,
                            return ExecOkFile(result_path=..., mode="file",
                                              bytes=<file size>, sha256=<file digest>)
7. page.evaluate("__FS_cleanup()")  # tidy; ctx.close() would kill the page anyway
```

### Stage-bounded timeout semantics

`--timeout` is the total exec budget. Phase A consumes some; phase B gets the remainder. If phase A times out, phase B isn't entered. Total wall-clock from "Run clicked" to "all chunks received or bridge gives up" ≤ `--timeout`.

## Host-side I/O

### Input — `--code-file`

- Path `-` → `sys.stdin.read()`. If `sys.stdin.isatty()` → `input_read_failed("path=- error=RefuseTTY: refusing to read code from interactive TTY; pipe input or use --code")`.
- Path `<file>` → `Path(p).read_text(encoding="utf-8")`. `FileNotFoundError`, `PermissionError`, `IsADirectoryError`, `UnicodeDecodeError` → `input_read_failed`, `detail="path=<p> error=<class>: <msg>"`.
- Mutual exclusion handled by Typer's mutually-exclusive group.

### Output — `--out` (exec only)

- Path resolved via `Path(out).resolve()`; parent must exist.
- Atomic write sequence:
  ```python
  tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
  with open(tmp, "wb") as f:
      f.write(payload_bytes)
      f.flush()
      os.fsync(f.fileno())
  os.chmod(tmp, 0o600)
  os.replace(tmp, path)        # atomic on POSIX
  ```
- Each stage labeled in `detail`: `stage=<open|write|fsync|chmod|rename>`.
- Tmp file lives in the same directory as the target so `os.replace` is a true atomic rename.

### Request-ID

- `request_id = secrets.token_hex(8)` at the top of `_bridge_exec`. Substituted into wrapper template as `__RID__`. Passed to collector installer. Echoed in every status doc.

### What `--out` contains

The on-disk file holds **only the user's `result` value**, not the wrapper's status envelope (the envelope's metadata — `status`, `version`, `elapsed_ms`, etc. — is on stdout in the status doc instead).

Bridge encoding of the on-disk file:

```python
encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
payload_bytes = encoded.encode("utf-8")
```

`indent=2` for human readability; `ensure_ascii=False` so non-ASCII strings round-trip without `\uXXXX` escaping; `sort_keys=False` preserves the user's intended ordering; trailing newline is the POSIX text-file convention.

### sha256 — two hashes, by design

Two separate hashes serve distinct purposes:

| Hash | Computed by | Over | Purpose | User-visible? |
|---|---|---|---|---|
| `header.sha256` (in BEGIN) | wrapper, in JS | wire-payload bytes | transport integrity (catch `chunk_corrupt`) | no — internal |
| `ExecOkFile.sha256` | bridge, in Python | on-disk file bytes | artifact integrity (catch storage corruption) | yes — in status doc |

These don't match because the on-disk file contains only `result`, not the full wrapper envelope. The transport hash protects bytes in flight; the on-disk hash protects bytes at rest. The chain is:

```
wrapper bytes  ──[chunked toasts]──▶  reassembled bytes
                                              │
                                  verify against header.sha256
                                              │
                                          json.loads
                                              │
                                       extract result
                                              │
                                json.dumps(result, indent=2, …)
                                              │
                                     atomic write to --out
                                              │
                                hashlib.sha256(file bytes)
                                              │
                                     ExecOkFile.sha256
```

## Code organization & files touched

The wrapper template moves out of `run.py` into a sibling `wrapper.js`. No further module split this phase (the full reorg into `src/figma_service/{bridge,scripter,protocol,session}.py` is deferred — Phase 1.5 already adds significant new surface; piling a refactor on top makes the diff harder to review and verification slower).

- **`run.py`** — main changes: `exec` subcommand, `--code-file` on both, v2 Pydantic models (discriminated union), `request_id` plumbing, collector install + snapshot calls, chunk reassembly + sha256 verification, atomic file write, new error kinds. Estimated ~545 lines.
- **`wrapper.js`** *(new)* — the JS wrapper template with `__RID__` / `__INLINE_CAP__` / `__USER_JS__` markers. Loaded once at import time via `Path(__file__).parent / "wrapper.js"`.
- **`pyproject.toml`** — no new deps. `secrets`, `hashlib`, `base64` are stdlib; Pydantic and Playwright are already present.
- **`README.md`** — document the `exec` subcommand, v2 protocol shape (new kinds + `request_id`), atomic-write guarantee, the sha256/bytes integrity fields, and the `--code-file -` stdin convention.

## Open implementation risks (resolve at plan/build time)

1. **Notify coalescing.** Emitting many toasts in a tight synchronous loop may cause Figma's UI to batch or drop later ones. Mitigation candidate: `await new Promise(r => setTimeout(r, 0))` between emissions if testing shows drops. Implementation probes this on first real run.
2. **Toast DOM-text ceiling.** Phase 1 used 500 B because visible truncation starts ~100 chars; the underlying DOM `textContent` may hold more. The 2 KB-per-chunk figure is a first guess — implementation verifies the actual ceiling on a cold Figma session and locks it before declaring the chunk size.
3. **`crypto.subtle.digest` availability.** Web standard, present in Figma's plugin sandbox in practice but not confirmed there. If absent, fall back to a 12-line SHA-256 JS impl inlined into the wrapper.
4. **MutationObserver coverage.** Toasts may be added inside a Shadow DOM root or under a portal that's not in `document.body`. If so, the observer needs to attach deeper or watch document-wide. Probe early.
5. **Cold-start total time.** A 5 MB payload at 2 KB/chunk × ~10 ms emit interval ≈ 25 s emit time on top of mount. Acceptable for occasional dumps; document this in the README so users aren't surprised.

## Verification (sketch — full matrix in the implementation plan)

Manual, from the Figma_Service project root, against a real Figma file via `.env`:

1. **Phase 1 happy path unchanged.** `python run.py exec-inline --code 'return 42;'` still prints `{"status":"ok","mode":"inline","version":2,"request_id":"<rid>","result":42,"elapsed_ms":<n>,"logs":[]}`, exit 0. (Note v2 shape — `request_id`, `mode`, and reserved `logs` now present.)
2. **`exec-inline` from file.** `echo 'return 7;' > /tmp/s.js && python run.py exec-inline --code-file /tmp/s.js` → `result:7`, exit 0.
3. **`exec-inline` from stdin.** `echo 'return 7;' | python run.py exec-inline --code-file -` → `result:7`, exit 0.
4. **`exec-inline` TTY refusal.** `python run.py exec-inline --code-file -` (interactive) → `kind:"input_read_failed"`, exit 1.
5. **`exec` happy path, small.** `python run.py exec --code 'return {a:1,b:2};' --out /tmp/r.json` → status doc with `mode:"file"`, `result_path:/tmp/r.json`, `bytes:>0`, `sha256:<hex>`. File on disk parses as JSON, contents match.
6. **`exec` happy path, ~1 MB.** `python run.py exec --code 'return "x".repeat(1_000_000);' --out /tmp/big.json --timeout 60` → bytes ≈ 1_000_010, sha256 matches, file parses. Acceptable wall-clock (<60 s).
7. **`exec` user exception.** `python run.py exec --code 'throw new Error("boom");' --out /tmp/r.json` → `kind:"user_exception"`, exit 1. **No file written at /tmp/r.json** (or pre-existing file unchanged — atomic guarantee).
8. **`exec` output write failure.** `python run.py exec --code 'return 1;' --out /nonexistent/dir/r.json` → `kind:"output_write_failed"`, `detail` mentions parent-missing, exit 1.
9. **Hash integrity.** Verify `sha256` in status doc matches `shasum -a 256 /tmp/r.json` for at least one `exec` run.
10. **Cross-run isolation.** Run two `exec-inline` calls back-to-back without closing Figma; second run's `request_id` differs and its status doc references only its own chunks. No stale-toast contamination.

The implementation plan owns the full cross-product (each error kind × each subcommand) and the line-count target.

## Follow-ups (out of scope for Phase 1.5)

- Module split into `src/figma_service/{bridge,scripter,protocol,session,host_io,wrapper}.py`.
- High-throughput transport via `figma.showUI` hidden iframe (the realistic grow path past ~5 MB).
- Console.log capture in the wrapper, populating an `ExecOk.logs: list[str]` field.
- `--code-file` glob support for batch execution (would require multi-result aggregation; out of v2's scope).
- Retry policy keyed off the kind enum (retryable: `scripter_unreachable`, `injection_failed`, `timeout`, `chunk_incomplete`, `chunk_corrupt`; non-retryable: the rest).
- Stderr diagnostics upgrade from timestamped lines to JSONL.
