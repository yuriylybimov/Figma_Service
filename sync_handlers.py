"""Write-side Figma automation handlers — the `sync` sub-app.

All commands read token source files from the host, inject them into JS
templates, and dispatch through the bridge. All writes are idempotent and
support --dry-run.

Rule: validate_runtime_context runs before every sync; stops on failure.
"""

import json
import secrets
import sys
import time
import traceback
from pathlib import Path

import typer

from host_io import _log, _trim, set_quiet, set_debug
from protocol import EXEC_CAP_BYTES, ExecErr, ExecOkInline, _BridgeError
from transport import _bridge_exec

import os

sync_app = typer.Typer(no_args_is_help=True, help="Write-side Figma variable automation.")

_SCRIPT_DIR = Path(__file__).parent / "scripts" / "variables"
_TOKENS_DIR = Path(__file__).parent / "tokens"


def _emit_exit(model, code: int) -> None:
    typer.echo(model.model_dump_json())
    raise typer.Exit(code)


def _dispatch_sync(
    user_js: str,
    *,
    timeout: float,
    mount_timeout: float,
    file_url: str | None,
    quiet: bool,
) -> tuple[dict, ExecOkInline]:
    """Run JS via the bridge and return (js_result_dict, ok_model) on success.

    On error calls _emit_exit (which raises typer.Exit) so callers never see a
    partial return. On success the caller is responsible for calling _emit_exit.
    """
    set_quiet(quiet)
    rid = secrets.token_hex(8)
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)

    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter("FIGMA_FILE_URL not set. Pass -f <url> or set it in .env.")

    try:
        raw = _bridge_exec(url, user_js, rid, inline_cap=EXEC_CAP_BYTES,
                           timeout_s=timeout, mount_timeout_s=mount_timeout)
    except _BridgeError as e:
        _emit_exit(ExecErr(kind=e.kind, message=e.message, detail=e.detail,
                           elapsed_ms=ms(), request_id=rid), 1)

    if raw.get("status") != "ok":
        try:
            _emit_exit(ExecErr.model_validate(raw), 1)
        except typer.Exit:
            raise
        except Exception as e:
            _emit_exit(ExecErr(kind="injection_failed",
                               message=f"wrapper error-payload validation: {e}",
                               detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                               elapsed_ms=ms(), request_id=rid), 1)

    result = raw.get("result", {})

    try:
        ok_model = ExecOkInline.model_validate({**raw, "mode": "inline"})
    except Exception as e:
        _emit_exit(ExecErr(kind="injection_failed",
                           message=f"wrapper payload validation: {e}",
                           detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                           elapsed_ms=ms(), request_id=rid), 1)

    return result, ok_model


def _run_validation(
    *,
    timeout: float,
    mount_timeout: float,
    file_url: str | None,
    quiet: bool,
) -> None:
    """Run validate_runtime_context; print result and abort (exit 1) if any check fails."""
    script_path = _SCRIPT_DIR / "validate_runtime_context.js"
    if not script_path.exists():
        typer.echo(f"[validate_runtime_context] script not found: {script_path}", err=True)
        raise typer.Exit(1)

    url = file_url or os.environ.get("FIGMA_FILE_URL")
    if not url:
        raise typer.BadParameter("FIGMA_FILE_URL not set.")

    rid = secrets.token_hex(8)
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)

    try:
        raw = _bridge_exec(url, script_path.read_text(), rid,
                           inline_cap=EXEC_CAP_BYTES,
                           timeout_s=timeout, mount_timeout_s=mount_timeout)
    except _BridgeError as e:
        typer.echo(f"[validate_runtime_context] bridge error: {e.message}", err=True)
        raise typer.Exit(1)

    if raw.get("status") != "ok":
        typer.echo(f"[validate_runtime_context] bridge returned error: {raw}", err=True)
        raise typer.Exit(1)

    result = raw.get("result", {})
    checks = result.get("checks", [])

    for c in checks:
        status = "pass" if c["passed"] else "FAIL"
        detail = f" — {c['detail']}" if c.get("detail") else ""
        _log("info", f"[validate_runtime_context] {status} {c['name']}{detail}")

    if not result.get("ok", False):
        failed = [c["name"] for c in checks if not c["passed"]]
        typer.echo(
            f"[validate_runtime_context] failed: {', '.join(failed)}. Aborting.",
            err=True,
        )
        raise typer.Exit(1)

    _log("info", "[validate_runtime_context] all checks passed")


@sync_app.command("validate-runtime-context")
def cmd_validate_runtime_context(
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Check that the Figma plugin API and variables API are reachable."""
    set_quiet(quiet)
    _run_validation(timeout=timeout, mount_timeout=mount_timeout,
                    file_url=file_url, quiet=quiet)


@sync_app.command("primitive-colors")
def sync_primitive_colors(
    tokens_file: str = typer.Option(
        str(_TOKENS_DIR / "primitives.json"),
        "--tokens",
        help="Path to primitives.json token file.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing to Figma."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """[LEGACY] Not part of the normalized token pipeline. Use sync primitive-colors-normalized instead."""
    typer.echo(
        "ERROR: sync primitive-colors is a legacy command and is not part of the "
        "normalized token pipeline.\n"
        "Use the architecture-defined sync path instead:\n"
        "  plan primitive-colors-normalized  →  plan validate-normalized  →  "
        "sync primitive-colors-normalized",
        err=True,
    )
    raise typer.Exit(1)


@sync_app.command("primitive-colors-normalized")
def sync_primitive_colors_normalized(
    normalized_file: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--normalized",
        help="Path to primitives.normalized.json from `plan primitive-colors-normalized`.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing to Figma."),
    verbose: bool = typer.Option(False, "--verbose", help="Print per-entry log (human mode only)."),
    json_output: bool = typer.Option(False, "--json", help="Emit only machine-readable JSON; suppresses all human output."),
    debug: bool = typer.Option(False, "--debug", help="Show infrastructure logs (Playwright, bridge) on stderr."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Rename color/candidate/<hex> variables to their final names, or create them from normalized JSON."""
    set_quiet(quiet)
    set_debug(debug)

    _run_validation(timeout=timeout, mount_timeout=mount_timeout,
                    file_url=file_url, quiet=quiet)

    normalized_path = Path(normalized_file)
    if not normalized_path.exists():
        raise typer.BadParameter(f"Normalized file not found: {normalized_path}")

    data = json.loads(normalized_path.read_text(encoding="utf-8"))
    if "colors" not in data:
        raise typer.BadParameter("Normalized file missing required key: 'colors'")

    def _entry_sort_key(e: dict) -> tuple:
        parts = e.get("final_name", "").split("/")
        group = parts[1] if len(parts) >= 2 else ""
        scale_str = parts[2] if len(parts) >= 3 else ""
        scale = int(scale_str) if scale_str.isdigit() else float("inf")
        return (group, scale)

    entries = sorted(data["colors"], key=_entry_sort_key)

    script_path = _SCRIPT_DIR / "sync_primitive_colors_normalized.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")

    user_js = (script_path.read_text(encoding="utf-8")
               .replace("__NORMALIZED__", json.dumps(entries))
               .replace("__DRY_RUN__", "true" if dry_run else "false"))

    result, ok_model = _dispatch_sync(user_js, timeout=timeout, mount_timeout=mount_timeout,
                                       file_url=file_url, quiet=quiet)

    if json_output:
        # Machine mode: JSON only, no human text.
        _emit_exit(ok_model, 0)

    # Human mode: summary (+ optional verbose log), no JSON.
    label = "Dry-run summary" if dry_run else "Sync summary"
    typer.echo(f"\n{label}")
    typer.echo(f"  +{result.get('created', '?')} created"
               f"  ~{result.get('renamed', '?')} renamed"
               f"  {result.get('skipped', '?')} skipped"
               f"  ({result.get('total', len(entries))} total)")

    log_entries = result.get("log", [])

    if not verbose:
        # Default: grouped preview of created tokens.
        created = [e for e in log_entries if e.get("action") in ("would-rename-or-create", "created")]
        if created:
            groups: dict[str, list[tuple[str, str]]] = {}
            for e in created:
                fname = e.get("final_name") or e.get("name", "")
                hex_ = e.get("hex") or e.get("value", "")
                parts = fname.split("/")
                group = parts[-2] if len(parts) >= 2 else "other"
                scale = parts[-1] if len(parts) >= 1 else "?"
                groups.setdefault(group, []).append((scale, hex_))
            typer.echo("\nCreated tokens (by group)\n")
            fixed_items: list[tuple[str, str]] = []
            for group, items in sorted(groups.items()):
                items_sorted = sorted(items, key=lambda x: int(x[0]) if x[0].isdigit() else x[0])
                if group == "color" and all(not s.isdigit() for s, _ in items_sorted):
                    fixed_items = items_sorted
                    continue
                typer.echo(f"  {group} ({len(items_sorted)})")
                for scale, hex_ in items_sorted:
                    typer.echo(f"    {scale:<5}  {hex_}")
            if fixed_items:
                for label, hex_ in fixed_items:
                    typer.echo(f"  {label:<7}  {hex_}")
    else:
        # Verbose: diff-style lines for all log entries.
        if log_entries:
            typer.echo("\nDetailed changes\n")
            for e in sorted(log_entries, key=lambda e: e.get("final_name", e.get("name", ""))):
                action = e.get("action", "")
                final = e.get("final_name", e.get("name", "?"))
                hex_ = e.get("hex", e.get("value", ""))
                parts = final.split("/")
                short = "/".join(parts[-2:]) if len(parts) >= 2 else final
                if action in ("would-rename-or-create", "created"):
                    typer.echo(f"  + {short:<30}  {hex_}")
                elif action == "renamed":
                    from_ = e.get("from", "?")
                    typer.echo(f"  ~ {from_:<30}  → {final}")
                elif action == "skipped":
                    typer.echo(f"  = {short:<30}  (skipped)")

    raise typer.Exit(0)


@sync_app.command("semantic-tokens")
def sync_semantic_tokens(
    semantics_file: str = typer.Option(
        str(_TOKENS_DIR / "semantics.normalized.json"),
        "--semantics",
        help="Path to semantics.normalized.json.",
    ),
    primitives_file: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--primitives",
        help="Path to primitives.normalized.json (used to validate all references exist).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing to Figma."),
    verbose: bool = typer.Option(False, "--verbose", help="Print per-entry log (human mode only)."),
    json_output: bool = typer.Option(False, "--json", help="Emit only machine-readable JSON; suppresses all human output."),
    debug: bool = typer.Option(False, "--debug", help="Show infrastructure logs (Playwright, bridge) on stderr."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Create or update semantic token variables in Figma as aliases to primitive variables."""
    set_quiet(quiet)
    set_debug(debug)

    _run_validation(timeout=timeout, mount_timeout=mount_timeout,
                    file_url=file_url, quiet=quiet)

    semantics_path = Path(semantics_file)
    if not semantics_path.exists():
        raise typer.BadParameter(f"Semantics file not found: {semantics_path}")

    primitives_path = Path(primitives_file)
    if not primitives_path.exists():
        raise typer.BadParameter(f"Primitives file not found: {primitives_path}")

    semantics_data = json.loads(semantics_path.read_text(encoding="utf-8"))
    if not isinstance(semantics_data, dict):
        raise typer.BadParameter(f"Semantics file must be a flat JSON object: {semantics_path}")

    primitives_data = json.loads(primitives_path.read_text(encoding="utf-8"))
    primitive_names = {e["final_name"] for e in primitives_data.get("colors", []) if "final_name" in e}

    missing = [prim for prim in semantics_data.values() if prim not in primitive_names]
    if missing:
        typer.echo(
            f"ERROR: {len(missing)} primitive(s) referenced in semantics are not present in primitives.normalized.json:\n"
            + "\n".join(f"  {m}" for m in sorted(missing)),
            err=True,
        )
        raise typer.Exit(1)

    entries = [
        {"semantic_name": sem, "primitive_name": prim}
        for sem, prim in sorted(semantics_data.items())
    ]

    script_path = _SCRIPT_DIR / "sync_semantic_tokens.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")

    user_js = (script_path.read_text(encoding="utf-8")
               .replace("__SEMANTICS__", json.dumps(entries))
               .replace("__DRY_RUN__", "true" if dry_run else "false"))

    result, ok_model = _dispatch_sync(user_js, timeout=timeout, mount_timeout=mount_timeout,
                                       file_url=file_url, quiet=quiet)

    if result.get("ok") is False or result.get("errored", 0) > 0:
        missing_prims = result.get("missing_primitives", [])
        if missing_prims:
            typer.echo(
                f"ERROR: Figma reports {len(missing_prims)} missing primitive(s):\n"
                + "\n".join(f"  {m}" for m in missing_prims),
                err=True,
            )
        else:
            typer.echo(f"ERROR: sync_semantic_tokens.js returned ok:false (errored={result.get('errored', '?')})", err=True)
        raise typer.Exit(1)

    if json_output:
        _emit_exit(ok_model, 0)

    label = "Dry-run summary" if dry_run else "Sync summary"
    typer.echo(f"\n{label}")
    typer.echo(f"  +{result.get('created', '?')} created"
               f"  ~{result.get('updated', '?')} updated"
               f"  {result.get('skipped', '?')} skipped"
               f"  ({result.get('total', len(entries))} total)")

    log_entries = result.get("log", [])

    if verbose and log_entries:
        typer.echo("\nDetailed changes\n")
        for e in sorted(log_entries, key=lambda e: e.get("semantic_name", "")):
            action = e.get("action", "")
            sem = e.get("semantic_name", "?")
            prim = e.get("primitive_name", "")
            if action in ("would-create-alias", "created"):
                typer.echo(f"  + {sem:<40}  → {prim}")
            elif action == "updated":
                typer.echo(f"  ~ {sem:<40}  → {prim}")
            elif action == "skipped":
                typer.echo(f"  = {sem:<40}  (skipped)")

    raise typer.Exit(0)
