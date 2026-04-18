# Transport Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a diagnostic-only probe that measures the reliable `(chunks × inter-chunk-delay)` envelope of the current `figma.notify()` → MutationObserver channel, producing a CSV of sweep data and a one-page findings memo that recommends a Phase-1.5 pagination budget.

**Architecture:**
1. Thread an `inter_chunk_delay_ms` kwarg through the wrapper and `_bridge_exec`, defaulting to `0` so production behavior is unchanged.
2. Extract the Playwright session setup out of `_bridge_exec` into a reusable helper so the probe can hold one browser context open across the full sweep (~2–3 min vs. ~25 min).
3. Add `tools/transport_probe.py` — a standalone script (not wired into the typer CLI) that runs a `(bytes × delay × runs)` matrix, parses `chunk_incomplete` details for missing indexes, and writes one row per run to CSV.
4. Run the sweep live, then hand-write a one-page findings memo with the observed ceiling and a recommended pagination byte budget.

**Tech Stack:** Python 3.10+, Playwright (Firefox), Typer (already used in `run.py`), pytest, stdlib `csv` + `argparse` for the probe script (no new deps).

**Spec:** `docs/superpowers/specs/2026-04-18-transport-probe-design.md` (commit `4a824ff`).

---

## File Structure

| Path | Change | Responsibility |
|------|--------|----------------|
| `wrapper.js` | modify | Replace `setTimeout(r, 0)` with `setTimeout(r, __INTER_CHUNK_DELAY__)` marker. |
| `transport.py` | modify | (a) `_wrap_exec` accepts `inter_chunk_delay_ms`. (b) `_bridge_exec` accepts and threads it. (c) extract `_open_bridge_session` + `_run_once_in_session` helpers so the probe can reuse a single session. |
| `tests/test_wrapper_load.py` | modify | Add two assertions: marker present in template, marker substituted by `_wrap_exec`. |
| `tests/test_probe_helpers.py` | create | Unit-test probe pure-Python helpers (`parse_missing_indexes`, `compute_expected_chunks`, `build_probe_js`). No Playwright. |
| `tools/transport_probe.py` | create | Standalone sweep runner: argparse, CSV writer, session reuse, sweep matrix. |
| `probe-results.csv` | generated | Raw sweep output. Committed alongside memo. |
| `docs/superpowers/specs/2026-04-18-transport-ceiling-findings.md` | create | One-page memo written after the sweep. |

**Design rule for the refactor (Task 3):** `_bridge_exec` must keep its current external signature and behavior. Callers in `run.py` don't change. The extraction is purely internal so both `_bridge_exec` (single-shot) and the probe (long-lived session) can reuse the session-setup code.

---

### Task 1: Wire `inter_chunk_delay_ms` into the wrapper substitution

Adds a new marker to `wrapper.js` and a new parameter to `_wrap_exec`, defaulted to `0` so production behavior is identical.

**Files:**
- Modify: [wrapper.js:196](../../../wrapper.js#L196)
- Modify: [transport.py:122-131](../../../transport.py#L122-L131)
- Modify: `tests/test_wrapper_load.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wrapper_load.py`:

```python
def test_wrapper_template_has_inter_chunk_delay_marker():
    assert "__INTER_CHUNK_DELAY__" in run._WRAPPER_TEMPLATE


def test_wrap_exec_substitutes_inter_chunk_delay():
    # Default: 0 (production preserves current behavior).
    default_out = run._wrap_exec("return 1;", rid="a" * 16, inline_cap=500)
    assert "__INTER_CHUNK_DELAY__" not in default_out
    assert "setTimeout(r, 0)" in default_out

    # Explicit delay substitutes the integer.
    explicit = run._wrap_exec(
        "return 1;", rid="a" * 16, inline_cap=500,
        inter_chunk_delay_ms=250,
    )
    assert "setTimeout(r, 250)" in explicit
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `pytest tests/test_wrapper_load.py -v`
Expected: Both new tests FAIL. `test_wrapper_template_has_inter_chunk_delay_marker` fails because the marker isn't in `wrapper.js` yet; `test_wrap_exec_substitutes_inter_chunk_delay` fails with a `TypeError` about the unexpected `inter_chunk_delay_ms` kwarg.

- [ ] **Step 3: Update `wrapper.js` to use the marker**

In `wrapper.js`, line 196, replace:

```js
      await new Promise((r) => setTimeout(r, 0));
```

with:

```js
      await new Promise((r) => setTimeout(r, __INTER_CHUNK_DELAY__));
```

- [ ] **Step 4: Update `_wrap_exec` to accept and substitute the parameter**

In `transport.py`, replace the existing `_wrap_exec` (lines 122-131):

```python
def _wrap_exec(user_js: str, rid: str, inline_cap: float,
               inter_chunk_delay_ms: int = 0) -> str:
    """Substitute v2 markers. inline_cap is a UTF-8 byte cap; pass math.inf for no cap.

    inter_chunk_delay_ms controls the await between figma.notify() calls in the
    wrapper's chunked emit loop. Defaults to 0 (production behavior).
    """
    cap_token = "Infinity" if not math.isfinite(inline_cap) else str(int(inline_cap))
    return (_WRAPPER_TEMPLATE
            .replace("__RID__", rid)
            .replace("__SENTINEL_PREFIX__", SENTINEL_PREFIX)
            .replace("__SENTINEL_CLOSING__", SENTINEL_CLOSING)
            .replace("__INLINE_CAP__", cap_token)
            .replace("__CHUNK_B64_BYTES__", str(CHUNK_B64_BYTES))
            .replace("__INTER_CHUNK_DELAY__", str(int(inter_chunk_delay_ms)))
            .replace("/*__USER_JS__*/", user_js))
```

- [ ] **Step 5: Run the tests — confirm they pass**

Run: `pytest tests/test_wrapper_load.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add wrapper.js transport.py tests/test_wrapper_load.py
git commit -m "feat(transport): add inter_chunk_delay_ms param to wrapper

Default 0 preserves current production behavior. Probe script will
use this to sweep delay values without forking the wrapper."
```

---

### Task 2: Thread `inter_chunk_delay_ms` through `_bridge_exec`

`_bridge_exec` gains a kwarg defaulted to `0`. Existing callers in `run.py` are not touched — default preserves behavior.

**Files:**
- Modify: [transport.py:205-234](../../../transport.py#L205-L234)

- [ ] **Step 1: Update `_bridge_exec` signature + wrap call**

In `transport.py`, change the signature and the `_wrap_exec` call:

```python
def _bridge_exec(url: str, user_js: str, rid: str, inline_cap: float,
                 timeout_s: float, mount_timeout_s: float,
                 inter_chunk_delay_ms: int = 0) -> dict:
    """Drive Playwright + Scripter. Returns the decoded wrapper status doc."""
    wrapped_js = _wrap_exec(user_js, rid, inline_cap,
                            inter_chunk_delay_ms=inter_chunk_delay_ms)
    ...
```

Only those two lines change. The rest of the function body stays identical.

- [ ] **Step 2: Run the full existing test suite**

Run: `pytest -v`
Expected: All existing tests PASS. No Playwright tests run here — this verifies the refactor didn't break anything host-side.

- [ ] **Step 3: Commit**

```bash
git add transport.py
git commit -m "feat(transport): thread inter_chunk_delay_ms through _bridge_exec

Default 0 = unchanged production behavior; probe callers can override."
```

---

### Task 3: Extract reusable session helpers from `_bridge_exec`

Split `_bridge_exec` internals into two pieces so the probe can hold one session open across 60+ runs. `_bridge_exec` itself keeps its external behavior.

**Files:**
- Modify: [transport.py:205-234](../../../transport.py#L205-L234)
- Modify: `tests/test_wrapper_load.py` (add an import smoke test for the new names)

- [ ] **Step 1: Write the failing test for the new public names**

Append to `tests/test_wrapper_load.py`:

```python
def test_session_helpers_are_exposed():
    # These are re-exported from run for test and probe access.
    import run
    assert hasattr(run, "_open_bridge_session")
    assert hasattr(run, "_run_once_in_session")
    assert callable(run._open_bridge_session)
    assert callable(run._run_once_in_session)
```

- [ ] **Step 2: Run the test — confirm it fails**

Run: `pytest tests/test_wrapper_load.py::test_session_helpers_are_exposed -v`
Expected: FAIL with `AttributeError: module 'run' has no attribute '_open_bridge_session'`.

- [ ] **Step 3: Refactor `transport.py` — replace `_bridge_exec` with helpers + shim**

In `transport.py`, replace the existing `_bridge_exec` (lines 205-234) with:

```python
from contextlib import contextmanager


@contextmanager
def _open_bridge_session(url: str, mount_timeout_s: float):
    """Yield (page, frame) with Scripter mounted. Caller is responsible for
    installing the collector (rid-scoped) and for cleanup between runs.

    Extracted from _bridge_exec so long-lived callers (transport_probe) can
    reuse one Playwright context across many runs.
    """
    _log("info", f"launching firefox profile={PROFILE_DIR}")
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(str(PROFILE_DIR), headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            _stage("scripter_unreachable", _ensure_scripter, page)
            frame = _scripter_frame(page, timeout_s=mount_timeout_s)
            _log("info", "scripter frame ready")
            yield page, frame
        finally:
            try:
                page.evaluate(_CLEANUP_EXPR)
            except Exception:
                pass
            ctx.close()


def _run_once_in_session(page, frame, user_js: str, rid: str,
                         inline_cap: float, timeout_s: float,
                         inter_chunk_delay_ms: int = 0) -> dict:
    """One wrapper execution against an already-mounted Scripter session.

    Reinstalls the rid-scoped collector, writes the script, clicks Run,
    and returns the decoded status doc. Raises _BridgeError on transport
    failure; returns the decoded dict otherwise.
    """
    wrapped_js = _wrap_exec(user_js, rid, inline_cap,
                            inter_chunk_delay_ms=inter_chunk_delay_ms)
    _stage("injection_failed", page.evaluate, _INSTALL_COLLECTOR_JS, rid)
    _log("info", f"collector installed rid={rid}")
    _stage("injection_failed", _write_script, page, frame, wrapped_js)
    _stage("injection_failed", _run, frame)
    _log("info", f"run clicked; rid={rid} timeout={timeout_s}s")
    return _collect_and_reassemble(page, rid, timeout_s)


def _bridge_exec(url: str, user_js: str, rid: str, inline_cap: float,
                 timeout_s: float, mount_timeout_s: float,
                 inter_chunk_delay_ms: int = 0) -> dict:
    """Drive Playwright + Scripter. Returns the decoded wrapper status doc."""
    with _open_bridge_session(url, mount_timeout_s) as (page, frame):
        return _run_once_in_session(
            page, frame, user_js, rid, inline_cap,
            timeout_s=timeout_s,
            inter_chunk_delay_ms=inter_chunk_delay_ms,
        )
```

- [ ] **Step 4: Re-export the new names from `run.py`**

In `run.py`, extend the `from transport import (...)` block (around line 52) to include the two new names:

```python
from transport import (
    PROFILE_DIR,
    FIGMA_LOGIN_URL,
    _WRAPPER_TEMPLATE,
    _INSTALL_COLLECTOR_JS,
    _SNAPSHOT_EXPR,
    _CLEANUP_EXPR,
    _wrap_exec,
    _scripter_frame,
    _ensure_scripter,
    _write_script,
    _run,
    _stage,
    _bridge_exec,
    _open_bridge_session,
    _run_once_in_session,
    _collect_and_reassemble,
)
```

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: All tests PASS, including `test_session_helpers_are_exposed`.

- [ ] **Step 6: Commit**

```bash
git add transport.py run.py tests/test_wrapper_load.py
git commit -m "refactor(transport): extract _open_bridge_session + _run_once_in_session

_bridge_exec now composes the two. External signature + behavior
unchanged. Enables session reuse for the transport probe without
paying ~20s/run for a fresh browser context."
```

---

### Task 4: Scaffold `tools/transport_probe.py` with CLI + CSV writer

Pure-Python scaffolding — no Playwright yet. Sets up argparse, the CSV header, and the pure helpers the probe will use. Tested in isolation.

**Files:**
- Create: `tools/transport_probe.py`
- Create: `tests/test_probe_helpers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_probe_helpers.py`:

```python
"""Unit tests for the transport probe's pure-Python helpers."""
import sys
from pathlib import Path

# Make tools/ importable for tests.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import transport_probe as tp  # noqa: E402


def test_compute_expected_chunks_matches_wrapper_math():
    # Wrapper formula: N = max(1, ceil(b64.length / CHUNK_B64_BYTES))
    # where b64.length for a payload of B raw bytes is ceil(B/3)*4.
    # tp.compute_expected_chunks(raw_bytes) must return the same N.
    assert tp.compute_expected_chunks(0) == 1  # always at least one chunk
    assert tp.compute_expected_chunks(1) == 1
    assert tp.compute_expected_chunks(1_000) >= 1

    # A 2KB base64 chunk fits ~1536 raw bytes of payload. Two chunks by 2000B.
    n = tp.compute_expected_chunks(2_000)
    assert n >= 1

    # Sanity: more bytes => at least as many chunks.
    assert tp.compute_expected_chunks(32_000) > tp.compute_expected_chunks(1_000)


def test_build_probe_js_produces_deterministic_payload():
    js = tp.build_probe_js(100)
    assert 'return "x".repeat(100);' in js


def test_parse_missing_indexes_handles_comma_list():
    got = tp.parse_missing_indexes("got=2 expected=4 missing=1,3")
    assert got == [1, 3]


def test_parse_missing_indexes_handles_truncated_list():
    # Real detail strings use "…(+N)" when >10 missing; we keep what we can parse.
    got = tp.parse_missing_indexes(
        "got=0 expected=20 missing=0,1,2,3,4,5,6,7,8,9,…(+10)"
    )
    assert got == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_parse_missing_indexes_returns_empty_when_absent():
    assert tp.parse_missing_indexes("stage=begin elapsed_ms=5000 timeout_s=5") == []
    assert tp.parse_missing_indexes(None) == []


def test_csv_header_matches_spec():
    assert tp.CSV_HEADER == [
        "ts", "bytes", "chunks_expected", "delay_ms", "run_idx",
        "outcome", "chunks_delivered", "missing_indexes",
        "elapsed_ms", "error_detail",
    ]
```

- [ ] **Step 2: Run the tests — confirm they fail**

Run: `pytest tests/test_probe_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'transport_probe'`.

- [ ] **Step 3: Create `tools/transport_probe.py` (scaffold only)**

Create `tools/transport_probe.py`:

```python
"""Transport probe — diagnostic sweep of figma.notify() chunked-toast channel.

Not a product CLI. Run directly:
    python tools/transport_probe.py --bytes-sweep 1000,4000,16000,32000 \\
        --delay-sweep 0,25,100,250,500 --runs 3 \\
        --out probe-results.csv -f <figma-file-url>

Writes one CSV row per run. Pure sweep runner — analysis + memo are manual.
"""
import argparse
import math
import os
import re
import sys
from pathlib import Path

# Import from the parent directory so we get the transport helpers.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from protocol import CHUNK_B64_BYTES  # noqa: E402


CSV_HEADER = [
    "ts", "bytes", "chunks_expected", "delay_ms", "run_idx",
    "outcome", "chunks_delivered", "missing_indexes",
    "elapsed_ms", "error_detail",
]


def compute_expected_chunks(raw_bytes: int) -> int:
    """Mirror wrapper.js: N = max(1, ceil(b64_len / CHUNK_B64_BYTES))."""
    b64_len = math.ceil(raw_bytes / 3) * 4
    return max(1, math.ceil(b64_len / CHUNK_B64_BYTES))


def build_probe_js(raw_bytes: int) -> str:
    """Deterministic, incompressible, JSON-safe payload of exactly raw_bytes chars."""
    return f'return "x".repeat({raw_bytes});'


_MISSING_RE = re.compile(r"missing=([0-9,]+)")


def parse_missing_indexes(detail: str | None) -> list[int]:
    """Extract the numeric indexes from a `chunk_incomplete` detail string.

    Detail format: `got=X expected=Y missing=a,b,c` or `…missing=a,b,c,…(+N)`.
    Returns [] if no `missing=` clause is present.
    """
    if not detail:
        return []
    m = _MISSING_RE.search(detail)
    if not m:
        return []
    return [int(x) for x in m.group(1).split(",") if x.isdigit()]


def _parse_int_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Transport probe sweep runner.")
    p.add_argument("--bytes-sweep", default="1000,4000,16000,32000",
                   help="Comma-separated raw payload sizes in bytes.")
    p.add_argument("--delay-sweep", default="0,25,100,250,500",
                   help="Comma-separated inter-chunk delays in ms.")
    p.add_argument("--runs", type=int, default=3,
                   help="Runs per (bytes, delay) cell.")
    p.add_argument("--out", default="probe-results.csv",
                   help="CSV output path (appended, header written if new).")
    p.add_argument("-f", "--file", default=None,
                   help="Figma file URL (falls back to FIGMA_FILE_URL env var).")
    p.add_argument("--timeout", type=float, default=30.0,
                   help="Per-run wrapper timeout in seconds.")
    p.add_argument("--mount-timeout", type=float, default=30.0,
                   help="Scripter mount timeout in seconds.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    bytes_sweep = _parse_int_list(args.bytes_sweep)
    delay_sweep = _parse_int_list(args.delay_sweep)
    file_url = args.file or os.environ.get("FIGMA_FILE_URL")
    if not file_url:
        print("ERROR: pass -f <url> or set FIGMA_FILE_URL.", file=sys.stderr)
        return 2

    # Task 5 wires up the actual sweep loop against the bridge session.
    raise NotImplementedError("sweep loop — implemented in Task 5")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests — confirm they pass**

Run: `pytest tests/test_probe_helpers.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/transport_probe.py tests/test_probe_helpers.py
git commit -m "feat(probe): scaffold tools/transport_probe.py

Pure-Python helpers + argparse + CSV header. Sweep loop added in
the next commit. Unit tests cover parse_missing_indexes,
compute_expected_chunks, build_probe_js."
```

---

### Task 5: Implement the sweep loop against a reused session

Wires `tools/transport_probe.py` up to `_open_bridge_session` + `_run_once_in_session`, runs the matrix, writes CSV rows. No unit test — this is a live-only integration, validated by running it in Task 7.

**Files:**
- Modify: `tools/transport_probe.py`

- [ ] **Step 1: Replace the `NotImplementedError` body with the sweep loop**

In `tools/transport_probe.py`, replace the `NotImplementedError` line in `main` with the sweep runner, and add the two helper functions above `main`:

```python
import csv
import secrets
import time
from datetime import datetime, timezone


def _classify_outcome(raw_or_error):
    """Return (outcome, chunks_delivered, missing_indexes, error_detail).

    raw_or_error is either a decoded status doc (dict) on success, or a
    _BridgeError instance on transport failure. User-level errors in the
    status doc (status='error') are treated as 'ok' for transport purposes
    but we never expect them with the probe payload.
    """
    from protocol import _BridgeError
    if isinstance(raw_or_error, _BridgeError):
        missing = parse_missing_indexes(raw_or_error.detail)
        return raw_or_error.kind, None, missing, raw_or_error.detail
    # Success path: all chunks were delivered by definition.
    return "ok", None, [], ""


def _run_cell(page, frame, url, raw_bytes, delay_ms, run_idx,
              timeout_s, writer, csv_fh) -> None:
    """Execute one probe run and append one CSV row."""
    from protocol import _BridgeError
    rid = secrets.token_hex(8)
    user_js = build_probe_js(raw_bytes)
    expected = compute_expected_chunks(raw_bytes)
    t0 = time.monotonic()
    try:
        from transport import _run_once_in_session
        raw = _run_once_in_session(
            page, frame, user_js, rid,
            inline_cap=float("inf"),
            timeout_s=timeout_s,
            inter_chunk_delay_ms=delay_ms,
        )
        outcome, _, missing, detail = _classify_outcome(raw)
        # On success, chunks_delivered == expected; delivered count otherwise
        # is parsed from error detail (unknown for 'ok').
        delivered = expected
    except _BridgeError as e:
        outcome, _, missing, detail = _classify_outcome(e)
        delivered = expected - len(missing) if missing else None
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    writer.writerow({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": raw_bytes,
        "chunks_expected": expected,
        "delay_ms": delay_ms,
        "run_idx": run_idx,
        "outcome": outcome,
        "chunks_delivered": "" if delivered is None else delivered,
        "missing_indexes": ",".join(str(i) for i in missing),
        "elapsed_ms": elapsed_ms,
        "error_detail": detail or "",
    })
    csv_fh.flush()
    print(f"  bytes={raw_bytes:>6} delay={delay_ms:>3}ms run={run_idx} "
          f"outcome={outcome} missing={len(missing)} elapsed={elapsed_ms}ms",
          file=sys.stderr)
```

Then replace the final block of `main`:

```python
    # Open CSV (append mode; write header only if the file is new or empty).
    out_path = Path(args.out).resolve()
    is_new = not out_path.exists() or out_path.stat().st_size == 0
    csv_fh = out_path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_fh, fieldnames=CSV_HEADER)
    if is_new:
        writer.writeheader()
        csv_fh.flush()

    from transport import _open_bridge_session

    try:
        with _open_bridge_session(file_url, args.mount_timeout) as (page, frame):
            for raw_bytes in bytes_sweep:
                for delay_ms in delay_sweep:
                    for run_idx in range(args.runs):
                        _run_cell(page, frame, file_url, raw_bytes,
                                  delay_ms, run_idx, args.timeout,
                                  writer, csv_fh)
    finally:
        csv_fh.close()

    print(f"done; wrote to {out_path}", file=sys.stderr)
    return 0
```

- [ ] **Step 2: Smoke-test the sweep runs without crashing (single tiny cell)**

Run (requires `FIGMA_FILE_URL` set and `profile/` already authed):

```bash
python tools/transport_probe.py \
  --bytes-sweep 1000 --delay-sweep 0 --runs 1 \
  --out /tmp/probe-smoke.csv
```

Expected: the probe launches the browser, mounts Scripter, runs once, writes a single row to `/tmp/probe-smoke.csv`, and exits 0. Print the file with `cat /tmp/probe-smoke.csv` — it should have the header plus one row with `outcome=ok`.

If `outcome` isn't `ok` for this tiny cell: that's itself a finding — record it and proceed; the channel is worse than we thought. Do not "fix" it in this task.

- [ ] **Step 3: Commit**

```bash
git add tools/transport_probe.py
git commit -m "feat(probe): implement session-reused sweep loop

Wires transport_probe against _open_bridge_session +
_run_once_in_session. One CSV row per run; flushes after each."
```

---

### Task 6: Run the sweep and commit the raw CSV

Execute the full matrix from the spec, commit the CSV as-is. No code changes.

**Files:**
- Create: `probe-results.csv` (generated)

- [ ] **Step 1: Run the full sweep**

Run:

```bash
python tools/transport_probe.py \
  --bytes-sweep 1000,4000,16000,32000 \
  --delay-sweep 0,25,100,250,500 \
  --runs 3 \
  --out probe-results.csv
```

Expected: 4 × 5 × 3 = 60 rows written. Wall clock ~2–3 min for the whole sweep (session is reused). Stderr shows per-run progress. If the sweep crashes mid-run, the CSV still contains all rows written up to that point — fix the crash and re-run; truncate the CSV first if you want a clean matrix.

- [ ] **Step 2: Sanity-check the output**

Run: `wc -l probe-results.csv` — expect 61 (header + 60).
Run: `head -5 probe-results.csv` — verify header + first few rows look well-formed.

- [ ] **Step 3: Commit the raw data**

```bash
git add probe-results.csv
git commit -m "data(probe): raw sweep results (4 bytes × 5 delays × 3 runs)

60 rows covering 1000..32000 bytes at 0..500ms inter-chunk delay.
Memo with analysis + recommendation lands next commit."
```

---

### Task 7: Write the findings memo

Analyze `probe-results.csv` by eye (or with a one-liner), then write the one-page memo the spec calls for. No code.

**Files:**
- Create: `docs/superpowers/specs/2026-04-18-transport-ceiling-findings.md`

- [ ] **Step 1: Build the success-rate grid**

From the CSV, compute per-cell success rate: `runs_ok / 3`. A quick Python one-liner works:

```bash
python -c "
import csv, collections
g = collections.defaultdict(lambda: [0, 0])
with open('probe-results.csv') as f:
    for row in csv.DictReader(f):
        key = (int(row['bytes']), int(row['delay_ms']))
        g[key][1] += 1
        if row['outcome'] == 'ok':
            g[key][0] += 1
for (b, d), (ok, tot) in sorted(g.items()):
    print(f'bytes={b:>5} delay={d:>3} {ok}/{tot}')
"
```

- [ ] **Step 2: Identify the loss pattern**

Inspect the `missing_indexes` column across all failing rows. Look for:
- **Tail clustering** (largest indexes missing) → toast auto-dismiss of older toasts.
- **Head clustering** (indexes 0, 1 missing) → observer-install race.
- **Random scatter** → rate limiting or observer lag.

Quote one representative row in the memo.

- [ ] **Step 3: Write the memo**

Create `docs/superpowers/specs/2026-04-18-transport-ceiling-findings.md`:

```markdown
# Transport Ceiling Findings — Phase 1.5

**Date:** 2026-04-18
**Probe spec:** docs/superpowers/specs/2026-04-18-transport-probe-design.md
**Raw data:** probe-results.csv (4 bytes × 5 delays × 3 runs)

## Sweep table

| bytes \ delay_ms | 0 | 25 | 100 | 250 | 500 |
|------------------|---|----|-----|-----|-----|
| 1_000            | <ok/total> | … | … | … | … |
| 4_000            | … | … | … | … | … |
| 16_000           | … | … | … | … | … |
| 32_000           | … | … | … | … | … |

## Reliable envelope

<State the largest cell where all 3 runs succeeded, and the nearest failing
cell. E.g. "≤ N chunks at ≥ D ms is reliable; above that drops appear.">

## Loss pattern

<Tail / head / random. Quote one representative row from probe-results.csv,
e.g. `bytes=16000 delay=0 run=1 missing=14,15,16,17,18,19` → tail-clustered,
consistent with Figma auto-dismissing older toasts as newer ones arrive.>

## Recommendation

<One paragraph. Give a concrete byte budget per page for Phase-1.5 pagination
with ~30–50% safety margin below the observed ceiling. State the implied
chunk count and inter-chunk delay.>

## Scope caveat

This ceiling is a property of `figma.notify()` + MutationObserver. A channel
swap (e.g. rotating `document.title`, a hidden DOM node under Scripter, or
broadcastChannel) would lift it meaningfully. Not proposed here.
```

Fill each `<…>` placeholder with actual data from the sweep — do not commit a memo with placeholder text.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-18-transport-ceiling-findings.md
git commit -m "docs(findings): transport probe ceiling + pagination recommendation

Phase-1.5 reliable envelope and recommended byte budget per page,
based on 60-run sweep. Channel swap flagged as a future lift,
out of scope for this pass."
```

---

## Self-review checklist (already applied)

- **Spec coverage:** Every section of the design spec maps to a task. Wrapper marker (Task 1), param threading (Task 2), session reuse refactor (Task 3), scaffold + helpers (Task 4), sweep loop (Task 5), raw data (Task 6), memo (Task 7).
- **No placeholders:** Every step has concrete file paths, concrete code, concrete commands with expected output. The memo template in Task 7 has `<…>` placeholders but Step 3 explicitly requires filling them before commit.
- **Type consistency:** `_open_bridge_session` and `_run_once_in_session` are used with the same signatures in Task 3 definition, Task 4 scaffold (via re-export test), and Task 5 call sites. `inter_chunk_delay_ms` is spelled the same in wrapper, `_wrap_exec`, `_bridge_exec`, `_run_once_in_session`, and probe calls.
- **Prod safety:** Tasks 1–3 all preserve `_bridge_exec`'s external signature and default behavior (`inter_chunk_delay_ms=0`). No `run.py` command changes. No `protocol.py` changes.
