"""Host-side planning commands — the `plan` sub-app.

All commands run entirely on the host. No Figma round-trips.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

# Re-exported so tests can import pure helpers via `plan_handlers`; do not remove.
from plan_colors import (  # noqa: F401
    _STATUS_ORDER,
    _HUE_GROUPS,
    _GRAY_SATURATION_THRESHOLD,
    _SCALES,
    _FIXED_COLORS,
    _build_lookup,
    _hex_to_hls,
    _perceived_chroma,
    _color_group,
    _hex_to_group,
    _assign_scales,
    _fmt_group_block,
    _fmt_color_usage_summary_lines,
    _fmt_top_color_lines,
    _fmt_merge_summary_line,
    _fmt_merge_table,
    _build_normalized_entries,
    _classify_colors,
    _sort_colors,
    _build_color_lookups,
    _classify_and_count,
    _apply_use_counts,
    _hsl_delta,
    _group_near_duplicates,
    _deduplicate_primitives,
    _cleanup_candidates,
    _build_primitive_color_plan,
    _HEX_RE,
    _FORBIDDEN_MERGE_HEXES,
    _validate_merge_map,
    _apply_merge_map,
    _validate_normalized,
    _suggest_merge_overrides,
    _ALL_SCALES,
    _LOW_CHROMA_THRESHOLD,
    _audit_palette,
    _build_and_validate_semantic_normalized,
    _suggest_semantic_tokens,
    _suggest_semantic_tokens_contextual,
)

plan_app = typer.Typer(no_args_is_help=True, help="Host-side planning and proposal commands.")

_TOKENS_DIR = Path(__file__).parent / "tokens"


@plan_app.command("cleanup-candidates")
def plan_cleanup_candidates(
    proposed: str = typer.Option(..., "--proposed", help="Path to primitives.proposed.json."),
    detail: str = typer.Option(..., "--detail", help="Path to usage_detail.json from `read color-usage-detail`."),
    out: str = typer.Option(
        str(_TOKENS_DIR / "primitives.cleanup.json"),
        "--out",
        help="Output path (default: tokens/primitives.cleanup.json).",
    ),
    threshold: int = typer.Option(3, "--threshold", min=0, help="Min use_count to keep a color (default: 3)."),
) -> None:
    """Enrich proposed colors with use_count; tag low-use entries as review_low_use."""
    proposed_path = Path(proposed).resolve()
    if not proposed_path.exists():
        raise typer.BadParameter(f"Proposed file not found: {proposed_path}")

    try:
        proposed_data = json.loads(proposed_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read proposed file: {e}")

    if "colors" not in proposed_data:
        raise typer.BadParameter("Proposed file missing required key: 'colors'")

    detail_path = Path(detail).resolve()
    if not detail_path.exists():
        raise typer.BadParameter(f"Detail file not found: {detail_path}")

    try:
        detail_data = json.loads(detail_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read detail file: {e}")

    enriched = _apply_use_counts(proposed_data["colors"], detail_data)
    tagged = _cleanup_candidates(enriched, threshold=threshold)

    keep_count = sum(1 for e in tagged if e["cleanup_tag"] == "keep")
    review_count = sum(1 for e in tagged if e["cleanup_tag"] == "review_low_use")

    typer.echo(f"\nCleanup Summary (threshold={threshold})")
    typer.echo(f"  Total colors: {len(tagged)}")
    typer.echo(f"  Keep:             {keep_count}")
    typer.echo(f"  Review low use:   {review_count}")

    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing file: {out_path}")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_proposed_file": str(proposed_path),
        "source_detail_file": str(detail_path),
        "threshold": threshold,
        "summary": {
            "total": len(tagged),
            "keep": keep_count,
            "review_low_use": review_count,
        },
        "colors": tagged,
    }

    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nCleanup proposal written to: {out_path}")


@plan_app.command("primitive-colors-from-project")
def plan_primitive_colors_from_project(
    usage: str = typer.Option(..., "--usage", help="Path to usage JSON written by `read color-usage-summary`."),
    out: str = typer.Option(
        str(_TOKENS_DIR / "primitives.proposed.json"),
        "--out",
        help="Output path for proposal (default: tokens/primitives.proposed.json).",
    ),
) -> None:
    """Classify colors from usage scan and write a primitive color proposal."""
    usage_path = Path(usage).resolve()
    if not usage_path.exists():
        raise typer.BadParameter(f"Usage file not found: {usage_path}")

    try:
        data = json.loads(usage_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read usage file: {e}")

    for key in ("node_colors", "paint_styles", "primitive_variables"):
        if key not in data:
            raise typer.BadParameter(f"Usage file missing required key: {key!r}")

    prim_seen, style_seen, dup_prim, dup_style, warnings = _build_color_lookups(
        data["primitive_variables"],
        data["paint_styles"],
    )
    for w in warnings:
        typer.echo(w)

    sorted_colors, matched, paint_style_count, new_candidates, unique = _classify_and_count(
        data["node_colors"],
        prim_lookup=prim_seen,
        style_lookup=style_seen,
        dup_prim_hexes=dup_prim,
        dup_style_hexes=dup_style,
    )

    # Console summary
    scanned_nodes = data.get("scanned_nodes", "?")
    scanned_pages = data.get("scanned_pages", "?")
    for line in _fmt_color_usage_summary_lines(
        scanned_nodes=scanned_nodes,
        scanned_pages=scanned_pages,
        unique=unique,
        matched=matched,
        paint_style_count=paint_style_count,
        new_candidates=new_candidates,
    ):
        typer.echo(line)
    typer.echo(f"\nTop colors by usage:")
    for line in _fmt_top_color_lines(sorted_colors):
        typer.echo(line)

    # Write proposal
    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing proposal: {out_path}")

    proposal = _build_primitive_color_plan(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        usage_path=usage_path,
        scanned_pages=scanned_pages,
        scanned_nodes=scanned_nodes,
        unique=unique,
        matched=matched,
        paint_style_count=paint_style_count,
        new_candidates=new_candidates,
        sorted_colors=sorted_colors,
    )

    out_path.write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nProposal written to: {out_path}")


_MERGE_OVERRIDES_PATH = _TOKENS_DIR / "overrides.merge.json"


@plan_app.command("validate-normalized")
def plan_validate_normalized(
    normalized: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--normalized",
        help="Path to normalized JSON written by `plan primitive-colors-normalized`.",
    ),
) -> None:
    """Validate primitives.normalized.json before sync. Exits non-zero on any error."""
    normalized_path = Path(normalized).resolve()
    if not normalized_path.exists():
        typer.echo(f"ERROR: file not found: {normalized_path}", err=True)
        raise typer.Exit(1)

    try:
        data = json.loads(normalized_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read file: {e}", err=True)
        raise typer.Exit(1)

    if "colors" not in data:
        typer.echo("ERROR: missing required key 'colors'", err=True)
        raise typer.Exit(1)

    errors = _validate_normalized(data["colors"])
    if errors:
        for msg in errors:
            typer.echo(f"ERROR: {msg}", err=True)
        typer.echo(f"\n{len(errors)} error(s) found. Fix before syncing.", err=True)
        raise typer.Exit(1)

    typer.echo(f"OK: {len(data['colors'])} entries valid.")


@plan_app.command("primitive-colors-normalized")
def plan_primitive_colors_normalized(
    proposal: str = typer.Option(..., "--proposed", help="Path to proposal JSON written by `plan primitive-colors-from-project`."),
    overrides: str = typer.Option(
        str(_TOKENS_DIR / "overrides.normalized.json"),
        "--overrides",
        help="Path to overrides JSON (hex→name map). Default: tokens/overrides.normalized.json.",
    ),
    merge: str = typer.Option(
        str(_MERGE_OVERRIDES_PATH),
        "--merge",
        help="Path to merge map JSON (source_hex→canonical_hex). Default: tokens/overrides.merge.json.",
    ),
    out: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--out",
        help="Output path for normalized proposal (default: tokens/primitives.normalized.json).",
    ),
) -> None:
    """Assign auto color names to new_candidate colors; apply overrides; write normalized proposal."""
    proposal_path = Path(proposal).resolve()
    if not proposal_path.exists():
        raise typer.BadParameter(f"Proposal file not found: {proposal_path}")

    try:
        proposal_data = json.loads(proposal_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read proposal file: {e}")

    if "colors" not in proposal_data:
        raise typer.BadParameter("Proposal file missing required key: 'colors'")

    overrides_path = Path(overrides).resolve()
    if overrides_path.exists():
        try:
            overrides_map: dict[str, str] = json.loads(overrides_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise typer.BadParameter(f"Failed to read overrides file: {e}")
    else:
        overrides_map = {}

    merge_path = Path(merge).resolve()
    if merge_path.exists():
        try:
            merge_map: dict[str, str] = json.loads(merge_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise typer.BadParameter(f"Failed to read merge file: {e}")
    else:
        merge_map = {}

    candidates = [c for c in proposal_data["colors"] if c["status"] == "new_candidate"]

    if merge_map:
        candidate_hexes = {c["hex"] for c in candidates}
        merge_errors = _validate_merge_map(merge_map, candidate_hexes)
        if merge_errors:
            for msg in merge_errors:
                typer.echo(f"ERROR (merge map): {msg}", err=True)
            raise typer.BadParameter(f"Merge map has {len(merge_errors)} error(s). Fix before continuing.")

        candidates, excluded_count = _apply_merge_map(candidates, merge_map)
    else:
        excluded_count = 0

    normalized = _build_normalized_entries(candidates, overrides=overrides_map)

    override_count = sum(1 for e in normalized if e["final_name"] != e["auto_name"])

    typer.echo(f"\nNormalization Summary")
    typer.echo(f"  Candidates: {len(normalized)}")
    typer.echo(f"  Overrides applied: {override_count}")
    if merge_map:
        typer.echo(_fmt_merge_summary_line(
            before=len(normalized) + excluded_count,
            merged=excluded_count,
            after=len(normalized),
        ))
    typer.echo(f"\nNormalized names:")
    for line in _fmt_group_block(normalized):
        typer.echo(line)
    if override_count:
        typer.echo("  (* = override applied)")

    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing file: {out_path}")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_proposal_file": str(proposal_path),
        "source_overrides_file": str(overrides_path),
        "source_merge_file": str(merge_path),
        "summary": {
            "candidates_before_merge": len(candidates) + excluded_count,
            "merged_excluded": excluded_count,
            "candidates": len(normalized),
            "overrides_applied": override_count,
        },
        "colors": normalized,
    }

    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nNormalized proposal written to: {out_path}")


@plan_app.command("deduplicate-primitives")
def plan_deduplicate_primitives(
    cleanup: str = typer.Option(..., "--cleanup", help="Path to primitives.cleanup.json."),
    out: str = typer.Option(
        str(_TOKENS_DIR / "primitives.dedup.json"),
        "--out",
        help="Output path (default: tokens/primitives.dedup.json).",
    ),
    threshold: float = typer.Option(
        0.01,
        "--threshold",
        min=0.0,
        max=1.0,
        help="HSL delta threshold for near-duplicate detection (default: 0.01).",
    ),
) -> None:
    """Group visually similar colors and recommend a canonical hex per cluster.

    Reads primitives.cleanup.json. Writes primitives.dedup.json as a proposal
    only — never modifies Figma or any token file.
    """
    cleanup_path = Path(cleanup).resolve()
    if not cleanup_path.exists():
        raise typer.BadParameter(f"Cleanup file not found: {cleanup_path}")

    try:
        cleanup_data = json.loads(cleanup_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read cleanup file: {e}")

    if "colors" not in cleanup_data:
        raise typer.BadParameter("Cleanup file missing required key: 'colors'")

    colors = cleanup_data["colors"]
    groups = _deduplicate_primitives(colors, threshold=threshold)

    singleton_count = sum(1 for g in groups if g["recommendation"] == "keep")
    merge_group_count = sum(1 for g in groups if g["recommendation"] == "merge")
    merge_member_count = sum(len(g["members"]) for g in groups if g["recommendation"] == "merge")

    typer.echo(f"\nDeduplication Summary (threshold={threshold})")
    typer.echo(f"  Input colors:     {len(colors)}")
    typer.echo(f"  Unique groups:    {len(groups)}")
    typer.echo(f"  Singletons:       {singleton_count}")
    typer.echo(f"  Merge groups:     {merge_group_count}  ({merge_member_count} colors affected)")

    if merge_group_count:
        typer.echo(f"\nPossible near-duplicate clusters:")
        for g in groups:
            if g["recommendation"] != "merge":
                continue
            members_str = ", ".join(
                f"{m['hex']} (×{m['use_count']})" for m in g["members"]
            )
            typer.echo(f"  → keep {g['canonical_hex']}  |  cluster: {members_str}")

    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing file: {out_path}")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_cleanup_file": str(cleanup_path),
        "hsl_delta_threshold": threshold,
        "summary": {
            "input_colors": len(colors),
            "unique_groups": len(groups),
            "singletons": singleton_count,
            "merge_groups": merge_group_count,
            "merge_members_affected": merge_member_count,
        },
        "groups": groups,
    }

    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nDedup proposal written to: {out_path}")


_MERGE_PROPOSED_PATH = _TOKENS_DIR / "overrides.merge.proposed.json"



@plan_app.command("suggest-merge-overrides")
def plan_suggest_merge_overrides(
    cleanup: str = typer.Option(
        str(_TOKENS_DIR / "primitives.cleanup.json"),
        "--cleanup",
        help="Path to primitives.cleanup.json (default: tokens/primitives.cleanup.json).",
    ),
    dedup: str = typer.Option(
        str(_TOKENS_DIR / "primitives.dedup.json"),
        "--dedup",
        help="Path to primitives.dedup.json (default: tokens/primitives.dedup.json).",
    ),
    out: str = typer.Option(
        str(_MERGE_PROPOSED_PATH),
        "--out",
        help="Output path (default: tokens/overrides.merge.proposed.json).",
    ),
) -> None:
    """Suggest source→canonical merge overrides for groups with more than 9 candidates.

    Reads primitives.cleanup.json and primitives.dedup.json.
    Writes tokens/overrides.merge.proposed.json — never writes overrides.merge.json directly.
    """
    cleanup_path = Path(cleanup).resolve()
    if not cleanup_path.exists():
        raise typer.BadParameter(f"Cleanup file not found: {cleanup_path}")

    try:
        cleanup_data = json.loads(cleanup_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read cleanup file: {e}")

    if "colors" not in cleanup_data:
        raise typer.BadParameter("Cleanup file missing required key: 'colors'")

    dedup_path = Path(dedup).resolve()
    if dedup_path.exists():
        try:
            dedup_data = json.loads(dedup_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise typer.BadParameter(f"Failed to read dedup file: {e}")
        # Collect source hexes already covered by dedup merge recommendations
        dedup_covered: set[str] = set()
        for group in dedup_data.get("groups", []):
            if group.get("recommendation") == "merge":
                canonical_hex = group["canonical_hex"]
                for m in group["members"]:
                    if m["hex"] != canonical_hex:
                        dedup_covered.add(m["hex"])
    else:
        dedup_data = None
        dedup_covered = set()

    colors = cleanup_data["colors"]
    suggestions = _suggest_merge_overrides(colors, dedup_covered=dedup_covered)

    # Count groups actually analyzed (non-fixed candidates, grouped)
    groups_seen: dict[str, int] = {}
    for c in colors:
        if c["hex"].lower() in _FORBIDDEN_MERGE_HEXES:
            continue
        g = _hex_to_group(c["hex"])
        groups_seen[g] = groups_seen.get(g, 0) + 1
    overflowing = sum(1 for v in groups_seen.values() if v > 9)

    typer.echo(f"\nMerge Suggestion Summary")
    typer.echo(f"  Groups analyzed:    {len(groups_seen)}")
    typer.echo(f"  Overflowing groups: {overflowing}")
    typer.echo(f"  Merges suggested:   {len(suggestions)}")
    if dedup_covered:
        typer.echo(f"  Dedup-covered (excluded): {len(dedup_covered)}")

    if suggestions:
        typer.echo("")
        for line in _fmt_merge_table(suggestions):
            typer.echo(line)
    else:
        typer.echo("\nNo merges needed — all groups have 9 or fewer candidates.")

    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing file: {out_path}")

    merge_map = {s["source_hex"]: s["canonical_hex"] for s in suggestions}

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_cleanup_file": str(cleanup_path),
        "source_dedup_file": str(dedup_path),
        "summary": {
            "groups_analyzed": len(groups_seen),
            "overflowing_groups": overflowing,
            "merges_suggested": len(suggestions),
        },
        "merges": suggestions,
        "merge_map": merge_map,
    }

    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nMerge suggestion written to: {out_path}")



@plan_app.command("audit-palette")
def plan_audit_palette(
    normalized: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--normalized",
        help="Path to primitives.normalized.json (default: tokens/primitives.normalized.json).",
    ),
) -> None:
    """Read-only audit of primitives.normalized.json: groups, missing slots, suspicious colors."""
    normalized_path = Path(normalized).resolve()
    if not normalized_path.exists():
        typer.echo(f"ERROR: file not found: {normalized_path}", err=True)
        raise typer.Exit(1)

    try:
        data = json.loads(normalized_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read file: {e}", err=True)
        raise typer.Exit(1)

    if "colors" not in data:
        typer.echo("ERROR: missing required key 'colors'", err=True)
        raise typer.Exit(1)

    audit = _audit_palette(data["colors"])

    typer.echo(f"\nPalette audit  ({audit['total']} tokens)")

    for group, scales in audit["groups"].items():
        scale_str = "  ".join(str(s) for s in scales)
        typer.echo(f"  {group:<8}  {len(scales)}    slots: {scale_str}")

    if audit["fixed"]:
        typer.echo(f"  Fixed: {', '.join(audit['fixed'])}")

    if audit["missing"]:
        typer.echo("\nMissing scale slots:")
        for group, absent in sorted(audit["missing"].items()):
            typer.echo(f"  {group:<8}  missing: {', '.join(str(s) for s in absent)}")

    if audit["suspicious"]:
        typer.echo("\nSuspicious (low-chroma, not gray):")
        for s in audit["suspicious"]:
            typer.echo(f"  {s['hex']}  group={s['group']}  chroma={s['chroma']}")
    else:
        typer.echo("\nSuspicious (low-chroma, not gray): none")


@plan_app.command("semantic-tokens-normalized")
def plan_semantic_tokens_normalized(
    seed: str = typer.Option(
        str(_TOKENS_DIR / "semantics.seed.json"),
        "--seed",
        help="Path to hand-authored semantics seed JSON (semantic_name → primitive_name).",
    ),
    primitives: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--primitives",
        help="Path to primitives.normalized.json (must already exist and validate).",
    ),
    overrides: str = typer.Option(
        str(_TOKENS_DIR / "overrides.semantic.normalized.json"),
        "--overrides",
        help="Path to semantic overrides JSON. Stubbed as {} if missing.",
    ),
    out: str = typer.Option(
        str(_TOKENS_DIR / "semantics.normalized.json"),
        "--out",
        help="Output path for semantics.normalized.json.",
    ),
) -> None:
    """Resolve semantic seed + overrides into a validated flat name→primitive map.

    Validates inline; fails fast on first error and writes nothing on failure.
    """
    seed_path = Path(seed).resolve()
    primitives_path = Path(primitives).resolve()
    overrides_path = Path(overrides).resolve()
    out_path = Path(out).resolve()

    if not seed_path.exists():
        typer.echo(
            f"ERROR: seed file not found: {seed_path}\n"
            f"Create it as a flat JSON object: {{\"color/<role>/<state>\": \"color/<group>/<scale>\"}}",
            err=True,
        )
        raise typer.Exit(1)
    if not primitives_path.exists():
        typer.echo(
            f"ERROR: primitives file not found: {primitives_path}\n"
            f"Run `plan primitive-colors-normalized` first.",
            err=True,
        )
        raise typer.Exit(1)

    if not overrides_path.exists():
        overrides_path.parent.mkdir(parents=True, exist_ok=True)
        overrides_path.write_text("{}\n", encoding="utf-8")

    try:
        seed_data = json.loads(seed_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read seed: {e}", err=True)
        raise typer.Exit(1)

    try:
        primitives_data = json.loads(primitives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read primitives: {e}", err=True)
        raise typer.Exit(1)

    try:
        overrides_data = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read overrides: {e}", err=True)
        raise typer.Exit(1)

    primitives_list = primitives_data.get("colors") if isinstance(primitives_data, dict) else None
    if not isinstance(primitives_list, list):
        typer.echo(
            f"ERROR: {primitives_path} missing required 'colors' list.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        resolved = _build_and_validate_semantic_normalized(
            seed_data, primitives_list, overrides_data
        )
    except ValueError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(1)

    sorted_resolved = {k: resolved[k] for k in sorted(resolved.keys())}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(sorted_resolved, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"OK: {len(sorted_resolved)} semantic token(s) written to {out_path}")


@plan_app.command("suggest-semantic-tokens")
def plan_suggest_semantic_tokens(
    primitives: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--primitives",
        help="Path to primitives.normalized.json (default: tokens/primitives.normalized.json).",
    ),
    out: str | None = typer.Option(
        None,
        "--out",
        help=(
            "Optional path to write suggestions as JSON. Prints to stdout when omitted. "
            "Never writes semantics.seed.json. "
            "[EXPERIMENTAL] Output is a starting point only — review before using."
        ),
    ),
) -> None:
    """[EXPERIMENTAL] Suggest semantic token assignments from a normalized primitive palette.

    Uses luminance-based heuristics to propose initial mappings. Output is advisory only —
    review and copy relevant entries into semantics.seed.json manually.
    Never writes semantics.seed.json or semantics.normalized.json.
    """
    primitives_path = Path(primitives).resolve()
    if not primitives_path.exists():
        typer.echo(f"ERROR: primitives file not found: {primitives_path}", err=True)
        raise typer.Exit(1)

    try:
        primitives_data = json.loads(primitives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read primitives: {e}", err=True)
        raise typer.Exit(1)

    primitives_list = primitives_data.get("colors") if isinstance(primitives_data, dict) else None
    if not isinstance(primitives_list, list):
        typer.echo("ERROR: primitives file missing required 'colors' list.", err=True)
        raise typer.Exit(1)

    suggestions = _suggest_semantic_tokens(primitives_list)

    typer.echo(f"\nSemantic token suggestions ({len(suggestions)} token(s)):")
    for name, primitive in sorted(suggestions.items()):
        typer.echo(f"  {name:<36}  →  {primitive}")

    if not suggestions:
        typer.echo("  (none — no qualifying gray primitives found)")

    if out is not None:
        out_path = Path(out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            typer.echo(f"\nWARNING: overwriting existing file: {out_path}")
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_primitives_file": str(primitives_path),
            "suggestions": suggestions,
        }
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"\nSuggestions written to: {out_path}")


@plan_app.command("suggest-semantic-tokens-contextual")
def plan_suggest_semantic_tokens_contextual(
    context: str = typer.Option(
        str(_TOKENS_DIR / "color_usage_context.json"),
        "--context",
        help="Path to color_usage_context.json from `read color-usage-context`.",
    ),
    primitives: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--primitives",
        help="Path to primitives.normalized.json.",
    ),
    out: str = typer.Option(
        str(_TOKENS_DIR / "semantics.contextual.json"),
        "--out",
        help=(
            "Output path for experimental suggestions (default: tokens/semantics.contextual.json). "
            "[EXPERIMENTAL] Never set to semantics.seed.json or semantics.normalized.json."
        ),
    ),
) -> None:
    """[EXPERIMENTAL] Generate contextual semantic token suggestions from enriched Figma usage data.

    Uses multi-signal analysis (fill/stroke/text ratios, confidence scoring) to propose
    mappings. Output is advisory only — review and copy relevant entries into
    semantics.seed.json manually.
    Reads color_usage_context.json and primitives.normalized.json.
    Writes a proposal to tokens/semantics.contextual.json — never writes
    semantics.seed.json or semantics.normalized.json.
    """
    context_path = Path(context).resolve()
    if not context_path.exists():
        typer.echo(
            f"ERROR: context file not found: {context_path}\n"
            f"Run `read color-usage-context --out tokens/color_usage_context.json` first.",
            err=True,
        )
        raise typer.Exit(1)

    primitives_path = Path(primitives).resolve()
    if not primitives_path.exists():
        typer.echo(
            f"ERROR: primitives file not found: {primitives_path}\n"
            f"Run `plan primitive-colors-normalized` first.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        context_data = json.loads(context_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read context file: {e}", err=True)
        raise typer.Exit(1)

    if not isinstance(context_data, list):
        typer.echo("ERROR: context file must be a JSON array.", err=True)
        raise typer.Exit(1)

    try:
        primitives_data = json.loads(primitives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read primitives file: {e}", err=True)
        raise typer.Exit(1)

    primitives_list = primitives_data.get("colors") if isinstance(primitives_data, dict) else None
    if not isinstance(primitives_list, list):
        typer.echo("ERROR: primitives file missing required 'colors' list.", err=True)
        raise typer.Exit(1)

    suggestions = _suggest_semantic_tokens_contextual(context_data, primitives_list)

    typer.echo(f"\nContextual semantic suggestions ({len(suggestions)} token(s)):\n")
    if suggestions:
        col_sem  = max(len(s["semantic_name"])  for s in suggestions)
        col_prim = max(len(s["primitive_name"]) for s in suggestions)
        typer.echo(
            f"  {'semantic_name':<{col_sem}}  {'primitive_name':<{col_prim}}  confidence"
        )
        typer.echo(f"  {'-' * col_sem}  {'-' * col_prim}  ----------")
        for s in suggestions:
            warn_flag = "  [!]" if s["warnings"] else ""
            typer.echo(
                f"  {s['semantic_name']:<{col_sem}}  {s['primitive_name']:<{col_prim}}"
                f"  {s['confidence']}{warn_flag}"
            )
    else:
        typer.echo("  (none — no qualifying colors found in context)")

    out_path = Path(out).resolve()

    # Guard: experimental suggestion commands must never overwrite production seed files.
    _PROTECTED_NAMES = {"semantics.seed.json", "semantics.normalized.json"}
    if out_path.name in _PROTECTED_NAMES:
        typer.echo(
            f"ERROR: --out {out_path} targets a protected production file.\n"
            "Experimental suggestions must not overwrite semantics.seed.json or "
            "semantics.normalized.json. Use a different output path (e.g. semantics.contextual.json).",
            err=True,
        )
        raise typer.Exit(1)

    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing file: {out_path}")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_context_file": str(context_path),
        "source_primitives_file": str(primitives_path),
        "suggestions": suggestions,
    }

    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nContextual suggestions written to: {out_path}")


@plan_app.command("semantic-sync-dry-run")
def plan_semantic_sync_dry_run(
    semantics: str = typer.Option(
        str(_TOKENS_DIR / "semantics.normalized.json"),
        "--semantics",
        help="Path to semantics.normalized.json.",
    ),
    primitives: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--primitives",
        help="Path to primitives.normalized.json.",
    ),
) -> None:
    """Simulate semantic variable sync without writing to Figma.

    Reads semantics.normalized.json and primitives.normalized.json, verifies
    every semantic alias resolves to a known primitive, and prints the planned
    create operations. Exits non-zero if any primitive is missing.
    """
    semantics_path = Path(semantics).resolve()
    primitives_path = Path(primitives).resolve()

    if not semantics_path.exists():
        typer.echo(f"ERROR: semantics file not found: {semantics_path}", err=True)
        raise typer.Exit(1)
    if not primitives_path.exists():
        typer.echo(f"ERROR: primitives file not found: {primitives_path}", err=True)
        raise typer.Exit(1)

    try:
        semantics_data = json.loads(semantics_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read semantics: {e}", err=True)
        raise typer.Exit(1)

    try:
        primitives_data = json.loads(primitives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read primitives: {e}", err=True)
        raise typer.Exit(1)

    primitives_list = primitives_data.get("colors") if isinstance(primitives_data, dict) else None
    if not isinstance(primitives_list, list):
        typer.echo("ERROR: primitives file missing required 'colors' list.", err=True)
        raise typer.Exit(1)

    primitive_names = {e["final_name"] for e in primitives_list if isinstance(e.get("final_name"), str)}

    creates: list[tuple[str, str]] = []
    errors: list[str] = []

    for name, primitive in sorted(semantics_data.items()):
        if primitive in primitive_names:
            creates.append((name, primitive))
        else:
            errors.append(f"{name}: primitive {primitive!r} not found in primitives.normalized.json")

    typer.echo("\nSemantic sync dry-run:\n")
    typer.echo("  create:")
    if creates:
        col = max(len(n) for n, _ in creates)
        for name, primitive in creates:
            typer.echo(f"    {name:<{col}}  → alias {primitive}")
    else:
        typer.echo("    (none)")

    if errors:
        typer.echo("\n  errors:")
        for msg in errors:
            typer.echo(f"    {msg}")
        raise typer.Exit(1)


@plan_app.command("suggest-primitive-seeds")
def plan_suggest_primitive_seeds(
    usage: str = typer.Option(..., "--usage", help="Path to raw usage JSON written by `read primitive-usage`."),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir", help="Directory where <type>.suggested.json files are written."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """[EXPERIMENTAL] Suggest primitive seed entries from real Figma data.

    Reads raw primitive usage (output of `read primitive-usage`) and writes
    one tokens/<type>.suggested.json per type. Seed files are never modified.
    Output is advisory only — review and copy selected entries manually.
    """
    from suggest_primitives import suggest_primitive_entries
    from primitive_types import PRIMITIVE_TYPES

    usage_path = Path(usage).resolve()
    if not usage_path.exists():
        typer.echo(f"ERROR: usage file not found: {usage_path}", err=True)
        raise typer.Exit(1)

    try:
        raw = json.loads(usage_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read usage file: {e}", err=True)
        raise typer.Exit(1)

    out_dir = Path(tokens_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    for type_key in PRIMITIVE_TYPES:
        entries = suggest_primitive_entries(type_key, raw)
        if not entries:
            skipped += 1
            if not quiet:
                typer.echo(f"  skip  {type_key} (no data)")
            continue

        out_path = out_dir / f"{type_key}.suggested.json"
        out_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1
        if not quiet:
            typer.echo(f"  wrote {type_key}.suggested.json ({len(entries)} entries)")

    typer.echo(f"\nDone. {written} suggestion file(s) written to {out_dir}, {skipped} type(s) had no data.")
    typer.echo("Review the .suggested.json files. Copy selected entries (without use_count) into the seed files manually.")


@plan_app.command("validate-primitives")
def plan_validate_primitives(
    type_key: str = typer.Argument(..., help="Token type: spacing, radius, font-size, etc."),
    seed_file: str | None = typer.Option(None, "--seed-file", help="Path to seed JSON. Defaults to tokens/<type>.seed.json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Validate a primitive token seed file."""
    from validate_primitives import validate_primitive_seed

    path = Path(seed_file) if seed_file else Path("tokens") / f"{type_key}.seed.json"
    if not path.exists():
        typer.echo(f"Seed file not found: {path}", err=True)
        raise typer.Exit(1)

    entries = json.loads(path.read_text())
    errors = validate_primitive_seed(type_key, entries)

    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}")
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"✓ {type_key} seed is valid ({len(entries)} entries)")


@plan_app.command("validate-semantic-primitives")
def plan_validate_semantic_primitives(
    semantic_file: str | None = typer.Option(None, "--semantic-file"),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Validate the semantic primitive seed file against all loaded primitive seeds."""
    from validate_semantic_primitives import validate_semantic_primitives
    from primitive_types import PRIMITIVE_TYPES

    tokens_path = Path(tokens_dir)
    sem_path = Path(semantic_file) if semantic_file else tokens_path / "primitives-semantic.seed.json"

    if not sem_path.exists():
        typer.echo(f"Semantic seed file not found: {sem_path}", err=True)
        raise typer.Exit(1)

    semantic = json.loads(sem_path.read_text())

    # Load all primitive seeds present in tokens_dir
    primitive_seeds: dict[str, list[dict]] = {}
    for type_key in PRIMITIVE_TYPES:
        seed_path = tokens_path / f"{type_key}.seed.json"
        if seed_path.exists():
            primitive_seeds[type_key] = json.loads(seed_path.read_text())

    errors = validate_semantic_primitives(semantic, primitive_seeds)
    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}")
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"✓ Semantic primitives valid ({len(semantic)} entries)")


@plan_app.command("generate-text-styles")
def plan_generate_text_styles(
    config_file: str = typer.Option("tokens/typography/config.json", "--config"),
    scale_file: str = typer.Option("tokens/typography/scale.json", "--scale"),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir"),
    out_file: str = typer.Option("tokens/typography/text-styles.generated.json", "--out"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Generate text-styles.generated.json from config.json + scale.json + primitive seeds."""
    config = json.loads(Path(config_file).read_text())
    scale = json.loads(Path(scale_file).read_text())

    shared = config["shared"]
    weights = config["weights"]
    roles = config["roles"]

    styles = []
    for role, sizes in roles.items():
        for size in sizes:
            scale_entry = scale.get(role, {}).get(size)
            if scale_entry is None:
                typer.echo(f"ERROR: scale missing entry for {role}/{size}", err=True)
                raise typer.Exit(1)
            for weight in weights:
                style = {
                    "name": f"typography/{role}/{size}/{weight}",
                    "fontFamily": shared["fontFamily"],
                    "fontSize": scale_entry["fontSize"],
                    "fontWeight": f"font-weight/font-weight-{weight}",
                    "lineHeight": scale_entry["lineHeight"],
                    "letterSpacing": shared["letterSpacing"],
                }
                styles.append(style)

    output = {
        "$schema": "composable-typography/v1",
        "$generated": True,
        "$source": [config_file, scale_file],
        "$deprecated": ["tokens/text-styles.seed.json"],
        "styles": styles,
    }

    out_path = Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")

    if not quiet:
        typer.echo(f"✓ Generated {len(styles)} text styles → {out_file}")


# Token-ref prefix required for each field in a text style entry.
_TOKEN_REF_PREFIXES: dict[str, str] = {
    "fontFamily": "font-family/",
    "fontSize": "font-size/",
    "fontWeight": "font-weight/",
    "lineHeight": "line-height/",
    "letterSpacing": "letter-spacing/",
}

_EXPECTED_STYLES = 24


def _validate_text_styles_data(data: dict) -> list[str]:
    """Pure validator — returns a list of error strings (empty = valid)."""
    issues: list[str] = []

    if not data.get("$generated"):
        issues.append('$generated must be true')
        return issues  # fail-fast: rest of checks require valid structure

    styles = data.get("styles", [])

    if len(styles) != _EXPECTED_STYLES:
        issues.append(f'styles count is {len(styles)}, expected {_EXPECTED_STYLES}')
        return issues

    seen_names: set[str] = set()
    for style in styles:
        name = style.get("name", "")

        # name format: typography/{role}/{size}/{weight}
        parts = name.split("/")
        if len(parts) != 4 or parts[0] != "typography":
            issues.append(f'invalid name format: "{name}" (expected typography/{{role}}/{{size}}/{{weight}})')

        if name in seen_names:
            issues.append(f'duplicate name: "{name}"')
        seen_names.add(name)

        for field, expected_prefix in _TOKEN_REF_PREFIXES.items():
            value = style.get(field)
            if not isinstance(value, str):
                issues.append(f'"{name}": {field} is a raw {type(value).__name__} — must be a token ref')
            elif not value.startswith(expected_prefix):
                issues.append(f'"{name}": {field} "{value}" must start with "{expected_prefix}"')

    return issues


@plan_app.command("validate-text-styles")
def plan_validate_text_styles(
    file: str = typer.Option(
        "tokens/typography/text-styles.generated.json",
        "--file",
        help="Path to text-styles.generated.json",
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Validate tokens/typography/text-styles.generated.json for correctness."""
    path = Path(file)
    if not path.exists():
        typer.echo(f"ERROR: file not found: {path}")
        raise typer.Exit(1)

    data = json.loads(path.read_text())
    issues = _validate_text_styles_data(data)

    if issues:
        for issue in issues:
            typer.echo(f"  FAIL: {issue}")
        raise typer.Exit(1)

    if not quiet:
        styles = data.get("styles", [])
        typer.echo(f"✓ PASS — {len(styles)} text styles valid, all values are token refs, no duplicates")
