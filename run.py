"""Playwright + Scripter bridge for Figma Plugin API automation.

Phase 0: `login`, `hello`. Phase 1 thin slice: `exec-inline` + JSON protocol.
See ~/.claude/plans/yes-please-recursive-treasure.md for Phase 1 design.
"""

import base64
import hashlib
import json
import math
import os
import re
import secrets
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
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
SENTINEL_PREFIX = "__FS::"
SENTINEL_CLOSING = "::SF__"
INLINE_CAP_BYTES = 500      # exec-inline hard cap (UTF-8 bytes of the full status doc)
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


class _BridgeError(Exception):
    def __init__(self, kind: str, message: str, detail: str | None = None) -> None:
        self.kind, self.message, self.detail = kind, message, detail


def _log(level: str, msg: str) -> None:
    if _QUIET and level != "error":
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    print(f"{ts} [{level}] {msg}", file=sys.stderr)


def _trim(s: str | None, n: int = 2000) -> str | None:
    """Cap detail strings to match the JS wrapper's own 2KB stack slice."""
    if s is None:
        return None
    return s if len(s) <= n else s[:n] + f"… (+{len(s) - n}B truncated)"


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


def _scripter_frame(page: Page, timeout_s: float = 30) -> Frame:
    """Find the Scripter iframe and wait for Monaco to mount."""
    deadline = time.monotonic() + timeout_s
    saw_scripter_frame = False
    last_err: Exception | None = None
    last_err_repr: str | None = None
    while time.monotonic() < deadline:
        for fr in page.frames:
            if "scripter.rsms.me" not in fr.url:
                continue
            saw_scripter_frame = True
            try:
                ready = fr.evaluate(
                    "() => !!document.querySelector('.monaco-editor textarea.inputarea')"
                )
                if ready:
                    return fr
            except Exception as e:
                last_err = e
                # Dedupe: only log when the error message changes, so a slow
                # Monaco boot doesn't spew 120 identical lines over 30s.
                rep = f"{type(e).__name__}: {e}"
                if rep != last_err_repr:
                    last_err_repr = rep
                    _log("debug", f"scripter frame poll: {rep}")
        page.wait_for_timeout(250)
    if not saw_scripter_frame:
        raise _BridgeError(
            "scripter_unreachable",
            f"no scripter.rsms.me frame seen within {timeout_s}s",
            detail=_trim("page frames: " + ", ".join(fr.url for fr in page.frames)),
        )
    detail = _trim(traceback.format_exception_only(last_err)[-1].strip()) if last_err else None
    raise _BridgeError(
        "scripter_unreachable",
        f"scripter frame seen but Monaco did not mount within {timeout_s}s",
        detail=detail,
    )


def _ensure_scripter(page: Page) -> None:
    """Launch Scripter via Quick Actions unless it is already running."""
    page.wait_for_selector("canvas", timeout=20_000)
    page.wait_for_timeout(1_500)
    if any("scripter.rsms.me" in fr.url for fr in page.frames):
        return
    page.keyboard.press("Meta+/")
    page.wait_for_timeout(300)
    page.keyboard.type("Scripter")
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def _write_script(page: Page, frame: Frame, code: str) -> None:
    """Atomic replace via Monaco's model API — bypasses focus/selection entirely."""
    result = frame.evaluate(
        """(code) => {
          if (typeof monaco === 'undefined') return { ok: false, reason: 'monaco global undefined' };
          const models = monaco.editor.getModels();
          if (!models.length) return { ok: false, reason: 'no models registered' };
          const user = models.filter(m => {
            const uri = m.uri.toString();
            return !/lib\\.[^/]+\\.d\\.ts$/.test(uri) && !uri.includes('node_modules');
          });
          const target = user[0] || models[0];
          target.setValue(code);
          return { ok: true, value: target.getValue(), uri: target.uri.toString(), modelCount: models.length };
        }""",
        code,
    )
    if not result.get("ok"):
        raise RuntimeError(f"Monaco API unreachable: {result.get('reason')}")
    _log("info", f"monaco write ok: {result['modelCount']} models, uri={result['uri']}")


def _run(frame: Frame) -> None:
    """Scripter's Run is a <div> at y=-20; force=True bypasses visibility check."""
    frame.locator(".button.run").first.click(force=True, timeout=5_000)


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


_BEGIN_RE = re.compile(r"__FS::([0-9a-zA-Z]+):BEGIN:(\{.*?\})::SF__")
_CHUNK_RE = re.compile(r"__FS::([0-9a-zA-Z]+):C:(\d+):(.*?)::SF__")


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


def _stage(kind: str, fn, *args):
    try:
        return fn(*args)
    except _BridgeError:
        raise
    except Exception as e:
        raise _BridgeError(kind, str(e), detail=_trim(traceback.format_exc())) from e


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


def _emit_exit(model, code: int) -> None:
    typer.echo(model.model_dump_json())
    raise typer.Exit(code)


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


@app.command()
def login() -> None:
    """Sign in to Figma and install the Scripter plugin (one-time setup)."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Launching headed Firefox with profile at {PROFILE_DIR}")
    typer.echo("Steps inside the browser:")
    typer.echo("  1. Sign in to Figma.")
    typer.echo("  2. Install the Scripter plugin from the Community.")
    typer.echo("  3. Create a new empty design file.")
    typer.echo("  4. Copy its URL into .env as FIGMA_FILE_URL.")
    typer.echo("  5. Close the browser window when done.")
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(
            str(PROFILE_DIR), headless=False
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(FIGMA_LOGIN_URL)
        ctx.wait_for_event("close", timeout=0)


@app.command()
def hello(
    message: str = typer.Option("bridge alive", "-m", "--message"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
) -> None:
    """Paste `figma.notify(<message>)` into Scripter and run it."""
    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter(
            "FIGMA_FILE_URL not set. Run `python run.py login` first, "
            "or pass -f <url>."
        )
    user_js = f"figma.notify({json.dumps(message)});"
    code = (
        "(/*SCRIPTER*/async function __scripter_script_main(){\n"
        f"{user_js}\n"
        "})()/*SCRIPTER*/"
    )
    t0 = time.monotonic()
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(
            str(PROFILE_DIR), headless=False
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        _ensure_scripter(page)
        frame = _scripter_frame(page)
        _write_script(page, frame, code)
        _run(frame)
        page.wait_for_timeout(1_500)
        ctx.close()
    typer.echo(f"done in {time.monotonic() - t0:.1f}s")


if __name__ == "__main__":
    app()
