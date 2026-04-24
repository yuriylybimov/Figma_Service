"""Host-side override commands — the `override` sub-app.

All commands run entirely on the host. No Figma round-trips.
"""

import json
import re
from pathlib import Path

import typer

from host_io import _atomic_write
from protocol import _BridgeError

override_app = typer.Typer(no_args_is_help=True, help="Manage final-name overrides for primitive color tokens.")

_TOKENS_DIR = Path(__file__).parent / "tokens"
_OVERRIDES_PATH = _TOKENS_DIR / "overrides.normalized.json"
_MERGE_PROPOSAL_PATH = _TOKENS_DIR / "overrides.merge.proposed.json"
_MERGE_OUTPUT_PATH = _TOKENS_DIR / "overrides.merge.json"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_hex(hex_: str) -> str:
    """Return hex_ if valid, else raise typer.BadParameter."""
    if not _HEX_RE.match(hex_):
        raise typer.BadParameter(f"hex must be #rrggbb, got {hex_!r}")
    return hex_


def _validate_final_name(name: str) -> str:
    """Return name if valid, else raise typer.BadParameter.

    Reuses the same rules as plan_handlers._validate_normalized:
    must start with 'color/' and must not start with 'color/candidate/'.
    """
    if not name.startswith("color/"):
        raise typer.BadParameter(f"final_name must start with 'color/', got {name!r}")
    if name.startswith("color/candidate/"):
        raise typer.BadParameter(f"final_name must not start with 'color/candidate/', got {name!r}")
    return name


def _load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read overrides file: {e}")
    if not isinstance(data, dict):
        raise typer.BadParameter("Overrides file must be a JSON object.")
    return data


def _save_overrides(path: Path, overrides: dict[str, str]) -> None:
    payload = (json.dumps(overrides, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        _atomic_write(path, payload)
    except _BridgeError as e:
        typer.echo(f"ERROR: {e.message}", err=True)
        raise typer.Exit(1)


@override_app.command("set")
def override_set(
    hex_: str = typer.Argument(..., metavar="HEX", help="Color hex, e.g. #1a2b3c"),
    final_name: str = typer.Argument(..., metavar="FINAL_NAME", help="Token name, e.g. color/brand/navy"),
    overrides_file: str = typer.Option(
        str(_OVERRIDES_PATH),
        "--overrides",
        help="Path to overrides JSON (default: tokens/overrides.normalized.json).",
    ),
) -> None:
    """Set or replace a final_name override for a hex color."""
    _validate_hex(hex_)
    _validate_final_name(final_name)

    path = Path(overrides_file).resolve()
    overrides = _load_overrides(path)

    existed = hex_ in overrides
    old_name = overrides.get(hex_)
    overrides[hex_] = final_name

    _save_overrides(path, overrides)

    if existed:
        typer.echo(f"Updated: {hex_}  {old_name!r} → {final_name!r}")
    else:
        typer.echo(f"Set:     {hex_}  → {final_name!r}")


@override_app.command("apply-merge-proposal")
def override_apply_merge_proposal(
    proposal_file: str = typer.Option(
        str(_MERGE_PROPOSAL_PATH),
        "--proposal",
        help="Path to merge proposal JSON (default: tokens/overrides.merge.proposed.json).",
    ),
    output_file: str = typer.Option(
        str(_MERGE_OUTPUT_PATH),
        "--out",
        help="Path to write the merge map (default: tokens/overrides.merge.json).",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite output file if it already exists."),
) -> None:
    """Apply a merge proposal: extract merge_map and write tokens/overrides.merge.json."""
    proposal_path = Path(proposal_file).resolve()
    output_path = Path(output_file).resolve()

    if not proposal_path.exists():
        typer.echo(f"ERROR: Proposal file not found: {proposal_path}", err=True)
        raise typer.Exit(1)

    try:
        data = json.loads(proposal_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: Failed to read proposal file: {e}", err=True)
        raise typer.Exit(1)

    if not isinstance(data, dict) or "merge_map" not in data:
        typer.echo("ERROR: Proposal file must be a JSON object with a 'merge_map' key.", err=True)
        raise typer.Exit(1)

    merge_map = data["merge_map"]

    if not isinstance(merge_map, dict) or len(merge_map) == 0:
        typer.echo("ERROR: 'merge_map' must be a non-empty object.", err=True)
        raise typer.Exit(1)

    for key, val in merge_map.items():
        if not _HEX_RE.match(key):
            typer.echo(f"ERROR: Invalid hex key in merge_map: {key!r}", err=True)
            raise typer.Exit(1)
        if not _HEX_RE.match(val):
            typer.echo(f"ERROR: Invalid hex value in merge_map for key {key!r}: {val!r}", err=True)
            raise typer.Exit(1)

    if output_path.exists() and not force:
        typer.echo(
            f"ERROR: Output file already exists: {output_path}\n"
            "Pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(1)

    payload = (json.dumps(merge_map, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        _atomic_write(output_path, payload)
    except _BridgeError as e:
        typer.echo(f"ERROR: {e.message}", err=True)
        raise typer.Exit(1)

    typer.echo(f"Applied {len(merge_map)} merge(s) → {output_path}")
    for src, canonical in sorted(merge_map.items()):
        typer.echo(f"  {src}  →  {canonical}")


@override_app.command("list")
def override_list(
    overrides_file: str = typer.Option(
        str(_OVERRIDES_PATH),
        "--overrides",
        help="Path to overrides JSON (default: tokens/overrides.normalized.json).",
    ),
) -> None:
    """Print all current overrides."""
    path = Path(overrides_file).resolve()
    overrides = _load_overrides(path)

    if not overrides:
        typer.echo("No overrides set.")
        return

    typer.echo(f"Overrides ({len(overrides)}):")
    for hex_, name in sorted(overrides.items()):
        typer.echo(f"  {hex_}  →  {name}")
