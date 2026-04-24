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

from host_io import _log, _trim, set_quiet
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
) -> None:
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
    _log("info", f"sync result: {json.dumps(result)}")

    try:
        _emit_exit(ExecOkInline.model_validate({**raw, "mode": "inline"}), 0)
    except typer.Exit:
        raise
    except Exception as e:
        _emit_exit(ExecErr(kind="injection_failed",
                           message=f"wrapper payload validation: {e}",
                           detail=_trim("".join(traceback.format_exception_only(e)).strip()),
                           elapsed_ms=ms(), request_id=rid), 1)


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
    """Create or update primitive color variables in Figma from tokens/primitives.json."""
    set_quiet(quiet)

    _run_validation(timeout=timeout, mount_timeout=mount_timeout,
                    file_url=file_url, quiet=quiet)

    tokens_path = Path(tokens_file)
    if not tokens_path.exists():
        raise typer.BadParameter(f"Token file not found: {tokens_path}")

    tokens = json.loads(tokens_path.read_text())

    script_path = _SCRIPT_DIR / "sync_primitive_colors.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")

    user_js = (script_path.read_text()
               .replace("__TOKENS__", json.dumps(tokens))
               .replace("__DRY_RUN__", "true" if dry_run else "false"))

    _dispatch_sync(user_js, timeout=timeout, mount_timeout=mount_timeout,
                   file_url=file_url, quiet=quiet)


@sync_app.command("primitive-colors-normalized")
def sync_primitive_colors_normalized(
    normalized_file: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--normalized",
        help="Path to primitives.normalized.json from `plan primitive-colors-normalized`.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing to Figma."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Rename color/candidate/<hex> variables to their final names, or create them from normalized JSON."""
    set_quiet(quiet)

    _run_validation(timeout=timeout, mount_timeout=mount_timeout,
                    file_url=file_url, quiet=quiet)

    normalized_path = Path(normalized_file)
    if not normalized_path.exists():
        raise typer.BadParameter(f"Normalized file not found: {normalized_path}")

    data = json.loads(normalized_path.read_text(encoding="utf-8"))
    if "colors" not in data:
        raise typer.BadParameter("Normalized file missing required key: 'colors'")

    entries = data["colors"]
    typer.echo(f"Entries: {len(entries)} normalized colors")

    script_path = _SCRIPT_DIR / "sync_primitive_colors_normalized.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")

    user_js = (script_path.read_text(encoding="utf-8")
               .replace("__NORMALIZED__", json.dumps(entries))
               .replace("__DRY_RUN__", "true" if dry_run else "false"))

    _dispatch_sync(user_js, timeout=timeout, mount_timeout=mount_timeout,
                   file_url=file_url, quiet=quiet)


@sync_app.command("primitive-colors-from-proposal")
def sync_primitive_colors_from_proposal(
    proposal_file: str = typer.Option(
        str(_TOKENS_DIR / "primitives.proposed.json"),
        "--proposal",
        help="Path to primitives.proposed.json from `plan primitive-colors-from-project`.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes without writing to Figma."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Max candidates to sync."),
    timeout: float = typer.Option(10.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Create or update primitive color variables from new_candidate entries in a proposal file."""
    set_quiet(quiet)

    _run_validation(timeout=timeout, mount_timeout=mount_timeout,
                    file_url=file_url, quiet=quiet)

    proposal_path = Path(proposal_file)
    if not proposal_path.exists():
        raise typer.BadParameter(f"Proposal file not found: {proposal_path}")

    data = json.loads(proposal_path.read_text(encoding="utf-8"))
    if "colors" not in data:
        raise typer.BadParameter("Proposal file missing required key: 'colors'")

    candidates = [c for c in data["colors"] if c["status"] == "new_candidate"]
    if limit is not None:
        candidates = candidates[:limit]

    typer.echo(f"Candidates: {len(candidates)} new_candidate colors")

    script_path = _SCRIPT_DIR / "sync_primitive_colors_from_proposal.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")

    user_js = (script_path.read_text(encoding="utf-8")
               .replace("__CANDIDATES__", json.dumps(candidates))
               .replace("__DRY_RUN__", "true" if dry_run else "false"))

    _dispatch_sync(user_js, timeout=timeout, mount_timeout=mount_timeout,
                   file_url=file_url, quiet=quiet)
