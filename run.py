"""Playwright + Scripter bridge for Figma Plugin API automation.

Phase 0: `login`, `hello`. Phase 1 thin slice: `exec-inline` + JSON protocol.
See ~/.claude/plans/yes-please-recursive-treasure.md for Phase 1 design.
"""

import json
import os
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


def _wrap_exec(user_js: str) -> str:
    return (_WRAPPER_TEMPLATE
            .replace("__SENTINEL__", SENTINEL)
            .replace("__CLOSING__", CLOSING)
            .replace("__CAP__", str(PAYLOAD_CAP_BYTES))
            .replace("/*__USER_JS__*/", user_js))


def _read_sentinel(page: Page, timeout_s: float) -> dict:
    """Poll main Figma DOM for a sentinel-bracketed JSON payload."""
    handle = page.wait_for_function(
        """({s,e}) => { const t=document.body?document.body.textContent:''; const i=t.indexOf(s);"""
        """ if (i===-1) return null; const j=t.indexOf(e,i+s.length);"""
        """ return j===-1?null:t.slice(i+s.length,j); }""",
        arg={"s": SENTINEL, "e": CLOSING},
        timeout=int(timeout_s * 1000),
    )
    raw_text = handle.json_value()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise _BridgeError(
            "injection_failed",
            "malformed sentinel payload",
            detail=_trim(f"{type(e).__name__}: {e}\npayload: {raw_text!r}"),
        ) from e


def _stage(kind: str, fn, *args):
    try:
        return fn(*args)
    except _BridgeError:
        raise
    except Exception as e:
        raise _BridgeError(kind, str(e), detail=_trim(traceback.format_exc())) from e


def _bridge_exec(url: str, wrapped_js: str, timeout_s: float, mount_timeout_s: float) -> dict:
    _log("info", f"launching firefox profile={PROFILE_DIR}")
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(str(PROFILE_DIR), headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded")
            _stage("scripter_unreachable", _ensure_scripter, page)
            frame = _scripter_frame(page, timeout_s=mount_timeout_s)
            _log("info", "scripter frame ready")
            _stage("injection_failed", _write_script, page, frame, wrapped_js)
            _stage("injection_failed", _run, frame)
            _log("info", f"run clicked; waiting (timeout={timeout_s}s)")
            try:
                result = _read_sentinel(page, timeout_s)
            except PWTimeoutError as e:
                raise _BridgeError("timeout", f"sentinel not seen within {timeout_s}s") from e
            except _BridgeError:
                raise
            except Exception as e:
                raise _BridgeError(
                    "injection_failed",
                    f"readback: {e}",
                    detail=_trim(traceback.format_exc()),
                ) from e
            _log("info", "sentinel received")
            return result
        finally:
            ctx.close()


def _emit_exit(model, code: int) -> None:
    typer.echo(model.model_dump_json())
    raise typer.Exit(code)


@app.command("exec-inline")
def exec_inline(
    code: str = typer.Option(..., "--code", "-c", help="JS snippet; use `return <expr>;` to send a value back."),
    timeout: float = typer.Option(10.0, "--timeout", help="Seconds to wait for the script result after Run is clicked."),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout", help="Seconds to wait for the Scripter frame + Monaco to mount. Independent of --timeout."),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Execute a JS snippet via Scripter; emit one JSON document to stdout."""
    global _QUIET
    _QUIET = quiet
    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter("FIGMA_FILE_URL not set. Pass -f <url> or set it in .env.")
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)
    try:
        raw = _bridge_exec(url, _wrap_exec(code), timeout, mount_timeout)
    except _BridgeError as e:
        _emit_exit(ExecErr(kind=e.kind, message=e.message, detail=e.detail, elapsed_ms=ms()), 1)
    try:
        if raw.get("status") == "ok":
            _emit_exit(ExecOk.model_validate(raw), 0)
        _emit_exit(ExecErr.model_validate(raw), 1)
    except typer.Exit:
        raise
    except Exception as e:
        _emit_exit(
            ExecErr(
                kind="injection_failed",
                message=f"wrapper validation: {e}",
                detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                elapsed_ms=ms(),
            ),
            1,
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
