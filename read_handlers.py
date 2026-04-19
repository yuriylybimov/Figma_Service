"""Read-only Figma query handlers — the `read` sub-app.

All commands call `_dispatch_read`, which runs baked JS through the bridge
and emits a v2 status doc. No Playwright is imported here; transport lives
in transport.py.
"""

import hashlib
import json
import secrets
import time
import traceback
from pathlib import Path

import typer

from host_io import _atomic_write, _log, _trim, set_quiet
from protocol import (
    EXEC_CAP_BYTES,
    INLINE_CAP_BYTES,
    ExecErr,
    ExecOkFile,
    ExecOkInline,
    _BridgeError,
)
from transport import _bridge_exec

import os

read_app = typer.Typer(no_args_is_help=True, help="Read-only Figma queries.")


def _emit_exit(model, code: int) -> None:
    typer.echo(model.model_dump_json())
    raise typer.Exit(code)


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
# Content read layer
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Design-system read layer
# ---------------------------------------------------------------------------

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

# Shared pagination slice injected into both local-styles-summary and
# components-summary. Source array must be bound to `_all` before this runs.
_JS_PAGINATE_SLICE = """
const total = _all.length;
const end = limit === null ? total : Math.min(offset + limit, total);
const slice = offset >= total ? [] : _all.slice(offset, end);
"""

_JS_LOCAL_STYLES_SUMMARY_TMPL = (
    """
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
const _all = fn.call(figma);
"""
    + _JS_PAGINATE_SLICE
    + """
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
)


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


_JS_COMPONENTS_SUMMARY_TMPL = (
    """
const pid = __PAGE_ID__;
const offset = __OFFSET__;
const limit = __LIMIT__;
const page = pid ? figma.getNodeById(pid) : figma.currentPage;
if (!page) throw new Error("Page not found: " + pid);
if (page.type !== "PAGE") throw new Error("Not a page: " + page.type);
const _all = page.findAllWithCriteria
  ? page.findAllWithCriteria({ types: ["COMPONENT", "COMPONENT_SET"] })
  : page.findAll(n => n.type === "COMPONENT" || n.type === "COMPONENT_SET");
"""
    + _JS_PAGINATE_SLICE
    + """
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
)


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
