"""Playwright + Scripter bridge: launch, mount, inject wrapper, collect sentinels.

Owns everything between "I have JS to run" and "I have a decoded wrapper
status doc". Imports protocol for sentinel constants + reassembly; imports
host_io for logging.

Transport: the wrapper emits each sentinel via `console.log`. Playwright's
`page.on("console")` captures messages from the page and its frames, so the
Scripter iframe's console output arrives at the host without any DOM
observation. Replaces the earlier `figma.notify` → MutationObserver path,
which dropped messages when Figma's toast stack auto-dismissed older toasts.
"""

import json
import math
import os
import time
import traceback
from pathlib import Path

from playwright.sync_api import Frame, Page, sync_playwright

from protocol import (
    _BridgeError,
    _reassemble_chunks,
    CHUNK_B64_BYTES,
    SENTINEL_CLOSING,
    SENTINEL_PREFIX,
)
from host_io import _log, _trim


PROFILE_DIR = Path(os.environ.get("PROFILE_DIR", "./profile")).resolve()
FIGMA_LOGIN_URL = "https://www.figma.com/login"


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
                # Gate on three signals: Monaco input mounted, a visible Run
                # button (Scripter hides it until the active script loads),
                # and >1 registered model (lib.d.ts models land after boot,
                # and writing before they do targets a placeholder model
                # that Run won't execute).
                ready = fr.evaluate(
                    "() => !!document.querySelector('.monaco-editor textarea.inputarea')"
                    " && !!document.querySelector('.button.run:not(.hidden)')"
                    " && (typeof monaco !== 'undefined')"
                    " && monaco.editor.getModels().length > 1"
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
        detail = _trim("page frames: " + ", ".join(fr.url for fr in page.frames))
        _log("error", f"stage=mount kind=scripter_unreachable timeout_s={timeout_s} reason=no_frame")
        raise _BridgeError(
            "scripter_unreachable",
            f"no scripter.rsms.me frame seen within {timeout_s}s",
            detail=detail,
        )
    detail = _trim(traceback.format_exception_only(last_err)[-1].strip()) if last_err else None
    _log("error", f"stage=mount kind=scripter_unreachable timeout_s={timeout_s} reason=monaco_not_ready")
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
    """Substitute v2 markers. inline_cap is a UTF-8 byte cap; pass math.inf for no cap."""
    cap_token = "Infinity" if not math.isfinite(inline_cap) else str(int(inline_cap))
    return (_WRAPPER_TEMPLATE
            .replace("__RID__", rid)
            .replace("__SENTINEL_PREFIX__", SENTINEL_PREFIX)
            .replace("__SENTINEL_CLOSING__", SENTINEL_CLOSING)
            .replace("__INLINE_CAP__", cap_token)
            .replace("__CHUNK_B64_BYTES__", str(CHUNK_B64_BYTES))
            .replace("/*__USER_JS__*/", user_js))


def _stage(stage: str, kind: str, fn, *args):
    """Run `fn`; on failure, log `stage=<layer> kind=<kind>` and raise _BridgeError."""
    try:
        return fn(*args)
    except _BridgeError as e:
        _log("error", f"stage={stage} kind={e.kind} message={_trim(e.message, 200)}")
        raise
    except Exception as e:
        _log("error", f"stage={stage} kind={kind} error={type(e).__name__}: {_trim(str(e), 200)}")
        raise _BridgeError(kind, str(e), detail=_trim(traceback.format_exc())) from e


def _bridge_exec(url: str, user_js: str, rid: str, inline_cap: float,
                 timeout_s: float, mount_timeout_s: float) -> dict:
    """Drive Playwright + Scripter. Returns the decoded wrapper status doc.

    The console collector is attached to the page *before* navigation and
    script injection so no BEGIN / chunk lines can slip past us in a race.
    """
    wrapped_js = _wrap_exec(user_js, rid, inline_cap)
    _log("info", f"launching firefox profile={PROFILE_DIR} rid={rid}")
    with sync_playwright() as pw:
        ctx = pw.firefox.launch_persistent_context(str(PROFILE_DIR), headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Attach the console collector before anything else runs. Sentinels
            # live in `buffer`; `_collect_and_reassemble` polls it while the
            # Playwright sync loop pumps events.
            buffer: list[str] = []
            prefix = f"{SENTINEL_PREFIX}{rid}:"

            def _on_console(msg) -> None:
                try:
                    text = msg.text
                except Exception:
                    return
                if prefix in text:
                    buffer.append(text)

            page.on("console", _on_console)

            page.goto(url, wait_until="domcontentloaded")

            _stage("mount", "scripter_unreachable", _ensure_scripter, page)
            frame = _scripter_frame(page, timeout_s=mount_timeout_s)
            _log("info", "scripter frame ready")

            _stage("inject", "injection_failed", _write_script, page, frame, wrapped_js)
            _stage("inject", "injection_failed", _run, frame)
            _log("info", f"run clicked; rid={rid} timeout={timeout_s}s")

            return _collect_and_reassemble(page, rid, timeout_s, buffer)
        finally:
            ctx.close()


def _collect_and_reassemble(page: Page, rid: str, timeout_s: float,
                            buffer: list[str]) -> dict:
    """Phase A: wait for BEGIN. Phase B: wait for all chunks. Then reassemble.

    `buffer` is the list populated by the `page.on("console")` handler
    registered in `_bridge_exec`. We never mutate it here — just read
    snapshots and let Playwright's sync loop pump events between polls.
    """
    t0 = time.monotonic()
    deadline = t0 + timeout_s
    begin_prefix = f"{SENTINEL_PREFIX}{rid}:BEGIN:"
    chunk_prefix = f"{SENTINEL_PREFIX}{rid}:C:"

    # Phase A — wait for BEGIN.
    header: dict | None = None
    while time.monotonic() < deadline:
        for s in buffer:
            if begin_prefix in s:
                try:
                    header_json = s.split(":BEGIN:", 1)[1].rsplit(SENTINEL_CLOSING, 1)[0]
                    header = json.loads(header_json)
                except Exception:
                    header = None
                break
        if header is not None:
            break
        # wait_for_timeout (not time.sleep) so sync Playwright can dispatch
        # pending console events into our handler during the wait.
        page.wait_for_timeout(100)

    if header is None:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _log("error",
             f"stage=transport kind=timeout rid={rid} phase=begin "
             f"elapsed_ms={elapsed_ms} timeout_s={timeout_s} buffer_len={len(buffer)}")
        raise _BridgeError(
            "timeout", f"BEGIN not seen within {timeout_s}s",
            detail=f"stage=begin elapsed_ms={elapsed_ms} timeout_s={timeout_s}",
        )

    expected_n = int(header["chunks"])

    # Phase B — wait for all chunks.
    while time.monotonic() < deadline:
        count = sum(1 for s in buffer if chunk_prefix in s)
        if count >= expected_n:
            break
        page.wait_for_timeout(100)

    # Reassembly raises chunk_incomplete / chunk_corrupt with the precise
    # missing indexes; we just log the layer here.
    try:
        return _reassemble_chunks(list(buffer), rid)
    except _BridgeError as e:
        _log("error",
             f"stage=reassemble kind={e.kind} rid={rid} "
             f"expected_chunks={expected_n} buffer_len={len(buffer)}")
        raise
