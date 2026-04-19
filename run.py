"""Playwright + Scripter bridge for Figma Plugin API automation.

Phase 0: `login`, `hello`. Phase 1.5: `exec-inline` + `exec` (v2 protocol).
Phase 2 thin slice: `read <tool>` sub-app for document/selection/page +
design-system (variable collections, local styles) queries.

Runtime is split across three sibling modules:
- protocol.py : wire format, Pydantic models, chunk reassembly
- host_io.py  : logging, code-source resolution, atomic writes
- transport.py: Playwright, Scripter, wrapper injection, sentinel collection

This file keeps the Typer command surface and re-exports the sibling symbols
so `tests/conftest.py` + `import run; run._X` references keep working unchanged.
"""

import hashlib
import json
import os
import secrets
import time
import traceback
from pathlib import Path

import typer
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# --- Re-exports (keep `run.X` stable for tests and external callers). -------
from protocol import (
    PROTOCOL_VERSION,
    SENTINEL_PREFIX,
    SENTINEL_CLOSING,
    INLINE_CAP_BYTES,
    EXEC_CAP_BYTES,
    CHUNK_B64_BYTES,
    _BridgeError,
    ExecOkInline,
    ExecOkFile,
    ExecOk,
    ExecErr,
    _BEGIN_RE,
    _CHUNK_RE,
    _reassemble_chunks,
)
from host_io import (
    _log,
    _trim,
    _read_code_source,
    _atomic_write,
    set_quiet,
)
from transport import (
    PROFILE_DIR,
    FIGMA_LOGIN_URL,
    _WRAPPER_TEMPLATE,
    _wrap_exec,
    _scripter_frame,
    _ensure_scripter,
    _write_script,
    _run,
    _stage,
    _bridge_exec,
    _collect_and_reassemble,
)

load_dotenv()

app = typer.Typer(no_args_is_help=True, add_completion=False)
read_app = typer.Typer(no_args_is_help=True, help="Read-only Figma queries.")
app.add_typer(read_app, name="read")


def _emit_exit(model, code: int) -> None:
    typer.echo(model.model_dump_json())
    raise typer.Exit(code)


# ---------------------------------------------------------------------------
# exec-inline / exec
# ---------------------------------------------------------------------------

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
    set_quiet(quiet)
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
    set_quiet(quiet)
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
        raw = _bridge_exec(url, user_js, rid, inline_cap=EXEC_CAP_BYTES,
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


# ---------------------------------------------------------------------------
# login / hello
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# read <tool> sub-app
# ---------------------------------------------------------------------------

def _dispatch_read(
    user_js: str,
    *,
    out: str | None,
    timeout: float,
    mount_timeout: float,
    file_url: str | None,
    quiet: bool,
) -> None:
    """Run baked JS through the bridge; emit a v2 status doc; exit.

    Inline by default; pass --out to get file mode + EXEC_CAP_BYTES headroom.
    """
    set_quiet(quiet)
    rid = secrets.token_hex(8)
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)

    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter("FIGMA_FILE_URL not set. Pass -f <url> or set it in .env.")

    out_path: Path | None = None
    if out is not None:
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
        cap = EXEC_CAP_BYTES
    else:
        cap = INLINE_CAP_BYTES

    try:
        raw = _bridge_exec(url, user_js, rid, inline_cap=cap,
                           timeout_s=timeout, mount_timeout_s=mount_timeout)
    except _BridgeError as e:
        _emit_exit(
            ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                    elapsed_ms=ms(), request_id=rid),
            1,
        )

    if raw.get("status") != "ok":
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

    if out_path is None:
        # Inline mode: emit ExecOkInline with the wrapper result verbatim.
        try:
            _emit_exit(ExecOkInline.model_validate({**raw, "mode": "inline"}), 0)
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

    # File mode: mirror `exec` — extract result, serialize, atomic-write, hash.
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


# --- Content read layer ----------------------------------------------------

_JS_PING = """
return { ping: true, pageName: figma.currentPage.name };
"""


@read_app.command("ping")
def read_ping(
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Smallest round-trip: confirm the bridge can run one line and send a reply."""
    _dispatch_read(_JS_PING, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


_JS_DOCUMENT_SUMMARY = """
return {
  name: figma.root.name,
  type: figma.root.type,
  pages: figma.root.children.map(p => ({
    id: p.id, name: p.name, type: p.type, childCount: p.children.length
  })),
  currentPageId: figma.currentPage.id,
};
"""


@read_app.command("document-summary")
def read_document_summary(
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Top-level document info: name, pages, current page."""
    _dispatch_read(_JS_DOCUMENT_SUMMARY, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


_JS_SELECTION_INFO = """
return figma.currentPage.selection.map(n => ({
  id: n.id, name: n.name, type: n.type,
  parentId: n.parent ? n.parent.id : null,
  visible: n.visible, locked: n.locked,
  x: n.x, y: n.y, width: n.width, height: n.height,
}));
"""


@read_app.command("selection-info")
def read_selection_info(
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Current page selection: id, type, geometry, parent."""
    _dispatch_read(_JS_SELECTION_INFO, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


_JS_PAGE_NODES_SUMMARY_TMPL = """
const pid = __PAGE_ID__;
const page = pid ? figma.getNodeById(pid) : figma.currentPage;
if (!page) throw new Error("Page not found: " + pid);
return {
  pageId: page.id, pageName: page.name,
  nodes: page.children.map(n => ({
    id: n.id, name: n.name, type: n.type,
    childCount: n.children ? n.children.length : 0,
    x: n.x, y: n.y, width: n.width, height: n.height,
  })),
};
"""


@read_app.command("page-nodes-summary")
def read_page_nodes_summary(
    page_id: str | None = typer.Option(None, "--page-id", help="Page id (defaults to current page)."),
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Top-level nodes of a page: id, type, geometry, child count."""
    user_js = _JS_PAGE_NODES_SUMMARY_TMPL.replace(
        "__PAGE_ID__", json.dumps(page_id),
    )
    _dispatch_read(user_js, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


# --- Design-system read layer ---------------------------------------------

_JS_VARIABLE_COLLECTIONS_SUMMARY = """
return figma.variables.getLocalVariableCollections().map(c => ({
  id: c.id, name: c.name, key: c.key,
  modes: c.modes,
  defaultModeId: c.defaultModeId,
  variableCount: c.variableIds.length,
  remote: c.remote,
}));
"""


@read_app.command("variable-collections-summary")
def read_variable_collections_summary(
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Local variable collections: id, modes, variable counts."""
    _dispatch_read(_JS_VARIABLE_COLLECTIONS_SUMMARY, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


_JS_VARIABLE_COLLECTION_DETAIL_TMPL = """
const cid = __COLLECTION_ID__;
const col = figma.variables.getVariableCollectionById(cid);
if (!col) throw new Error("VariableCollection not found: " + cid);
const vars = col.variableIds.map(vid => {
  const v = figma.variables.getVariableById(vid);
  return {
    id: v.id, name: v.name, key: v.key,
    resolvedType: v.resolvedType,
    scopes: v.scopes,
    valuesByMode: v.valuesByMode,
    description: v.description,
    remote: v.remote,
  };
});
return {
  id: col.id, name: col.name,
  modes: col.modes, defaultModeId: col.defaultModeId,
  variables: vars,
};
"""


@read_app.command("variable-collection-detail")
def read_variable_collection_detail(
    collection_id: str = typer.Option(..., "--collection-id", help="VariableCollection id to expand."),
    out: str = typer.Option(..., "--out", help="Output path (required — payload reliably exceeds inline cap)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Full variable list for a collection (modes, valuesByMode, scopes)."""
    user_js = _JS_VARIABLE_COLLECTION_DETAIL_TMPL.replace(
        "__COLLECTION_ID__", json.dumps(collection_id),
    )
    _dispatch_read(user_js, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


_LOCAL_STYLES_KINDS = ("paint", "text", "effect", "grid")

_JS_LOCAL_STYLES_SUMMARY_TMPL = """
const kind = __KIND__;
const offset = __OFFSET__;
const limit = __LIMIT__;
const getters = {
  paint:  figma.getLocalPaintStyles,
  text:   figma.getLocalTextStyles,
  effect: figma.getLocalEffectStyles,
  grid:   figma.getLocalGridStyles,
};
const fn = getters[kind];
if (!fn) throw new Error("unknown kind: " + kind);
const all = fn.call(figma);
const total = all.length;
const end = limit === null ? total : Math.min(offset + limit, total);
const slice = offset >= total ? [] : all.slice(offset, end);
return {
  kind: kind,
  total: total,
  offset: offset,
  limit: limit,
  items: slice.map(s => ({
    id: s.id, name: s.name, key: s.key,
    type: s.type, description: s.description,
  })),
};
"""


@read_app.command("local-styles-summary")
def read_local_styles_summary(
    kind: str = typer.Option(..., "--kind", help=f"Style kind: one of {'/'.join(_LOCAL_STYLES_KINDS)}."),
    limit: int | None = typer.Option(None, "--limit", min=0, help="Max items to return (default: all)."),
    offset: int = typer.Option(0, "--offset", min=0, help="Items to skip from the start."),
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Local styles of a single kind, paginated: id, name, key, type, description."""
    if kind not in _LOCAL_STYLES_KINDS:
        raise typer.BadParameter(
            f"--kind must be one of {'/'.join(_LOCAL_STYLES_KINDS)} (got {kind!r})"
        )
    user_js = (_JS_LOCAL_STYLES_SUMMARY_TMPL
               .replace("__KIND__", json.dumps(kind))
               .replace("__OFFSET__", json.dumps(offset))
               .replace("__LIMIT__", json.dumps(limit)))
    _dispatch_read(user_js, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


_JS_COMPONENTS_SUMMARY_TMPL = """
const pid = __PAGE_ID__;
const offset = __OFFSET__;
const limit = __LIMIT__;
const page = pid ? figma.getNodeById(pid) : figma.currentPage;
if (!page) throw new Error("Page not found: " + pid);
if (page.type !== "PAGE") throw new Error("Not a page: " + page.type);
const nodes = page.findAllWithCriteria
  ? page.findAllWithCriteria({ types: ["COMPONENT", "COMPONENT_SET"] })
  : page.findAll(n => n.type === "COMPONENT" || n.type === "COMPONENT_SET");
const total = nodes.length;
const end = limit === null ? total : Math.min(offset + limit, total);
const slice = offset >= total ? [] : nodes.slice(offset, end);
return {
  pageId: page.id,
  pageName: page.name,
  total: total,
  offset: offset,
  limit: limit,
  items: slice.map(n => ({
    id: n.id, name: n.name, type: n.type,
    key: n.key,
    description: n.description || "",
    parentId: n.parent ? n.parent.id : null,
  })),
};
"""


@read_app.command("components-summary")
def read_components_summary(
    page_id: str | None = typer.Option(None, "--page-id", help="Page id (defaults to current page)."),
    limit: int | None = typer.Option(None, "--limit", min=0, help="Max items to return (default: all)."),
    offset: int = typer.Option(0, "--offset", min=0, help="Items to skip from the start."),
    out: str | None = typer.Option(None, "--out", help="Write result JSON to this path (file mode)."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Components and component sets on a page, paginated."""
    user_js = (_JS_COMPONENTS_SUMMARY_TMPL
               .replace("__PAGE_ID__", json.dumps(page_id))
               .replace("__OFFSET__", json.dumps(offset))
               .replace("__LIMIT__", json.dumps(limit)))
    _dispatch_read(user_js, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)


if __name__ == "__main__":
    app()
