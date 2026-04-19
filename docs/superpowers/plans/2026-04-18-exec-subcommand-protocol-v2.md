# Phase 1.5 — `exec` Subcommand & Protocol v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `exec` subcommand that writes arbitrary-size results atomically to a file via chunked toast transport, bumping the status-doc protocol to v2 with `request_id`, discriminated union `ExecOk`, and four new error kinds.

**Architecture:** The wrapper JS moves from a Python string literal into a sibling `wrapper.js` template. A MutationObserver-based collector installed on the Figma page captures every `__FS::<rid>:…::SF__` sentinel toast synchronously at DOM-insert time, surviving Figma's ~6 s auto-dismiss. The wrapper emits a BEGIN header + N base64 chunks of the serialized status doc; the bridge reassembles, verifies sha256, decodes JSON, and for `exec` writes just the `result` value atomically to `--out` with a second on-disk sha256.

**Tech Stack:** Python 3.10+, Typer, Pydantic v2 (discriminated unions), Playwright (Firefox, persistent context), `secrets.token_hex`, `hashlib.sha256`, `base64`, `os.replace`. JS wrapper uses `TextEncoder`, `crypto.subtle.digest`, `figma.notify`. Tests: pytest (unit-testable host-side logic only — E2E is manual against a real Figma file per the spec's verification section).

---

## Scope boundary

This plan implements the full spec at `docs/superpowers/specs/2026-04-18-exec-subcommand-protocol-v2-design.md`. Non-goals listed there are **not** implemented: no module split into `src/figma_service/`, no second transport, no retries, no streaming, no `showUI` iframe.

## File Structure

- **`run.py`** (modify heavily, target ~545 lines): new v2 Pydantic models, `request_id` plumbing, `exec` command, `--code-file` on both commands, collector install, chunked reassembly, atomic file write, wrapper loaded from sibling file.
- **`wrapper.js`** *(new)*: JS wrapper template with `__RID__`, `__INLINE_CAP__`, `__USER_JS__` markers. Loaded once at import time via `Path(__file__).parent / "wrapper.js"`.
- **`tests/`** *(new)*: pytest unit tests for host-side logic (Pydantic models, file I/O, reassembly helpers, sentinel parsing). E2E remains manual per spec.
- **`tests/test_protocol.py`** *(new)*: v2 Pydantic model invariants (discriminator fills, required fields, error-kind literal).
- **`tests/test_host_io.py`** *(new)*: `_read_code_source` (path/stdin/TTY-refusal), `_atomic_write` (success, parent-missing, cleanup of .tmp).
- **`tests/test_reassembly.py`** *(new)*: `_reassemble_chunks` pure function — parses BEGIN header, concatenates base64 chunks, verifies length + sha256, json-decodes, detects each `chunk_corrupt` stage.
- **`tests/conftest.py`** *(new)*: shared fixtures (tmp path factory already in pytest; project-level path helpers).
- **`pyproject.toml`** (modify): add `pytest>=8` to a `[project.optional-dependencies].dev` group. No new runtime deps (everything else is stdlib).
- **`README.md`** (modify): document `exec`, v2 shape (`request_id`, `mode`, `logs`, new error kinds), atomic-write guarantee, sha256/bytes fields, `--code-file -` stdin convention, `exec-inline` behavior change (still 500 B cap, but v2 response shape).

### Code organization inside `run.py`

Keep the single-file layout this phase. Top-to-bottom ordering:

1. Imports, `load_dotenv`, `app` creation, constants (`PROTOCOL_VERSION = 2`, `SENTINEL_PREFIX = "__FS::"`, `SENTINEL_CLOSING = "::SF__"`, `INLINE_CAP_BYTES = 500`, `CHUNK_B64_BYTES = 2048`).
2. Pydantic models: `ExecOkInline`, `ExecOkFile`, `ExecOk` (discriminated union), `ExecErr`, `_BridgeError`.
3. Logging helpers: `_log`, `_trim`, `_emit_exit`.
4. Scripter helpers (unchanged from v1): `_scripter_frame`, `_ensure_scripter`, `_write_script`, `_run`.
5. Wrapper loader: `_WRAPPER_TEMPLATE = (Path(__file__).parent / "wrapper.js").read_text(encoding="utf-8")`; `_wrap_exec(user_js, rid, inline_cap)`.
6. Collector JS string constant: `_COLLECTOR_JS` (install) and `_SNAPSHOT_EXPR` / `_CLEANUP_EXPR` (read/tidy).
7. Host I/O helpers: `_read_code_source`, `_atomic_write`.
8. Reassembly: `_reassemble_chunks` (pure, testable).
9. Bridge: `_bridge_exec` (Playwright session + phase A/B polling + reassembly call).
10. Commands: `exec_inline`, `exec`, `login`, `hello`.

---

## Task 0: Project baseline — init git, add pytest, create tests skeleton

**Files:**
- Create: `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/__init__.py`
- Create: `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/conftest.py`
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/pyproject.toml`
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/.gitignore`

- [ ] **Step 1: Initialize git if not already initialized**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
git status 2>/dev/null || git init -b main
```

Expected: either shows working tree, or prints `Initialized empty Git repository`.

- [ ] **Step 2: Add tests/.pytest_cache and __pycache__ to .gitignore**

Read the existing `.gitignore`. It should already contain `profile/`, `.env`, `.venv/`. Append these lines if missing:

```
__pycache__/
.pytest_cache/
*.pyc
```

- [ ] **Step 3: Add pytest dev dependency to pyproject.toml**

Modify `pyproject.toml`. After the existing `dependencies = [...]` block and before `[project.scripts]`, add:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
```

- [ ] **Step 4: Install pytest**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
source .venv/bin/activate
pip install -e '.[dev]'
```

Expected: pytest installed, exit 0.

- [ ] **Step 5: Create empty tests package**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py` with:

```python
"""Shared pytest fixtures for Figma_Service host-side tests."""
import sys
from pathlib import Path

# Make run.py importable as `run` from tests.
sys.path.insert(0, str(Path(__file__).parent.parent))
```

- [ ] **Step 6: Verify pytest collects zero tests cleanly**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/ -v
```

Expected: `no tests ran` (or `collected 0 items`), exit 5. This confirms the harness is wired.

- [ ] **Step 7: Commit**

```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
git add pyproject.toml .gitignore tests/__init__.py tests/conftest.py
git commit -m "chore: add pytest harness for phase 1.5 host-side tests"
```

---

## Task 1: Extract v1 wrapper to sibling `wrapper.js`

Pure refactor of the existing Python-string wrapper into its own file, so Task 2 can replace it wholesale with the v2 version. No behavior change. Keeps v1 protocol (`version:1`, single-toast, 500 B cap) intact.

**Files:**
- Create: `/Users/yuriiliubymov/Documents/claude/Figma_Service/wrapper.js`
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py:151-169` (replace `_WRAPPER_TEMPLATE` string + `_wrap_exec` loader)

- [ ] **Step 1: Write the failing test**

Create `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_wrapper_load.py`:

```python
"""Verify the wrapper loads from wrapper.js and _wrap_exec substitutes markers."""
import run


def test_wrapper_template_loaded_from_file():
    # Template is loaded at import; must contain the expected markers.
    assert "__SENTINEL__" in run._WRAPPER_TEMPLATE
    assert "__CLOSING__" in run._WRAPPER_TEMPLATE
    assert "__CAP__" in run._WRAPPER_TEMPLATE
    assert "/*__USER_JS__*/" in run._WRAPPER_TEMPLATE


def test_wrap_exec_substitutes_all_markers():
    out = run._wrap_exec("return 42;")
    assert "__SENTINEL__" not in out
    assert "__CLOSING__" not in out
    assert "__CAP__" not in out
    assert "/*__USER_JS__*/" not in out
    assert "return 42;" in out
    assert run.SENTINEL in out
    assert run.CLOSING in out
    assert str(run.PAYLOAD_CAP_BYTES) in out
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/test_wrapper_load.py -v
```

Expected: 2 PASSED (because the current `_WRAPPER_TEMPLATE` already has these markers and `_wrap_exec` already substitutes them). If so, the test is a **regression guard** for Step 3; proceed.

If any FAIL unexpectedly, stop and investigate — don't proceed until green.

- [ ] **Step 3: Create `wrapper.js` with the exact v1 template body**

Create `/Users/yuriiliubymov/Documents/claude/Figma_Service/wrapper.js` with the full body of the current `_WRAPPER_TEMPLATE`, one statement per line for readability:

```js
(/*SCRIPTER*/async function __scripter_script_main(){
const S="__SENTINEL__",C="__CLOSING__",CAP=__CAP__,T0=Date.now();
const E=(o)=>{
  o.elapsed_ms=Date.now()-T0;
  let p;
  try{p=JSON.stringify(o)}catch(e){p=JSON.stringify({status:"error",version:1,kind:"serialize_failed",message:String(e&&e.message||e),elapsed_ms:Date.now()-T0})}
  if(p.length>CAP&&o.status==="ok")p=JSON.stringify({status:"error",version:1,kind:"payload_too_large",message:`result ${p.length}B exceeds cap ${CAP}B`,elapsed_ms:Date.now()-T0});
  figma.notify(S+p+C)
};
try{
  const R=await(async()=>{
/*__USER_JS__*/
  })();
  E({status:"ok",version:1,result:R===undefined?null:R})
}catch(e){
  E({status:"error",version:1,kind:"user_exception",message:String(e&&e.message||e),detail:e&&e.stack?String(e.stack).slice(0,2000):null})
}
})()/*SCRIPTER*/
```

- [ ] **Step 4: Replace the Python string literal with a file read**

In `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`, replace the block at lines 151–169 (the `_WRAPPER_TEMPLATE = (...)` tuple literal and `_wrap_exec` body) with:

```python
_WRAPPER_TEMPLATE = (Path(__file__).parent / "wrapper.js").read_text(encoding="utf-8")


def _wrap_exec(user_js: str) -> str:
    return (_WRAPPER_TEMPLATE
            .replace("__SENTINEL__", SENTINEL)
            .replace("__CLOSING__", CLOSING)
            .replace("__CAP__", str(PAYLOAD_CAP_BYTES))
            .replace("/*__USER_JS__*/", user_js))
```

- [ ] **Step 5: Run tests to confirm still green**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/ -v
```

Expected: 2 PASSED.

- [ ] **Step 6: Smoke-test the v1 flow end-to-end**

Run (requires `.env` populated with `FIGMA_FILE_URL` and a logged-in profile):
```bash
python run.py exec-inline --code 'return 42;'
```

Expected: stdout shows `{"status":"ok","version":1,"result":42,"elapsed_ms":<n>}`, exit 0.

If this fails, **do not proceed**. The refactor is broken. Investigate (most likely: template whitespace changed the JS semantics).

- [ ] **Step 7: Commit**

```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
git add wrapper.js run.py tests/test_wrapper_load.py
git commit -m "refactor: extract v1 wrapper template to sibling wrapper.js"
```

---

## Task 2: v2 Pydantic models — discriminated union and new error kinds

Replace `ExecOk`/`ExecErr` with the v2 shapes from the spec (lines 72–110). Keep `PROTOCOL_VERSION` bump to 2 isolated in this task — no command logic uses the models yet, so nothing breaks until Task 8/9.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py:28-49` (constants + models)
- Create: `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_protocol.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_protocol.py`:

```python
"""Protocol v2 Pydantic model invariants."""
import pytest
from pydantic import TypeAdapter, ValidationError

import run


def test_protocol_version_is_2():
    assert run.PROTOCOL_VERSION == 2


def test_exec_ok_inline_defaults_and_required_fields():
    m = run.ExecOkInline(request_id="abc123", result=42, elapsed_ms=10)
    assert m.status == "ok"
    assert m.mode == "inline"
    assert m.version == 2
    assert m.result == 42
    assert m.logs == []


def test_exec_ok_inline_rejects_missing_result():
    # result is required (Any, but must be present)
    with pytest.raises(ValidationError):
        run.ExecOkInline(request_id="abc", elapsed_ms=1)


def test_exec_ok_file_required_fields():
    m = run.ExecOkFile(
        request_id="abc", result_path="/tmp/r.json",
        bytes=10, sha256="a"*64, elapsed_ms=5,
    )
    assert m.mode == "file"
    assert m.bytes == 10
    assert m.sha256 == "a"*64


def test_exec_ok_file_rejects_missing_sha256():
    with pytest.raises(ValidationError):
        run.ExecOkFile(
            request_id="abc", result_path="/tmp/r.json",
            bytes=10, elapsed_ms=5,
        )


def test_discriminated_union_routes_by_mode():
    adapter = TypeAdapter(run.ExecOk)
    inline = adapter.validate_python({
        "status": "ok", "mode": "inline", "version": 2,
        "request_id": "abc", "result": 42, "elapsed_ms": 1,
    })
    assert isinstance(inline, run.ExecOkInline)

    file_m = adapter.validate_python({
        "status": "ok", "mode": "file", "version": 2,
        "request_id": "abc", "result_path": "/tmp/r.json",
        "bytes": 10, "sha256": "a"*64, "elapsed_ms": 1,
    })
    assert isinstance(file_m, run.ExecOkFile)


def test_exec_err_accepts_all_v2_kinds():
    for kind in [
        "user_exception", "payload_too_large", "serialize_failed",
        "timeout", "injection_failed", "scripter_unreachable",
        "chunk_incomplete", "chunk_corrupt",
        "input_read_failed", "output_write_failed",
    ]:
        m = run.ExecErr(kind=kind, message="x")
        assert m.kind == kind
        assert m.version == 2


def test_exec_err_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        run.ExecErr(kind="not_a_real_kind", message="x")


def test_exec_err_request_id_optional():
    m = run.ExecErr(kind="timeout", message="x")
    assert m.request_id is None
    m2 = run.ExecErr(kind="timeout", message="x", request_id="abc")
    assert m2.request_id == "abc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/test_protocol.py -v
```

Expected: FAIL on `test_protocol_version_is_2` (currently 1), FAIL on every model test (no `ExecOkInline` / `ExecOkFile`, no `mode`, no `request_id`, no new kinds).

- [ ] **Step 3: Update constants and write the v2 models**

In `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`, replace lines 14–49 with:

```python
from typing import Annotated, Any, Literal, Union

import typer
from dotenv import load_dotenv
from playwright.sync_api import Frame, Page, TimeoutError as PWTimeoutError, sync_playwright
from pydantic import BaseModel, Field

load_dotenv()

app = typer.Typer(no_args_is_help=True, add_completion=False)

PROFILE_DIR = Path(os.environ.get("PROFILE_DIR", "./profile")).resolve()
FIGMA_LOGIN_URL = "https://www.figma.com/login"

PROTOCOL_VERSION = 2
SENTINEL = "__FS::"         # legacy alias; kept so log messages read naturally
CLOSING = "::SF__"          # legacy alias; same reason
SENTINEL_PREFIX = SENTINEL  # v2 canonical name
SENTINEL_CLOSING = CLOSING
PAYLOAD_CAP_BYTES = 500     # exec-inline hard cap (UTF-8 bytes of the full status doc)
INLINE_CAP_BYTES = PAYLOAD_CAP_BYTES  # v2 alias used in wrapper substitution
CHUNK_B64_BYTES = 2048      # 2 KB base64 per C:<i> toast

_QUIET = False


class ExecOkInline(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["inline"] = "inline"
    version: int = PROTOCOL_VERSION
    request_id: str
    result: Any
    elapsed_ms: int
    logs: list[str] = Field(default_factory=list)


class ExecOkFile(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["file"] = "file"
    version: int = PROTOCOL_VERSION
    request_id: str
    result_path: str
    bytes: int
    sha256: str
    elapsed_ms: int
    logs: list[str] = Field(default_factory=list)


ExecOk = Annotated[Union[ExecOkInline, ExecOkFile], Field(discriminator="mode")]


class ExecErr(BaseModel):
    status: Literal["error"] = "error"
    version: int = PROTOCOL_VERSION
    request_id: str | None = None
    kind: Literal[
        "user_exception", "payload_too_large", "serialize_failed",
        "timeout", "injection_failed", "scripter_unreachable",
        "chunk_incomplete", "chunk_corrupt",
        "input_read_failed", "output_write_failed",
    ]
    message: str
    detail: str | None = None
    elapsed_ms: int | None = None
```

**Note:** The `result: Any` field in `ExecOkInline` uses the default Pydantic treatment for `Any`, which permits `None` but requires the key to be present. This matches the spec ("required; the decoded JSON value").

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/test_protocol.py -v
```

Expected: 8 PASSED.

**If `test_exec_ok_inline_rejects_missing_result` fails** (Pydantic may treat `Any` as implicitly optional), change the field to `result: Any = ...` (an Ellipsis default forces required-ness in Pydantic v2):

```python
result: Any = ...
```

Rerun and confirm 8 PASSED.

- [ ] **Step 5: Confirm old tests still green**

Run:
```bash
pytest tests/ -v
```

Expected: 10 PASSED total (2 from Task 1 + 8 new). Note: `test_wrapper_load.py` still uses v1 wrapper — that's fine; Task 4 replaces the wrapper.

- [ ] **Step 6: Commit**

```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
git add run.py tests/test_protocol.py
git commit -m "feat(protocol): v2 models — discriminated ExecOk + 4 new error kinds"
```

---

## Task 3: Host I/O helpers — `_read_code_source` and `_atomic_write`

Two pure-ish helpers the commands will call. `_read_code_source` handles `--code` / `--code-file path` / `--code-file -` with TTY refusal. `_atomic_write` handles the mode-0o600 atomic-replace sequence from spec lines 245–255.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (add helpers after `_trim`, before `_scripter_frame`)
- Create: `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_host_io.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_host_io.py`:

```python
"""Host-side I/O helpers: _read_code_source and _atomic_write."""
import io
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

import run


# --- _read_code_source ---

def test_read_code_source_from_code_arg():
    assert run._read_code_source(code="return 42;", code_file=None) == "return 42;"


def test_read_code_source_from_file(tmp_path):
    p = tmp_path / "snippet.js"
    p.write_text("return 7;", encoding="utf-8")
    assert run._read_code_source(code=None, code_file=str(p)) == "return 7;"


def test_read_code_source_file_missing_raises_input_read_failed(tmp_path):
    p = tmp_path / "nope.js"
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file=str(p))
    assert exc.value.kind == "input_read_failed"
    assert f"path={p}" in exc.value.detail
    assert "FileNotFoundError" in exc.value.detail


def test_read_code_source_file_is_directory_raises(tmp_path):
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file=str(tmp_path))
    assert exc.value.kind == "input_read_failed"
    assert "IsADirectoryError" in exc.value.detail


def test_read_code_source_stdin_non_tty(monkeypatch):
    fake_stdin = io.StringIO("return stdin_code;")
    fake_stdin.isatty = lambda: False
    monkeypatch.setattr("sys.stdin", fake_stdin)
    assert run._read_code_source(code=None, code_file="-") == "return stdin_code;"


def test_read_code_source_stdin_tty_refuses(monkeypatch):
    fake_stdin = io.StringIO("ignored")
    fake_stdin.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", fake_stdin)
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file="-")
    assert exc.value.kind == "input_read_failed"
    assert "RefuseTTY" in exc.value.detail
    assert "path=-" in exc.value.detail


def test_read_code_source_both_none_raises():
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code=None, code_file=None)
    assert exc.value.kind == "input_read_failed"


def test_read_code_source_both_set_raises():
    with pytest.raises(run._BridgeError) as exc:
        run._read_code_source(code="a", code_file="b")
    assert exc.value.kind == "input_read_failed"


# --- _atomic_write ---

def test_atomic_write_success(tmp_path):
    target = tmp_path / "out.json"
    run._atomic_write(target, b'{"a":1}\n')
    assert target.read_bytes() == b'{"a":1}\n'
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_atomic_write_no_tmp_leftovers(tmp_path):
    target = tmp_path / "out.json"
    run._atomic_write(target, b"hello")
    # No .<name>.<pid>.tmp files remain.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f".{target.name}.")]
    assert leftovers == []


def test_atomic_write_parent_missing_raises(tmp_path):
    target = tmp_path / "nonexistent" / "out.json"
    with pytest.raises(run._BridgeError) as exc:
        run._atomic_write(target, b"x")
    assert exc.value.kind == "output_write_failed"
    assert f"path={target}" in exc.value.detail
    # Stage should be one of the labeled stages.
    assert any(f"stage={s}" in exc.value.detail
               for s in ("open", "write", "fsync", "chmod", "rename"))


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "out.json"
    target.write_bytes(b"old content")
    run._atomic_write(target, b"new content")
    assert target.read_bytes() == b"new content"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/test_host_io.py -v
```

Expected: all FAIL with `AttributeError: module 'run' has no attribute '_read_code_source'` / `_atomic_write`.

- [ ] **Step 3: Implement the helpers**

In `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`, insert these helpers after the `_trim` function (around the current line 69) and before `_scripter_frame`:

```python
def _read_code_source(code: str | None, code_file: str | None) -> str:
    """Resolve --code / --code-file into a JS string. Raises _BridgeError on failure."""
    if (code is None) == (code_file is None):
        # Both None or both set — misuse.
        raise _BridgeError(
            "input_read_failed",
            "exactly one of --code or --code-file is required",
            detail="path=<none> error=ArgError: exactly one of --code/--code-file must be set",
        )
    if code is not None:
        return code
    # code_file branch
    if code_file == "-":
        if sys.stdin.isatty():
            raise _BridgeError(
                "input_read_failed",
                "refusing to read code from interactive TTY",
                detail="path=- error=RefuseTTY: refusing to read code from interactive TTY; pipe input or use --code",
            )
        try:
            return sys.stdin.read()
        except Exception as e:
            raise _BridgeError(
                "input_read_failed",
                f"stdin read failed: {e}",
                detail=f"path=- error={type(e).__name__}: {e}",
            ) from e
    try:
        return Path(code_file).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError) as e:
        raise _BridgeError(
            "input_read_failed",
            f"cannot read --code-file: {e}",
            detail=f"path={code_file} error={type(e).__name__}: {e}",
        ) from e


def _atomic_write(path: Path, payload: bytes) -> None:
    """Atomic, mode-0o600 write. Raises _BridgeError(kind='output_write_failed') on any stage failure."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    stage = "open"
    try:
        with open(tmp, "wb") as f:
            stage = "write"
            f.write(payload)
            stage = "fsync"
            f.flush()
            os.fsync(f.fileno())
        stage = "chmod"
        os.chmod(tmp, 0o600)
        stage = "rename"
        os.replace(tmp, path)
    except Exception as e:
        # Clean up any partial tmp so we don't leak it.
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise _BridgeError(
            "output_write_failed",
            f"atomic write failed at stage {stage}: {e}",
            detail=f"path={path} stage={stage} error={type(e).__name__}: {e}",
        ) from e
```

Ensure `import sys` is present at the top of the file (it already is per the current layout).

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/test_host_io.py -v
```

Expected: 12 PASSED.

- [ ] **Step 5: Run the full suite**

Run:
```bash
pytest tests/ -v
```

Expected: 22 PASSED (2 + 8 + 12).

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_host_io.py
git commit -m "feat(io): add _read_code_source (stdin+TTY-refusal) and _atomic_write"
```

---

## Task 4: v2 `wrapper.js` — request_id, chunked BEGIN+C emission, sha256

Replace the v1 wrapper body in `wrapper.js` with the v2 emission pipeline from spec lines 159–174. Mode-agnostic: the wrapper never knows whether it's `exec-inline` or `exec`; only `__INLINE_CAP__` differs (`500` vs `Infinity`). The Python `_wrap_exec` signature changes to accept `rid` and `inline_cap`.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/wrapper.js` (full rewrite)
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (`_wrap_exec` signature + marker replacement)
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_wrapper_load.py` (update markers)

- [ ] **Step 1: Update the failing tests for the new signature and markers**

Replace the contents of `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_wrapper_load.py` with:

```python
"""Verify the wrapper loads from wrapper.js and _wrap_exec substitutes v2 markers."""
import run


def test_wrapper_template_loaded_from_file():
    assert "__RID__" in run._WRAPPER_TEMPLATE
    assert "__INLINE_CAP__" in run._WRAPPER_TEMPLATE
    assert "__SENTINEL_PREFIX__" in run._WRAPPER_TEMPLATE
    assert "__SENTINEL_CLOSING__" in run._WRAPPER_TEMPLATE
    assert "__CHUNK_B64_BYTES__" in run._WRAPPER_TEMPLATE
    assert "/*__USER_JS__*/" in run._WRAPPER_TEMPLATE


def test_wrap_exec_substitutes_all_markers():
    out = run._wrap_exec("return 42;", rid="abcdef0123456789", inline_cap=500)
    assert "__RID__" not in out
    assert "__INLINE_CAP__" not in out
    assert "__SENTINEL_PREFIX__" not in out
    assert "__SENTINEL_CLOSING__" not in out
    assert "__CHUNK_B64_BYTES__" not in out
    assert "/*__USER_JS__*/" not in out
    assert "return 42;" in out
    assert "abcdef0123456789" in out
    assert "__FS::" in out
    assert "::SF__" in out


def test_wrap_exec_inline_cap_is_substituted():
    inline = run._wrap_exec("return 1;", rid="a"*16, inline_cap=500)
    assert "500" in inline
    exec_mode = run._wrap_exec("return 1;", rid="a"*16, inline_cap=float("inf"))
    # Python's float('inf') stringifies as 'inf'; wrapper accepts Infinity.
    # We substitute the token "Infinity" for any non-finite cap.
    assert "Infinity" in exec_mode
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
pytest tests/test_wrapper_load.py -v
```

Expected: FAIL — old wrapper has different markers; `_wrap_exec` takes different args.

- [ ] **Step 3: Replace `wrapper.js` with the v2 body**

Overwrite `/Users/yuriiliubymov/Documents/claude/Figma_Service/wrapper.js` with:

```js
(/*SCRIPTER*/async function __scripter_script_main(){
const RID = "__RID__";
const SP = "__SENTINEL_PREFIX__";
const SC = "__SENTINEL_CLOSING__";
const INLINE_CAP = __INLINE_CAP__;
const CHUNK = __CHUNK_B64_BYTES__;
const T0 = Date.now();

const toHex = (buf) => {
  const b = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < b.length; i++) s += b[i].toString(16).padStart(2, "0");
  return s;
};

const b64encode = (bytes) => {
  // Chunk-wise to avoid stack overflow on large Uint8Arrays.
  let out = "";
  const STEP = 0x8000;
  for (let i = 0; i < bytes.length; i += STEP) {
    out += String.fromCharCode.apply(null, bytes.subarray(i, i + STEP));
  }
  return btoa(out);
};

const emit = async (statusDoc) => {
  statusDoc.elapsed_ms = Date.now() - T0;
  let json;
  try {
    json = JSON.stringify(statusDoc);
  } catch (e) {
    json = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "serialize_failed",
      message: String(e && e.message || e),
      elapsed_ms: Date.now() - T0,
    });
  }
  let bytes = new TextEncoder().encode(json);

  // Inline cap check — only for the initial ok payload, matching v1 semantics.
  if (bytes.byteLength > INLINE_CAP && statusDoc.status === "ok") {
    const err = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "payload_too_large",
      message: `result ${bytes.byteLength}B exceeds cap ${INLINE_CAP}B`,
      elapsed_ms: Date.now() - T0,
    });
    bytes = new TextEncoder().encode(err);
  }

  // sha256 of the wire payload (transport integrity).
  let sha256Hex = "";
  try {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    sha256Hex = toHex(digest);
  } catch (e) {
    // crypto.subtle missing — emit injection_failed immediately, single-chunk.
    const errJson = JSON.stringify({
      status: "error", version: 2, request_id: RID,
      kind: "injection_failed",
      message: "crypto.subtle.digest unavailable in sandbox",
      detail: String(e && e.message || e),
      elapsed_ms: Date.now() - T0,
    });
    const errBytes = new TextEncoder().encode(errJson);
    const errB64 = b64encode(errBytes);
    const header = JSON.stringify({
      version: 2, chunks: 1, bytes: errBytes.byteLength,
      sha256: "0".repeat(64), transport: "chunked_toast",
    });
    figma.notify(SP + RID + ":BEGIN:" + header + SC);
    figma.notify(SP + RID + ":C:0:" + errB64 + SC);
    return;
  }

  const b64 = b64encode(bytes);
  const N = Math.max(1, Math.ceil(b64.length / CHUNK));
  const header = JSON.stringify({
    version: 2, chunks: N, bytes: bytes.byteLength,
    sha256: sha256Hex, transport: "chunked_toast",
  });
  figma.notify(SP + RID + ":BEGIN:" + header + SC);
  for (let i = 0; i < N; i++) {
    const seg = b64.slice(i * CHUNK, (i + 1) * CHUNK);
    figma.notify(SP + RID + ":C:" + i + ":" + seg + SC);
    // Yield to the event loop so Figma's UI can process each notify before the next.
    await new Promise((r) => setTimeout(r, 0));
  }
};

try {
  const R = await (async () => {
/*__USER_JS__*/
  })();
  await emit({
    status: "ok", version: 2, request_id: RID,
    result: R === undefined ? null : R,
  });
} catch (e) {
  await emit({
    status: "error", version: 2, request_id: RID,
    kind: "user_exception",
    message: String(e && e.message || e),
    detail: e && e.stack ? String(e.stack).slice(0, 2000) : null,
  });
}
})()/*SCRIPTER*/
```

- [ ] **Step 4: Rewrite `_wrap_exec` in run.py for v2 markers**

Replace the `_wrap_exec` function in `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` with:

```python
import math

_WRAPPER_TEMPLATE = (Path(__file__).parent / "wrapper.js").read_text(encoding="utf-8")


def _wrap_exec(user_js: str, rid: str, inline_cap: float) -> str:
    """Substitute v2 markers. inline_cap is a number; use math.inf for exec (no cap)."""
    cap_token = "Infinity" if not math.isfinite(inline_cap) else str(int(inline_cap))
    return (_WRAPPER_TEMPLATE
            .replace("__RID__", rid)
            .replace("__SENTINEL_PREFIX__", SENTINEL_PREFIX)
            .replace("__SENTINEL_CLOSING__", SENTINEL_CLOSING)
            .replace("__INLINE_CAP__", cap_token)
            .replace("__CHUNK_B64_BYTES__", str(CHUNK_B64_BYTES))
            .replace("/*__USER_JS__*/", user_js))
```

Place `import math` with the other stdlib imports at the top.

**Note:** The old `PAYLOAD_CAP_BYTES` / `SENTINEL` / `CLOSING` constants remain as legacy aliases; remove them in Task 10 if unused.

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
pytest tests/test_wrapper_load.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Confirm full suite still passes**

Run:
```bash
pytest tests/ -v
```

Expected: 23 PASSED.

**Note:** The v1 `exec-inline` command still calls the old `_wrap_exec(code)` signature and now has a broken signature mismatch at runtime — this is expected and will be fixed in Task 8. Do not run `python run.py exec-inline` between now and Task 8.

- [ ] **Step 7: Commit**

```bash
git add wrapper.js run.py tests/test_wrapper_load.py
git commit -m "feat(wrapper): v2 chunked BEGIN+C emission with sha256 and request_id"
```

---

## Task 5: Collector JS — MutationObserver snapshot on the Figma page

Add the installer/snapshot/cleanup JS as Python string constants. The installer is run via `page.evaluate(INSTALL_COLLECTOR_JS, rid)` before writing the script; snapshot returns a fresh array of all observed sentinels; cleanup removes the observer.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (add constants before `_bridge_exec`)

No new unit tests — this code runs inside the browser and can only be validated manually. Task 11's verification matrix covers it.

- [ ] **Step 1: Add the collector JS constants**

In `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`, insert these constants after the `_wrap_exec` function and before `_read_sentinel` (which is removed in Task 7):

```python
_INSTALL_COLLECTOR_JS = r"""
(rid) => {
  // Install once per request_id. Replace any existing observer.
  if (window.__FS_observer) {
    try { window.__FS_observer.disconnect(); } catch (e) {}
  }
  const prefix = "__FS::" + rid + ":";
  const closing = "::SF__";
  const seen = new Set();
  const collected = [];
  window.__FS_collected = collected;

  const scan = (node) => {
    if (!node) return;
    const t = node.textContent || "";
    let idx = 0;
    while (true) {
      const start = t.indexOf(prefix, idx);
      if (start === -1) break;
      const end = t.indexOf(closing, start);
      if (end === -1) break;
      const full = t.slice(start, end + closing.length);
      if (!seen.has(full)) {
        seen.add(full);
        collected.push(full);
      }
      idx = end + closing.length;
    }
  };

  const obs = new MutationObserver((mutations) => {
    for (const m of mutations) {
      for (const added of m.addedNodes) {
        scan(added);
        if (added.querySelectorAll) {
          added.querySelectorAll("*").forEach(scan);
        }
      }
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });
  window.__FS_observer = obs;

  // Catch sentinels already in the DOM at install time (unlikely but cheap).
  scan(document.body);

  window.__FS_snapshot = () => collected.slice();
  window.__FS_cleanup = () => {
    try { obs.disconnect(); } catch (e) {}
    delete window.__FS_observer;
    delete window.__FS_collected;
    delete window.__FS_snapshot;
    delete window.__FS_cleanup;
  };
  return true;
}
"""

_SNAPSHOT_EXPR = "() => (window.__FS_snapshot ? window.__FS_snapshot() : [])"
_CLEANUP_EXPR = "() => { if (window.__FS_cleanup) window.__FS_cleanup(); }"
```

- [ ] **Step 2: Run tests**

Run:
```bash
pytest tests/ -v
```

Expected: 23 PASSED (no new tests; this is a string-constant change).

- [ ] **Step 3: Commit**

```bash
git add run.py
git commit -m "feat(bridge): add MutationObserver-based sentinel collector JS"
```

---

## Task 6: `_reassemble_chunks` — pure, fully unit-testable reassembly

This is the bridge-side counterpart to the wrapper's emission pipeline: takes a list of sentinel strings and a request_id, finds the BEGIN header, collects every `C:<i>` chunk, base64-decodes, verifies length + sha256, json-decodes. Returns the decoded status doc OR raises `_BridgeError` with the right stage.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (add function before `_bridge_exec`)
- Create: `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_reassembly.py`

- [ ] **Step 1: Write the failing tests**

Create `/Users/yuriiliubymov/Documents/claude/Figma_Service/tests/test_reassembly.py`:

```python
"""Pure reassembly: sentinel list + rid -> decoded wrapper status doc."""
import base64
import hashlib
import json

import pytest

import run


def _build_sentinels(rid: str, payload: dict, chunk_size: int = 2048) -> list[str]:
    """Mirror the wrapper's emission for unit testing."""
    data = json.dumps(payload).encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    b64 = base64.b64encode(data).decode("ascii")
    n = max(1, (len(b64) + chunk_size - 1) // chunk_size)
    prefix = f"__FS::{rid}:"
    closing = "::SF__"
    header = json.dumps({
        "version": 2, "chunks": n, "bytes": len(data),
        "sha256": sha, "transport": "chunked_toast",
    })
    sentinels = [prefix + "BEGIN:" + header + closing]
    for i in range(n):
        seg = b64[i * chunk_size:(i + 1) * chunk_size]
        sentinels.append(prefix + f"C:{i}:" + seg + closing)
    return sentinels


def test_reassemble_round_trip_small():
    rid = "a" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": 42, "elapsed_ms": 5}
    sentinels = _build_sentinels(rid, payload)
    assert run._reassemble_chunks(sentinels, rid) == payload


def test_reassemble_ignores_other_rids():
    rid = "a" * 16
    other = "b" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "mine", "elapsed_ms": 1}
    sentinels = _build_sentinels(other, {"status": "ok", "version": 2,
                                         "request_id": other, "result": "stale",
                                         "elapsed_ms": 0})
    sentinels += _build_sentinels(rid, payload)
    assert run._reassemble_chunks(sentinels, rid) == payload


def test_reassemble_large_payload():
    rid = "c" * 16
    big = "x" * 50_000  # many chunks
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": big, "elapsed_ms": 100}
    sentinels = _build_sentinels(rid, payload, chunk_size=2048)
    assert run._reassemble_chunks(sentinels, rid) == payload


def test_reassemble_chunk_incomplete():
    rid = "d" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "x" * 10_000, "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload, chunk_size=2048)
    # Drop chunk index 2 (any middle chunk).
    sentinels = [s for s in sentinels if f":C:2:" not in s]
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_incomplete"
    assert "missing=2" in exc.value.detail


def test_reassemble_missing_begin():
    rid = "e" * 16
    # No BEGIN; just chunks (shouldn't happen in practice, but must fail cleanly).
    sentinels = [f"__FS::{rid}:C:0:abc::SF__"]
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    # No BEGIN means we can't know expected count; surface as chunk_incomplete
    # with a distinguishing detail.
    assert exc.value.kind == "chunk_incomplete"
    assert "stage=no_begin" in exc.value.detail or "missing=begin" in exc.value.detail


def test_reassemble_b64_decode_error():
    rid = "f" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": 1, "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload)
    # Corrupt chunk 0 with illegal base64.
    sentinels[1] = f"__FS::{rid}:C:0:!!!not-base64!!!::SF__"
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=b64_decode" in exc.value.detail


def test_reassemble_length_mismatch():
    rid = "g" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "abc", "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload)
    # Rewrite BEGIN to claim a wrong byte count.
    header_sentinel = sentinels[0]
    header_json = header_sentinel.split(":BEGIN:", 1)[1].rsplit("::SF__", 1)[0]
    bad = header_json.replace(f'"bytes":{len(json.dumps(payload))}',
                              '"bytes":9999')
    sentinels[0] = f"__FS::{rid}:BEGIN:" + bad + "::SF__"
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=length_mismatch" in exc.value.detail


def test_reassemble_sha256_mismatch():
    rid = "h" * 16
    payload = {"status": "ok", "version": 2, "request_id": rid,
               "result": "abc", "elapsed_ms": 1}
    sentinels = _build_sentinels(rid, payload)
    # Rewrite BEGIN with a bogus sha256 of the same length (64 hex chars).
    header_json = sentinels[0].split(":BEGIN:", 1)[1].rsplit("::SF__", 1)[0]
    data = json.loads(header_json)
    data["sha256"] = "0" * 64
    bad = json.dumps(data)
    sentinels[0] = f"__FS::{rid}:BEGIN:" + bad + "::SF__"
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=sha256_mismatch" in exc.value.detail


def test_reassemble_json_parse_error():
    rid = "i" * 16
    # Build sentinels where the payload is not valid JSON.
    raw = b"not valid json at all"
    sha = hashlib.sha256(raw).hexdigest()
    b64 = base64.b64encode(raw).decode("ascii")
    header = json.dumps({"version": 2, "chunks": 1, "bytes": len(raw),
                         "sha256": sha, "transport": "chunked_toast"})
    sentinels = [
        f"__FS::{rid}:BEGIN:" + header + "::SF__",
        f"__FS::{rid}:C:0:" + b64 + "::SF__",
    ]
    with pytest.raises(run._BridgeError) as exc:
        run._reassemble_chunks(sentinels, rid)
    assert exc.value.kind == "chunk_corrupt"
    assert "stage=json_parse" in exc.value.detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
pytest tests/test_reassembly.py -v
```

Expected: all FAIL with `AttributeError: module 'run' has no attribute '_reassemble_chunks'`.

- [ ] **Step 3: Implement `_reassemble_chunks`**

In `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`, add:

```python
import base64
import hashlib
import re


_BEGIN_RE = re.compile(r"__FS::([0-9a-f]+):BEGIN:(\{.*?\})::SF__")
_CHUNK_RE = re.compile(r"__FS::([0-9a-f]+):C:(\d+):([A-Za-z0-9+/=]*)::SF__")


def _reassemble_chunks(sentinels: list[str], rid: str) -> dict:
    """Parse a list of sentinel strings for a given rid; return decoded status doc.

    Raises _BridgeError with kind='chunk_incomplete' or 'chunk_corrupt'.
    """
    # 1. Find BEGIN for this rid (most recent wins).
    header: dict | None = None
    for s in sentinels:
        m = _BEGIN_RE.search(s)
        if m and m.group(1) == rid:
            try:
                header = json.loads(m.group(2))
            except json.JSONDecodeError as e:
                raise _BridgeError(
                    "chunk_corrupt",
                    f"BEGIN header not JSON: {e}",
                    detail=f"stage=json_parse bytes_got=0 bytes_want=0",
                ) from e
    if header is None:
        raise _BridgeError(
            "chunk_incomplete",
            "no BEGIN sentinel seen for request_id",
            detail=f"stage=no_begin got=0 expected=? missing=begin",
        )

    expected_n = int(header["chunks"])
    expected_bytes = int(header["bytes"])
    expected_sha = str(header["sha256"])

    # 2. Collect chunks for this rid.
    chunks: dict[int, str] = {}
    for s in sentinels:
        m = _CHUNK_RE.search(s)
        if m and m.group(1) == rid:
            idx = int(m.group(2))
            chunks[idx] = m.group(3)

    missing = [i for i in range(expected_n) if i not in chunks]
    if missing:
        sample = ",".join(str(i) for i in missing[:10])
        if len(missing) > 10:
            sample += f",…(+{len(missing) - 10})"
        raise _BridgeError(
            "chunk_incomplete",
            f"missing {len(missing)}/{expected_n} chunks",
            detail=f"got={len(chunks)} expected={expected_n} missing={sample}",
        )

    # 3. Reassemble in order.
    b64 = "".join(chunks[i] for i in range(expected_n))
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as e:
        raise _BridgeError(
            "chunk_corrupt",
            f"base64 decode failed: {e}",
            detail=f"stage=b64_decode",
        ) from e

    if len(raw) != expected_bytes:
        raise _BridgeError(
            "chunk_corrupt",
            f"reassembled length {len(raw)} != header.bytes {expected_bytes}",
            detail=f"stage=length_mismatch bytes_got={len(raw)} bytes_want={expected_bytes}",
        )

    got_sha = hashlib.sha256(raw).hexdigest()
    if got_sha != expected_sha:
        raise _BridgeError(
            "chunk_corrupt",
            "sha256 mismatch",
            detail=f"stage=sha256_mismatch sha256_got={got_sha} sha256_want={expected_sha}",
        )

    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise _BridgeError(
            "chunk_corrupt",
            f"payload not JSON: {e}",
            detail=f"stage=json_parse bytes_got={len(raw)} bytes_want={expected_bytes}",
        ) from e
```

Place `import base64`, `import hashlib`, `import re` with the other stdlib imports.

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
pytest tests/test_reassembly.py -v
```

Expected: 9 PASSED.

- [ ] **Step 5: Full suite green**

Run:
```bash
pytest tests/ -v
```

Expected: 32 PASSED (23 + 9).

- [ ] **Step 6: Commit**

```bash
git add run.py tests/test_reassembly.py
git commit -m "feat(bridge): add _reassemble_chunks with stage-labeled corruption kinds"
```

---

## Task 7: New `_bridge_exec` — collector install, two-phase polling, reassembly

Rewire the bridge to:
1. Install the collector before clicking Run.
2. Phase A: poll `__FS_snapshot()` for the BEGIN sentinel until `--timeout` is consumed.
3. Phase B: keep polling for chunks until all N arrive or remaining budget is exhausted.
4. Call `_reassemble_chunks` on the snapshot.
5. Cleanup the observer.

`_read_sentinel` is deleted.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (replace `_read_sentinel` + `_bridge_exec`)

No new unit tests — integration happens in Task 11's manual matrix. The reassembly logic already has full unit coverage.

- [ ] **Step 1: Delete the old `_read_sentinel`**

Remove the function `_read_sentinel` (current lines 172–189) entirely.

- [ ] **Step 2: Rewrite `_bridge_exec`**

Replace the existing `_bridge_exec` in `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` with:

```python
def _bridge_exec(url: str, user_js: str, rid: str, inline_cap: float,
                 timeout_s: float, mount_timeout_s: float) -> dict:
    """Drive Playwright + Scripter. Returns the decoded wrapper status doc."""
    wrapped_js = _wrap_exec(user_js, rid, inline_cap)
    _log("info", f"launching firefox profile={PROFILE_DIR} rid={rid}")
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(str(PROFILE_DIR), headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")

            _stage("scripter_unreachable", _ensure_scripter, page)
            frame = _scripter_frame(page, timeout_s=mount_timeout_s)
            _log("info", "scripter frame ready")

            # Install the MutationObserver collector on the main page.
            _stage("injection_failed", page.evaluate, _INSTALL_COLLECTOR_JS, rid)
            _log("info", "collector installed")

            _stage("injection_failed", _write_script, page, frame, wrapped_js)
            _stage("injection_failed", _run, frame)
            _log("info", f"run clicked; rid={rid} timeout={timeout_s}s")

            return _collect_and_reassemble(page, rid, timeout_s)
        finally:
            try:
                page.evaluate(_CLEANUP_EXPR)
            except Exception:
                pass
            ctx.close()


def _collect_and_reassemble(page: Page, rid: str, timeout_s: float) -> dict:
    """Phase A: wait for BEGIN. Phase B: wait for all chunks. Then reassemble."""
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    begin_prefix = f"__FS::{rid}:BEGIN:"
    chunk_prefix = f"__FS::{rid}:C:"

    # Phase A — wait for BEGIN.
    header: dict | None = None
    snapshot: list[str] = []
    while time.monotonic() < deadline:
        snapshot = page.evaluate(_SNAPSHOT_EXPR)
        for s in snapshot:
            if begin_prefix in s:
                # Eagerly parse so we know `chunks` and can manage Phase B.
                try:
                    header_json = s.split(":BEGIN:", 1)[1].rsplit("::SF__", 1)[0]
                    header = json.loads(header_json)
                except Exception:
                    header = None
                break
        if header is not None:
            break
        time.sleep(0.1)

    if header is None:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        raise _BridgeError(
            "timeout", f"BEGIN not seen within {timeout_s}s",
            detail=f"stage=begin elapsed_ms={elapsed_ms} timeout_s={timeout_s}",
        )

    expected_n = int(header["chunks"])

    # Phase B — wait for all chunks.
    while time.monotonic() < deadline:
        snapshot = page.evaluate(_SNAPSHOT_EXPR)
        count = sum(1 for s in snapshot if chunk_prefix in s)
        if count >= expected_n:
            break
        time.sleep(0.1)
    else:
        snapshot = page.evaluate(_SNAPSHOT_EXPR)

    # Let reassembly detect exactly which chunks are missing / corrupt.
    return _reassemble_chunks(snapshot, rid)
```

- [ ] **Step 3: Verify it compiles**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
python -c "import run; print('ok')"
```

Expected: `ok`.

If it fails with `ImportError` or `NameError`, check that `_stage`, `_BridgeError`, `_INSTALL_COLLECTOR_JS`, `_SNAPSHOT_EXPR`, `_CLEANUP_EXPR`, and `_reassemble_chunks` are all defined above `_bridge_exec` in file order.

- [ ] **Step 4: Run the suite**

Run:
```bash
pytest tests/ -v
```

Expected: 32 PASSED.

- [ ] **Step 5: Commit**

```bash
git add run.py
git commit -m "feat(bridge): collector-driven two-phase polling + chunked reassembly"
```

---

## Task 8: `exec-inline` v2 wiring — `--code-file`, discriminated union, new bridge

Rewrite the `exec_inline` command to: accept `--code` OR `--code-file`, generate a `request_id`, call the new `_bridge_exec` with `inline_cap=500`, validate the raw wrapper payload into `ExecOkInline` (injecting `mode="inline"`) or `ExecErr`, and emit to stdout.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (rewrite `exec_inline`)

- [ ] **Step 1: Rewrite the `exec_inline` command**

Replace the existing `exec_inline` in `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` with:

```python
import secrets


@app.command("exec-inline")
def exec_inline(
    code: str | None = typer.Option(None, "--code", "-c", help="JS snippet; use `return <expr>;` to send a value back."),
    code_file: str | None = typer.Option(None, "--code-file", help="Path to JS file, or `-` to read from stdin."),
    timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait for the script result after Run is clicked."),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout", help="Seconds to wait for the Scripter frame + Monaco to mount."),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Execute a JS snippet via Scripter; emit one JSON status doc to stdout."""
    global _QUIET
    _QUIET = quiet
    rid = secrets.token_hex(8)
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)

    # Input resolution.
    try:
        user_js = _read_code_source(code, code_file)
    except _BridgeError as e:
        _emit_exit(
            ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                    elapsed_ms=ms(), request_id=rid),
            1,
        )

    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter("FIGMA_FILE_URL not set. Pass -f <url> or set it in .env.")

    try:
        raw = _bridge_exec(url, user_js, rid, inline_cap=INLINE_CAP_BYTES,
                           timeout_s=timeout, mount_timeout_s=mount_timeout)
    except _BridgeError as e:
        _emit_exit(
            ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                    elapsed_ms=ms(), request_id=rid),
            1,
        )

    # Map raw wrapper payload to the v2 status doc.
    if raw.get("status") == "ok":
        # Wrapper doesn't emit `mode`; inject it so the discriminated union validates.
        raw_with_mode = {**raw, "mode": "inline"}
        try:
            _emit_exit(ExecOkInline.model_validate(raw_with_mode), 0)
        except typer.Exit:
            raise
        except Exception as e:
            _emit_exit(
                ExecErr(
                    kind="injection_failed",
                    message=f"wrapper payload validation: {e}",
                    detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                    elapsed_ms=ms(), request_id=rid,
                ),
                1,
            )
    try:
        _emit_exit(ExecErr.model_validate(raw), 1)
    except typer.Exit:
        raise
    except Exception as e:
        _emit_exit(
            ExecErr(
                kind="injection_failed",
                message=f"wrapper error-payload validation: {e}",
                detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                elapsed_ms=ms(), request_id=rid,
            ),
            1,
        )
```

Place `import secrets` with the other stdlib imports at the top of the file.

- [ ] **Step 2: Verify the module still imports**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
python -c "import run; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Run the suite**

Run:
```bash
pytest tests/ -v
```

Expected: 32 PASSED.

- [ ] **Step 4: Smoke-test `exec-inline` happy path**

Run:
```bash
python run.py exec-inline --code 'return 42;'
```

Expected: stdout contains `"status":"ok"`, `"mode":"inline"`, `"version":2`, `"request_id":"<16 hex>"`, `"result":42`, `"elapsed_ms":<n>`, `"logs":[]`. Exit 0.

If it fails with a `timeout` / `chunk_incomplete`, investigate the collector or notify coalescing (spec risk #1 — may need the `await setTimeout(0)` between emits; it's already in the wrapper but confirm it survived).

- [ ] **Step 5: Smoke-test `--code-file`**

Run:
```bash
echo 'return 7;' > /tmp/s.js
python run.py exec-inline --code-file /tmp/s.js
```

Expected: `"result":7`, exit 0.

- [ ] **Step 6: Smoke-test stdin**

Run:
```bash
echo 'return 7;' | python run.py exec-inline --code-file -
```

Expected: `"result":7`, exit 0.

- [ ] **Step 7: Smoke-test payload_too_large**

Run:
```bash
python run.py exec-inline --code 'return "x".repeat(10000);'
```

Expected: `"status":"error"`, `"kind":"payload_too_large"`, exit 1.

- [ ] **Step 8: Commit**

```bash
git add run.py
git commit -m "feat(exec-inline): v2 — request_id, --code-file, discriminated union"
```

---

## Task 9: `exec` subcommand — end-to-end

New subcommand that mirrors `exec-inline` but:
1. Uses `inline_cap=math.inf` so the wrapper never self-aborts on size.
2. Requires `--out <path>`.
3. On success: extracts `raw["result"]`, encodes it as indented JSON with trailing newline, atomically writes, computes on-disk sha256, builds `ExecOkFile`.
4. On error: emits `ExecErr` as usual, no file written.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (add `exec` command after `exec_inline`)

- [ ] **Step 1: Add the `exec` command**

In `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`, insert immediately after `exec_inline`:

```python
@app.command("exec")
def exec_(
    code: str | None = typer.Option(None, "--code", "-c", help="JS snippet; use `return <expr>;` to send a value back."),
    code_file: str | None = typer.Option(None, "--code-file", help="Path to JS file, or `-` to read from stdin."),
    out: str = typer.Option(..., "--out", help="Path to write the result JSON (atomic, mode 0o600)."),
    timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait for the script result after Run is clicked."),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout", help="Seconds to wait for the Scripter frame + Monaco to mount."),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Execute a JS snippet via Scripter; write result to --out, status doc to stdout."""
    global _QUIET
    _QUIET = quiet
    rid = secrets.token_hex(8)
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)

    # Input resolution.
    try:
        user_js = _read_code_source(code, code_file)
    except _BridgeError as e:
        _emit_exit(
            ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                    elapsed_ms=ms(), request_id=rid),
            1,
        )

    # Pre-validate --out: parent must exist.
    out_path = Path(out).resolve()
    if not out_path.parent.exists():
        _emit_exit(
            ExecErr(
                kind="output_write_failed",
                message=f"parent directory does not exist: {out_path.parent}",
                detail=f"path={out_path} stage=open error=FileNotFoundError: parent missing",
                elapsed_ms=ms(), request_id=rid,
            ),
            1,
        )

    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter("FIGMA_FILE_URL not set. Pass -f <url> or set it in .env.")

    try:
        raw = _bridge_exec(url, user_js, rid, inline_cap=math.inf,
                           timeout_s=timeout, mount_timeout_s=mount_timeout)
    except _BridgeError as e:
        _emit_exit(
            ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                    elapsed_ms=ms(), request_id=rid),
            1,
        )

    if raw.get("status") != "ok":
        # Wrapper reported an error (user_exception, serialize_failed, etc.).
        try:
            _emit_exit(ExecErr.model_validate(raw), 1)
        except typer.Exit:
            raise
        except Exception as e:
            _emit_exit(
                ExecErr(
                    kind="injection_failed",
                    message=f"wrapper error-payload validation: {e}",
                    detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                    elapsed_ms=ms(), request_id=rid,
                ),
                1,
            )

    # Success: extract result, encode canonically, write atomically, hash, build ExecOkFile.
    if "result" not in raw:
        _emit_exit(
            ExecErr(
                kind="injection_failed",
                message="wrapper ok payload missing 'result' field",
                detail=_trim(f"keys={sorted(raw.keys())}"),
                elapsed_ms=ms(), request_id=rid,
            ),
            1,
        )

    result_value = raw["result"]
    try:
        encoded = json.dumps(result_value, ensure_ascii=False, indent=2,
                             sort_keys=False) + "\n"
        payload_bytes = encoded.encode("utf-8")
    except (TypeError, ValueError) as e:
        _emit_exit(
            ExecErr(
                kind="serialize_failed",
                message=f"result not JSON-serializable host-side: {e}",
                detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                elapsed_ms=ms(), request_id=rid,
            ),
            1,
        )

    try:
        _atomic_write(out_path, payload_bytes)
    except _BridgeError as e:
        _emit_exit(
            ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                    elapsed_ms=ms(), request_id=rid),
            1,
        )

    on_disk_sha = hashlib.sha256(payload_bytes).hexdigest()
    _emit_exit(
        ExecOkFile(
            request_id=rid,
            result_path=str(out_path),
            bytes=len(payload_bytes),
            sha256=on_disk_sha,
            elapsed_ms=ms(),
        ),
        0,
    )
```

- [ ] **Step 2: Verify import**

Run:
```bash
python -c "import run; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Suite still green**

Run:
```bash
pytest tests/ -v
```

Expected: 32 PASSED.

- [ ] **Step 4: Smoke-test `exec` happy path**

Run:
```bash
python run.py exec --code 'return {a:1,b:2};' --out /tmp/r.json
cat /tmp/r.json
```

Expected:
- stdout contains `"status":"ok"`, `"mode":"file"`, `"result_path":"/tmp/r.json"`, `"bytes":<n>`, `"sha256":"<hex>"`, `"request_id":"<16 hex>"`.
- `/tmp/r.json` contains `{\n  "a": 1,\n  "b": 2\n}\n`.
- Exit 0.

- [ ] **Step 5: Smoke-test `exec` user_exception — no file written**

Run:
```bash
rm -f /tmp/r.json
python run.py exec --code 'throw new Error("boom");' --out /tmp/r.json
ls /tmp/r.json 2>&1 | head -1
```

Expected:
- stdout: `"status":"error"`, `"kind":"user_exception"`, `"message"` contains `boom`, exit 1.
- `ls` reports: `ls: /tmp/r.json: No such file or directory` (atomic guarantee — partial files never appear).

- [ ] **Step 6: Smoke-test `exec` output_write_failed**

Run:
```bash
python run.py exec --code 'return 1;' --out /nonexistent/dir/r.json
```

Expected: `"kind":"output_write_failed"`, `"detail"` contains `path=/nonexistent/dir/r.json`, exit 1.

- [ ] **Step 7: Commit**

```bash
git add run.py
git commit -m "feat(exec): new subcommand with atomic file output + dual sha256"
```

---

## Task 10: Cleanup and README update

Two housekeeping items: remove the now-unused v1 aliases from `run.py`, and document the v2 shape + `exec` subcommand.

**Files:**
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py` (remove `SENTINEL`, `CLOSING`, `PAYLOAD_CAP_BYTES` aliases if all references switched to v2 names)
- Modify: `/Users/yuriiliubymov/Documents/claude/Figma_Service/README.md`

- [ ] **Step 1: Audit remaining uses of v1 constant names**

Run:
```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
grep -n "SENTINEL\|CLOSING\|PAYLOAD_CAP_BYTES\|PROTOCOL_VERSION" run.py
```

Expected: only references to `SENTINEL_PREFIX`, `SENTINEL_CLOSING`, `INLINE_CAP_BYTES`, and `PROTOCOL_VERSION` (the latter is still used in models). The bare aliases `SENTINEL`, `CLOSING`, `PAYLOAD_CAP_BYTES` should only appear in the constant-definition block.

- [ ] **Step 2: Remove the v1 aliases**

Edit `/Users/yuriiliubymov/Documents/claude/Figma_Service/run.py`: delete the three legacy-alias lines:

```python
SENTINEL = "__FS::"         # legacy alias; kept so log messages read naturally
CLOSING = "::SF__"          # legacy alias; same reason
PAYLOAD_CAP_BYTES = 500     # exec-inline hard cap (UTF-8 bytes of the full status doc)
INLINE_CAP_BYTES = PAYLOAD_CAP_BYTES  # v2 alias used in wrapper substitution
```

Replace with the v2-only definitions:

```python
SENTINEL_PREFIX = "__FS::"
SENTINEL_CLOSING = "::SF__"
INLINE_CAP_BYTES = 500
```

Re-grep to confirm no dangling references to the removed names.

- [ ] **Step 3: Run the suite**

Run:
```bash
pytest tests/ -v
```

Expected: 32 PASSED.

- [ ] **Step 4: Smoke-test `exec-inline` end-to-end still green**

Run:
```bash
python run.py exec-inline --code 'return 42;'
```

Expected: ok, exit 0.

- [ ] **Step 5: Rewrite README.md**

Overwrite `/Users/yuriiliubymov/Documents/claude/Figma_Service/README.md` with:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add run.py README.md
git commit -m "docs: README for v2 protocol + exec subcommand; drop v1 aliases"
```

---

## Task 11: Manual verification matrix

The spec's verification section lists ten scenarios; here we expand each into a runnable command + expected result, in the order that discovers the most regressions fastest. These are **manual** because they require a signed-in Firefox profile and a live Figma file.

**Files:** None edited. Just shell commands.

**Prep:**
- Ensure `.env` has `FIGMA_FILE_URL` set.
- Ensure the profile at `./profile/` is signed in and has Scripter installed.
- Close any existing Firefox windows that might be using the profile.

- [ ] **Step 1: Phase 1 happy path (v2 shape)**

Run:
```bash
python run.py exec-inline --code 'return 42;'
```

Expected stdout (one line):
```
{"status":"ok","mode":"inline","version":2,"request_id":"<16 hex>","result":42,"elapsed_ms":<n>,"logs":[]}
```
Exit 0.

- [ ] **Step 2: `exec-inline` from file**

Run:
```bash
echo 'return 7;' > /tmp/s.js
python run.py exec-inline --code-file /tmp/s.js
```

Expected: `"result":7`, exit 0.

- [ ] **Step 3: `exec-inline` from stdin**

Run:
```bash
echo 'return 7;' | python run.py exec-inline --code-file -
```

Expected: `"result":7`, exit 0.

- [ ] **Step 4: `exec-inline` TTY refusal**

Run (in an interactive terminal, without piping):
```bash
python run.py exec-inline --code-file -
```

Expected: `"kind":"input_read_failed"`, `"detail"` contains `RefuseTTY`, exit 1. No hang.

- [ ] **Step 5: `exec-inline` mutex violation**

Run:
```bash
python run.py exec-inline --code 'return 1;' --code-file /tmp/s.js
```

Expected: `"kind":"input_read_failed"`, `"detail"` contains `ArgError`, exit 1.

- [ ] **Step 6: `exec` happy path, small**

Run:
```bash
rm -f /tmp/r.json
python run.py exec --code 'return {a:1,b:2};' --out /tmp/r.json
cat /tmp/r.json
```

Expected:
- stdout: status doc with `"mode":"file"`, `"result_path":"/tmp/r.json"`, `"bytes":<n>`, `"sha256":"<64 hex>"`, exit 0.
- `/tmp/r.json` on disk: pretty JSON `{\n  "a": 1,\n  "b": 2\n}\n`.

- [ ] **Step 7: `exec` happy path, ~1 MB**

Run:
```bash
rm -f /tmp/big.json
python run.py exec --code 'return "x".repeat(1000000);' --out /tmp/big.json --timeout 60
wc -c /tmp/big.json
```

Expected:
- Status doc has `bytes` ≈ 1_000_010 (the 1M x's + surrounding `"…"`), exit 0.
- Wall-clock under 60 s.
- `wc -c /tmp/big.json` reports ~1,000,010.
- The `"sha256"` in the status doc matches `shasum -a 256 /tmp/big.json`.

- [ ] **Step 8: `exec` user exception — no file written**

Run:
```bash
rm -f /tmp/r.json
python run.py exec --code 'throw new Error("boom");' --out /tmp/r.json
ls -la /tmp/r.json 2>&1
```

Expected:
- Status doc: `"kind":"user_exception"`, `"message"` contains `boom`, exit 1.
- `ls -la /tmp/r.json` reports `No such file or directory`.
- No leftover `/tmp/.r.json.<pid>.tmp`.

- [ ] **Step 9: `exec` output_write_failed**

Run:
```bash
python run.py exec --code 'return 1;' --out /nonexistent/dir/r.json
```

Expected: `"kind":"output_write_failed"`, `"detail"` includes `path=/nonexistent/dir/r.json`, exit 1. No Figma window opens (pre-check before bridge launch).

- [ ] **Step 10: Hash integrity**

Run:
```bash
python run.py exec --code 'return {foo: "bar", baz: [1,2,3]};' --out /tmp/hash.json
DOC_SHA=$(python -c "import json,sys; print(json.load(open('/tmp/hash.json.status')).get('sha256',''))" 2>/dev/null || \
          python run.py exec --code 'return {foo: "bar", baz: [1,2,3]};' --out /tmp/hash.json | python -c "import json,sys; print(json.loads(sys.stdin.read())['sha256'])")
DISK_SHA=$(shasum -a 256 /tmp/hash.json | cut -d' ' -f1)
echo "doc:  $DOC_SHA"
echo "disk: $DISK_SHA"
test "$DOC_SHA" = "$DISK_SHA" && echo "MATCH" || echo "MISMATCH"
```

Expected: `MATCH`. (Alternatively, just eyeball one `exec` run's status-doc sha256 and compare with `shasum -a 256 <path>`.)

- [ ] **Step 11: Cross-run isolation**

Run:
```bash
python run.py exec-inline --code 'return 1;'
python run.py exec-inline --code 'return 2;'
```

Expected: both succeed, `request_id` differs between the two, each status doc's result matches its call (no contamination from the prior run's toasts).

- [ ] **Step 12: `chunk_incomplete` (forced)**

Rigged experiment — run `exec` with a tiny timeout so phase B can't complete for a large payload:

```bash
python run.py exec --code 'return "x".repeat(500_000);' --out /tmp/incomplete.json --timeout 2
```

Expected: `"kind":"chunk_incomplete"`, `"detail"` includes `got=<n> expected=<N> missing=…`, exit 1. No file at `/tmp/incomplete.json`.

(This test may race — if the machine is very fast, 2 s might actually be enough. Drop `--timeout 1` if needed, or use a larger payload.)

- [ ] **Step 13: `hello` regression**

Run:
```bash
python run.py hello -m "bridge alive v2"
```

Expected: yellow toast in Figma, prints elapsed time, exit 0. (`hello` wasn't touched this phase but verify it still works since the collector might accidentally interfere — it shouldn't, because `hello` doesn't call `_bridge_exec`.)

- [ ] **Step 14: Record any anomalies**

If any of steps 1–13 produced unexpected output, open the spec's "Open implementation risks" section (lines 313–319) and match the symptom:

- Steps 1–11 erratic / missing chunks → risk #1 (notify coalescing). Try increasing the `await setTimeout(r, 0)` to `setTimeout(r, 5)` in `wrapper.js`.
- `chunk_corrupt` stage=b64_decode with multi-byte Unicode → risk in TextEncoder handling. Double-check the wrapper uses `new TextEncoder().encode(json)` not `json.length`.
- `injection_failed` mentioning `crypto.subtle` → risk #3. Fall back to inlined SHA-256 JS in `wrapper.js` (see spec line 317–318).
- Sentinels never arriving → risk #4 (MutationObserver coverage). Check whether toasts land in a Shadow DOM; widen the observer scope.

Document any adjustments in a follow-up commit with a message like `fix(wrapper): pace notify emits to 5ms intervals per risk #1`.

- [ ] **Step 15: Commit verification log (optional)**

If adjustments were needed in step 14, commit them. Otherwise this is a no-op.

```bash
git status
# If nothing to commit, skip. Otherwise:
git add run.py wrapper.js
git commit -m "fix(wrapper): <describe the field-discovered adjustment>"
```

---

## Self-review checklist (run before handing off to executor)

**Spec coverage:**

- [x] New `exec` subcommand — Task 9.
- [x] `--code-file <path>` on both commands — Task 3 (helper) + Tasks 8/9 (wiring).
- [x] `--code-file -` stdin with TTY refusal — Task 3.
- [x] Protocol v2 with `request_id` — Task 2 + Tasks 8/9.
- [x] Discriminated `ExecOk` — Task 2.
- [x] Four new error kinds (`chunk_incomplete`, `chunk_corrupt`, `input_read_failed`, `output_write_failed`) — Task 2 + raised at Tasks 3/6.
- [x] sha256 integrity (transport + on-disk) — Task 6 (transport) + Task 9 (on-disk).
- [x] Chunked emission grammar `__FS::<rid>:BEGIN:…` / `__FS::<rid>:C:<i>:<b64>` — Task 4 (wrapper) + Task 6 (parser).
- [x] 2 KB base64 per toast — `CHUNK_B64_BYTES = 2048` constant, Task 2.
- [x] Wrapper mode-agnostic, `INLINE_CAP = Infinity` for `exec` — Task 4.
- [x] Collector via `MutationObserver` — Task 5.
- [x] Two-phase polling (BEGIN then chunks) with stage-labeled timeout — Task 7.
- [x] Atomic write to `--out` with mode 0o600 and labeled stages — Task 3.
- [x] `--out` parent-missing pre-check — Task 9.
- [x] On `exec` success, file holds only `result`, not envelope — Task 9.
- [x] On wrapper error, no file written — Task 9 (error path returns before `_atomic_write`).
- [x] Canonical file encoding (`indent=2`, `ensure_ascii=False`, trailing newline) — Task 9.
- [x] `request_id = secrets.token_hex(8)` — Tasks 8/9.
- [x] `PROTOCOL_VERSION = 2` — Task 2.
- [x] Standardized `detail` schemas per kind — Tasks 3, 6, 7.
- [x] Wrapper moved to `wrapper.js` — Task 1 (extract) + Task 4 (rewrite).
- [x] No module split (deferred) — confirmed by keeping everything in `run.py`.
- [x] README updated — Task 10.

**Placeholder scan:** No "TBD", "TODO later", "implement error handling" — every step names the exact file, code, or command.

**Type/name consistency:**
- `_read_code_source(code, code_file)` — Tasks 3, 8, 9 all call with the same two kwargs.
- `_wrap_exec(user_js, rid, inline_cap)` — Task 4 defines, Tasks 7/8/9 call consistently.
- `_bridge_exec(url, user_js, rid, inline_cap, timeout_s, mount_timeout_s)` — Task 7 defines, Tasks 8/9 call consistently.
- `_atomic_write(path, payload)` — Task 3 defines, Task 9 calls consistently.
- `_reassemble_chunks(sentinels, rid)` — Task 6 defines, Task 7 calls consistently.
- `ExecOkInline` / `ExecOkFile` / `ExecOk` / `ExecErr` — same names across Task 2 definitions and Task 8/9 usage.
- Sentinel constants renamed from `SENTINEL`/`CLOSING` to `SENTINEL_PREFIX`/`SENTINEL_CLOSING` in Task 2; Task 10 removes the legacy aliases. Intermediate tasks use whichever is current at that point.

Plan is internally consistent and spec-complete.
