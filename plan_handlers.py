"""Host-side planning commands — the `plan` sub-app.

All commands run entirely on the host. No Figma round-trips.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

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


_HEX_RE = __import__("re").compile(r"^#[0-9a-fA-F]{6}$")

_MERGE_OVERRIDES_PATH = _TOKENS_DIR / "overrides.merge.json"
_FORBIDDEN_MERGE_HEXES = frozenset({"#ffffff", "#000000"})


def _validate_merge_map(
    merge_map: dict[str, str],
    candidate_hexes: set[str],
) -> list[str]:
    """Validate overrides.merge.json. Returns list of error strings; empty = valid."""
    errors: list[str] = []
    for src, canonical in merge_map.items():
        if not _HEX_RE.match(src):
            errors.append(f"source_hex {src!r}: not a valid #rrggbb hex")
        if not _HEX_RE.match(canonical):
            errors.append(f"canonical_hex {canonical!r} (source={src!r}): not a valid #rrggbb hex")
        if src.lower() in _FORBIDDEN_MERGE_HEXES:
            errors.append(f"source_hex {src!r}: #ffffff and #000000 cannot be merge values")
        if canonical.lower() in _FORBIDDEN_MERGE_HEXES:
            errors.append(f"canonical_hex {canonical!r}: #ffffff and #000000 cannot be merge values")
        if _HEX_RE.match(src) and src not in candidate_hexes:
            errors.append(f"source_hex {src!r}: not found in candidates")
        if _HEX_RE.match(canonical) and canonical not in candidate_hexes:
            errors.append(f"canonical_hex {canonical!r} (source={src!r}): not found in candidates")
    return errors


def _apply_merge_map(
    candidates: list[dict],
    merge_map: dict[str, str],
) -> tuple[list[dict], int]:
    """Remove source hexes from candidates (canonical hexes remain).

    Returns (reduced_candidates, excluded_count).
    """
    source_hexes = set(merge_map.keys())
    reduced = [c for c in candidates if c["hex"] not in source_hexes]
    excluded = len(candidates) - len(reduced)
    return reduced, excluded


def _validate_normalized(colors: list[dict]) -> list[str]:
    """Return a list of error strings; empty means valid."""
    errors: list[str] = []
    required = ("hex", "candidate_name", "auto_name", "final_name")
    seen_final: dict[str, int] = {}

    for i, entry in enumerate(colors):
        ref = entry.get("hex") or f"entry[{i}]"

        for field in required:
            if field not in entry:
                errors.append(f"{ref}: missing required field '{field}'")

        hex_ = entry.get("hex", "")
        if hex_ and not _HEX_RE.match(hex_):
            errors.append(f"{ref}: 'hex' must be #rrggbb, got {hex_!r}")

        final = entry.get("final_name", "")
        if final:
            if not final.startswith("color/"):
                errors.append(f"{ref}: 'final_name' must start with 'color/', got {final!r}")
            elif final.startswith("color/candidate/"):
                errors.append(f"{ref}: 'final_name' must not start with 'color/candidate/', got {final!r}")

            if final in seen_final:
                errors.append(
                    f"{ref}: duplicate 'final_name' {final!r} (also used by entry[{seen_final[final]}])"
                )
            else:
                seen_final[final] = i

    return errors


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


def _suggest_merge_overrides(
    colors: list[dict],
    *,
    dedup_covered: set[str] | None = None,
) -> list[dict]:
    """Suggest source_hex→canonical_hex merges for color groups with more than 9 members.

    Returns a list of merge suggestion dicts:
      {source_hex, canonical_hex, group, hsl_distance, reason}

    Priority for picking which colors to merge out:
      1. review_low_use before keep
      2. lower use_count first
      3. hex string tiebreak (stable, deterministic)

    Canonical is the remaining group member nearest in HSL distance to the source;
    ties broken by higher use_count then hex string.

    #ffffff and #000000 are never source or canonical.
    dedup_covered: set of source hexes already handled by a dedup merge group —
    they are excluded from suggestion candidates (already covered upstream).
    """
    dedup_covered = dedup_covered or set()
    # Exclude both fixed colors and dedup-covered sources from group membership.
    # dedup_covered hexes are already handled upstream; treat them as absent.
    excluded_from_groups = _FORBIDDEN_MERGE_HEXES | {h.lower() for h in dedup_covered}

    # Build groups (same classification as _build_normalized_entries)
    groups: dict[str, list[dict]] = {}
    for c in colors:
        hex_ = c["hex"]
        if hex_.lower() in excluded_from_groups:
            continue
        group = _hex_to_group(hex_)
        groups.setdefault(group, []).append(c)

    suggestions: list[dict] = []

    for group_name, members in groups.items():
        if len(members) <= 9:
            continue

        # Sort by merge priority: review_low_use first, then lower use_count, then hex
        def _merge_priority(c: dict) -> tuple:
            tag_order = 0 if c.get("cleanup_tag") == "review_low_use" else 1
            return (tag_order, c["use_count"], c["hex"])

        remaining = sorted(members, key=_merge_priority)
        # How many to remove
        n_to_remove = len(members) - 9

        for _ in range(n_to_remove):
            source = remaining[0]
            remaining = remaining[1:]

            # Pick canonical: nearest remaining member in HSL space
            def _canonical_key(c: dict) -> tuple:
                return (_hsl_delta(source["hex"], c["hex"]), -c["use_count"], c["hex"])

            canonical = min(remaining, key=_canonical_key)
            dist = _hsl_delta(source["hex"], canonical["hex"])

            tag = source.get("cleanup_tag", "keep")
            reason = f"{tag}, use_count={source['use_count']}, nearest in group"

            suggestions.append({
                "source_hex": source["hex"],
                "canonical_hex": canonical["hex"],
                "group": group_name,
                "hsl_distance": round(dist, 6),
                "reason": reason,
            })

    return suggestions


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


# ---------------------------------------------------------------------------
# plan audit-palette
# ---------------------------------------------------------------------------

_ALL_SCALES = [100, 200, 300, 400, 500, 600, 700, 800, 900]
_LOW_CHROMA_THRESHOLD = 0.04


def _audit_palette(colors: list[dict]) -> dict:
    """Read-only analysis of a normalized color list.

    Returns:
      total         — int
      groups        — {group_name: [scale_int, ...]}  (sorted)
      fixed         — [label, ...]
      missing       — {group_name: [missing_scale_int, ...]}
      suspicious    — [{"hex": ..., "group": ..., "chroma": ...}, ...]
    """
    fixed_names = {"color/white": "white", "color/black": "black"}
    groups: dict[str, list[int]] = {}
    fixed: list[str] = []
    suspicious: list[dict] = []

    for e in colors:
        fname = e["final_name"]
        hex_ = e["hex"]
        if fname in fixed_names:
            fixed.append(fixed_names[fname])
            continue
        parts = fname.split("/")
        group = parts[1] if len(parts) >= 2 else "?"
        scale_str = parts[2] if len(parts) >= 3 else "0"
        scale = int(scale_str) if scale_str.isdigit() else 0
        groups.setdefault(group, []).append(scale)

        # Suspicious: non-gray color with low perceived chroma
        if group != "gray":
            hue, lightness, sat = _hex_to_hls(hex_)
            chroma = _perceived_chroma(sat, lightness)
            if chroma < _LOW_CHROMA_THRESHOLD:
                suspicious.append({"hex": hex_, "group": group, "chroma": round(chroma, 4)})

    missing: dict[str, list[int]] = {}
    for group, scales in groups.items():
        absent = [s for s in _ALL_SCALES if s not in scales]
        if absent:
            missing[group] = absent

    return {
        "total": len(colors),
        "groups": {g: sorted(s) for g, s in sorted(groups.items())},
        "fixed": sorted(fixed),
        "missing": missing,
        "suspicious": suspicious,
    }


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
