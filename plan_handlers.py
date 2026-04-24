"""Host-side planning commands — the `plan` sub-app.

All commands run entirely on the host. No Figma round-trips.
"""

import colorsys
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

plan_app = typer.Typer(no_args_is_help=True, help="Host-side planning and proposal commands.")

_TOKENS_DIR = Path(__file__).parent / "tokens"


def _build_lookup(
    items: list[dict],
    *,
    key: str,
    value: str,
    warn=None,
) -> dict[str, str]:
    """Build hex→name dict; first-seen wins; call warn(msg) on duplicates."""
    result: dict[str, str] = {}
    for item in items:
        k = item[key]
        v = item[value]
        if k in result:
            if warn:
                warn(f"WARNING: duplicate hex {k!r} — keeping {result[k]!r}, ignoring {v!r}")
        else:
            result[k] = v
    return result


_STATUS_ORDER = {"matched": 0, "paint_style": 1, "new_candidate": 2}

_HUE_GROUPS = [
    (0.0,  0.05, "red"),
    (0.05, 0.11, "orange"),
    (0.11, 0.20, "yellow"),
    (0.20, 0.46, "green"),
    (0.46, 0.52, "cyan"),
    (0.52, 0.69, "blue"),
    (0.69, 0.79, "violet"),
    (0.79, 0.86, "purple"),
    (0.86, 0.95, "pink"),
    (0.95, 1.01, "red"),   # wrap-around
]
_GRAY_SATURATION_THRESHOLD = 0.12
_SCALES = [100, 200, 300, 400, 500, 600, 700, 800, 900]

_FIXED_COLORS = {
    "#ffffff": "color/white",
    "#000000": "color/black",
}


def _hex_to_hls(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return colorsys.rgb_to_hls(r, g, b)  # (hue, lightness, saturation)


def _perceived_chroma(saturation: float, lightness: float) -> float:
    """Approximate perceptual chroma: HLS saturation × 2×L×(1-L) (the HLS 'C' factor).

    Near-white and near-black colors have a very small chroma range, so even a
    large HLS saturation value represents very little actual color.
    """
    return saturation * 2 * lightness * (1 - lightness)


def _color_group(hue: float, saturation: float, lightness: float = 0.5) -> str:
    if saturation < _GRAY_SATURATION_THRESHOLD:
        return "gray"
    # Very light near-neutral colors: HLS saturation is inflated at near-white
    # lightness. Use perceptual chroma to avoid classifying #f9fafb as blue.
    if _perceived_chroma(saturation, lightness) < 0.03:
        return "gray"
    for lo, hi, name in _HUE_GROUPS:
        if lo <= hue < hi:
            return name
    return "gray"


def _assign_scales(lightness_values: list[float]) -> list[int]:
    """Map N lightness values (same-group, in input order) → 100-900 scale integers.

    Lighter = lower scale number.  With fewer than 9 values, picks evenly-spaced
    slots from the nine-point range.  Guarantees unique output: if two inputs have
    identical lightness the tiebreaker is stable (index order) and a free slot is
    found by scanning forward then backward.

    Raises ValueError if n > 9 (only 9 scale slots exist).
    """
    n = len(lightness_values)
    if n == 0:
        return []
    if n == 1:
        return [500]
    if n > 9:
        raise ValueError(
            f"Cannot assign unique scale slots: group has more than 9 colors ({n} provided)"
        )

    # Sort by lightness descending (darker → higher scale number).
    # Tiebreak by original index (stable, deterministic).
    order = sorted(range(n), key=lambda i: (-lightness_values[i], i))

    # Assign evenly-spaced slot indices across [0, 8].
    raw_slot_indices = [round(i * 8 / (n - 1)) for i in range(n)]

    # Resolve slot collisions so every rank gets a distinct slot index.
    # Scan forward first, then backward; the two directions are checked
    # per delta so the nearest free slot wins.
    used: set[int] = set()
    resolved: list[int] = []
    for si in raw_slot_indices:
        if si not in used:
            used.add(si)
            resolved.append(si)
        else:
            found = None
            for delta in range(1, 9):
                if si + delta <= 8 and (si + delta) not in used:
                    found = si + delta
                    break
                if si - delta >= 0 and (si - delta) not in used:
                    found = si - delta
                    break
            # found is always set here: n ≤ 9 guarantees a free slot exists.
            used.add(found)
            resolved.append(found)

    result = [0] * n
    for rank, orig_idx in enumerate(order):
        result[orig_idx] = _SCALES[resolved[rank]]
    return result


# ---------------------------------------------------------------------------
# Formatting helpers (terminal output only — no effect on JSON artifacts)
# ---------------------------------------------------------------------------

def _fmt_group_block(normalized: list[dict]) -> list[str]:
    """Return human-readable grouped lines for a normalized color list.

    Output format:
        color / gray (9)
          100  #f9fafb
          ...
        Fixed
          white  #ffffff
          black  #000000
    """
    fixed_order = {"color/white": "white", "color/black": "black"}
    groups: dict[str, list[tuple[str, str]]] = {}  # group_name → [(scale_label, hex)]
    fixed: list[tuple[str, str]] = []

    for e in normalized:
        fname = e["final_name"]
        hex_ = e["hex"]
        if fname in fixed_order:
            fixed.append((fixed_order[fname], hex_))
            continue
        parts = fname.split("/")  # color / <group> / <scale>
        group = parts[1] if len(parts) >= 2 else "?"
        scale = parts[2] if len(parts) >= 3 else "?"
        groups.setdefault(group, []).append((scale, hex_))

    lines: list[str] = []
    for group, members in sorted(groups.items(), key=lambda x: ("" if x[0] == "gray" else x[0])):
        members_sorted = sorted(members, key=lambda x: (int(x[0]) if x[0].isdigit() else 9999))
        lines.append(f"  color / {group} ({len(members_sorted)})")
        for scale, hex_ in members_sorted:
            marker = ""
            # Mark overridden entries
            entry = next((e for e in normalized if e["hex"] == hex_), None)
            if entry and entry["final_name"] != entry["auto_name"]:
                marker = " *"
            lines.append(f"    {scale:<5}  {hex_}{marker}")

    if fixed:
        lines.append("  Fixed")
        for label, hex_ in sorted(fixed):
            lines.append(f"    {label:<7}  {hex_}")

    return lines


def _fmt_merge_summary_line(before: int, merged: int, after: int) -> str:
    return f"  Merge  before={before}  merged={merged}  after={after}"


def _fmt_merge_table(suggestions: list[dict]) -> list[str]:
    """Compact fixed-width table for merge suggestions."""
    if not suggestions:
        return []
    lines = ["  source     canonical   group   uses  reason"]
    for s in suggestions:
        use_count = s.get("use_count", s.get("hsl_distance", "?"))
        # Extract use_count from reason string if not a direct field
        reason = s.get("reason", "")
        import re as _re
        m = _re.search(r"use_count=(\d+)", reason)
        uses = m.group(1) if m else "?"
        lines.append(
            f"  {s['source_hex']}  → {s['canonical_hex']}"
            f"  {s['group']:<7}  {uses:<4}  {reason}"
        )
    return lines


def _build_normalized_entries(
    candidates: list[dict],
    *,
    overrides: dict[str, str],
) -> list[dict]:
    """Classify candidates into groups, assign scales, apply overrides.

    Fixed colors (#ffffff, #000000) are resolved before HSL grouping and
    are never assigned a scale slot.  Duplicate final_name values within
    a group cannot occur because _assign_scales guarantees unique slots.
    """
    auto_names: dict[str, str] = {}

    # Resolve fixed colors first; exclude them from group/scale logic.
    non_fixed = []
    for c in candidates:
        fixed = _FIXED_COLORS.get(c["hex"])
        if fixed is not None:
            auto_names[c["hex"]] = fixed
        else:
            non_fixed.append(c)

    groups: dict[str, list] = {}
    for idx, c in enumerate(non_fixed):
        hue, lightness, sat = _hex_to_hls(c["hex"])
        group = _color_group(hue, sat, lightness)
        groups.setdefault(group, []).append((idx, c, lightness))

    for group_name, members in groups.items():
        lightness_values = [m[2] for m in members]
        scales = _assign_scales(lightness_values)
        for (idx, c, _), scale in zip(members, scales):
            auto_names[c["hex"]] = f"color/{group_name}/{scale}"

    result = []
    for c in candidates:
        hex_ = c["hex"]
        auto = auto_names[hex_]
        final = overrides.get(hex_, auto)
        candidate_name = f"color/candidate/{hex_.lstrip('#')}"
        result.append({
            "hex": hex_,
            "candidate_name": candidate_name,
            "auto_name": auto,
            "final_name": final,
            "fill_count": c["fill_count"],
            "stroke_count": c["stroke_count"],
            "examples": c.get("examples", []),
        })
    return result


def _classify_colors(
    node_colors: list[dict],
    *,
    prim_lookup: dict[str, str],
    style_lookup: dict[str, str],
    dup_prim_hexes: set[str] | None = None,
    dup_style_hexes: set[str] | None = None,
) -> list[dict]:
    dup_prim_hexes = dup_prim_hexes or set()
    dup_style_hexes = dup_style_hexes or set()
    result = []
    for color in node_colors:
        hex_ = color["hex"]
        if hex_ in prim_lookup:
            status = "matched"
            primitive_name = prim_lookup[hex_]
            paint_style_name = None
            dup = hex_ in dup_prim_hexes
        elif hex_ in style_lookup:
            status = "paint_style"
            primitive_name = None
            paint_style_name = style_lookup[hex_]
            dup = hex_ in dup_style_hexes
        else:
            status = "new_candidate"
            primitive_name = None
            paint_style_name = None
            dup = False
        result.append({
            "hex": hex_,
            "fill_count": color["fill_count"],
            "stroke_count": color["stroke_count"],
            "status": status,
            "primitive_name": primitive_name,
            "paint_style_name": paint_style_name,
            "duplicate_warning": dup,
            "examples": color["examples"],
        })
    return result


def _sort_colors(colors: list[dict]) -> list[dict]:
    return sorted(
        colors,
        key=lambda c: (
            _STATUS_ORDER[c["status"]],
            -(c["fill_count"] + c["stroke_count"]),
            c["hex"],
        ),
    )


def _apply_use_counts(
    colors: list[dict],
    detail: list[dict],
) -> list[dict]:
    """Return copies of colors enriched with use_count from usage-detail data.

    Colors absent from detail receive use_count=0. Input lists are not mutated.
    """
    detail_lookup: dict[str, int] = {entry["hex"]: entry["use_count"] for entry in detail}
    return [{**c, "use_count": detail_lookup.get(c["hex"], 0)} for c in colors]


def _hsl_delta(hex_a: str, hex_b: str) -> float:
    """Perceptual HSL distance between two hex colors.

    Hue is treated as circular (max distance = 0.5). Returns a value in [0, 1].
    The three components are weighted: L×0.5, S×0.3, H×0.2 — lightness dominates
    because near-duplicate grays differ mainly in lightness, not hue.
    """
    ha, la, sa = _hex_to_hls(hex_a)
    hb, lb, sb = _hex_to_hls(hex_b)
    hue_diff = min(abs(ha - hb), 1.0 - abs(ha - hb))
    return (0.2 * hue_diff + 0.5 * abs(la - lb) + 0.3 * abs(sa - sb))


def _group_near_duplicates(
    colors: list[dict],
    *,
    threshold: float,
) -> list[list[dict]]:
    """Return groups of visually similar colors (HSL delta < threshold).

    Uses single-linkage clustering: two colors end up in the same group if any
    pair within the group is within threshold. Groups of 1 (singletons) are
    included so callers always get a complete partition.
    """
    n = len(colors)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            if _hsl_delta(colors[i]["hex"], colors[j]["hex"]) < threshold:
                union(i, j)

    buckets: dict[int, list[dict]] = {}
    for i, c in enumerate(colors):
        root = find(i)
        buckets.setdefault(root, []).append(c)

    return list(buckets.values())


def _deduplicate_primitives(
    colors: list[dict],
    *,
    threshold: float,
) -> list[dict]:
    """Group visually similar colors; recommend a canonical hex per group.

    Returns one entry per group. Each entry contains:
      - canonical_hex: the hex with the highest use_count (tie-broken by hex string)
      - members: all hexes in the group with their use_count and cleanup_tag
      - recommendation: 'keep' if singleton, 'merge' if multiple members
      - hsl_delta_threshold: the threshold used

    Input is not mutated. Never modifies Figma.
    """
    groups = _group_near_duplicates(colors, threshold=threshold)
    result = []
    for group in groups:
        canonical = max(group, key=lambda c: (c["use_count"], c["hex"]))
        recommendation = "keep" if len(group) == 1 else "merge"
        result.append({
            "canonical_hex": canonical["hex"],
            "recommendation": recommendation,
            "members": [
                {
                    "hex": c["hex"],
                    "use_count": c["use_count"],
                    "cleanup_tag": c.get("cleanup_tag"),
                }
                for c in sorted(group, key=lambda c: -c["use_count"])
            ],
        })
    result.sort(key=lambda e: (-len(e["members"]), -e["members"][0]["use_count"]))
    return result


def _cleanup_candidates(
    colors: list[dict],
    *,
    threshold: int,
) -> list[dict]:
    """Tag each color with cleanup_tag: 'keep' if use_count >= threshold, else 'review_low_use'.

    Input list is not mutated.
    """
    result = []
    for c in colors:
        tag = "keep" if c["use_count"] >= threshold else "review_low_use"
        result.append({**c, "cleanup_tag": tag})
    return result


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

    warnings: list[str] = []

    # Build lookups — track duplicate hexes for duplicate_warning flag
    prim_seen: dict[str, str] = {}
    dup_prim: set[str] = set()
    for item in data["primitive_variables"]:
        h = item["hex"]
        if h in prim_seen:
            msg = f"WARNING: duplicate hex {h!r} in primitive_variables — keeping {prim_seen[h]!r}, ignoring {item['name']!r}"
            warnings.append(msg)
            typer.echo(msg)
            dup_prim.add(h)
        else:
            prim_seen[h] = item["name"]

    style_seen: dict[str, str] = {}
    dup_style: set[str] = set()
    for item in data["paint_styles"]:
        h = item["hex"]
        if h in style_seen:
            msg = f"WARNING: duplicate hex {h!r} in paint_styles — keeping {style_seen[h]!r}, ignoring {item['name']!r}"
            warnings.append(msg)
            typer.echo(msg)
            dup_style.add(h)
        else:
            style_seen[h] = item["name"]

    classified = _classify_colors(
        data["node_colors"],
        prim_lookup=prim_seen,
        style_lookup=style_seen,
        dup_prim_hexes=dup_prim,
        dup_style_hexes=dup_style,
    )
    sorted_colors = _sort_colors(classified)

    matched = sum(1 for c in sorted_colors if c["status"] == "matched")
    paint_style_count = sum(1 for c in sorted_colors if c["status"] == "paint_style")
    new_candidates = sum(1 for c in sorted_colors if c["status"] == "new_candidate")
    unique = len(sorted_colors)

    # Console summary
    scanned_nodes = data.get("scanned_nodes", "?")
    scanned_pages = data.get("scanned_pages", "?")
    typer.echo(f"\nColor Usage Summary")
    typer.echo(f"  Scanned: {scanned_nodes} nodes across {scanned_pages} pages")
    typer.echo(f"  Unique colors: {unique}")
    typer.echo(f"  Matched to primitives: {matched}")
    typer.echo(f"  From paint styles: {paint_style_count}")
    typer.echo(f"  New candidates: {new_candidates}")
    typer.echo(f"\nTop colors by usage:")
    for c in sorted_colors[:10]:
        total = c["fill_count"] + c["stroke_count"]
        if c["status"] == "matched":
            label = f"→ {c['primitive_name']} (matched)"
        elif c["status"] == "paint_style":
            label = f"→ {c['paint_style_name']} (paint_style)"
        else:
            label = "→ NEW CANDIDATE"
        typer.echo(f"  {c['hex']}  ×{total:<5} {label}")

    # Write proposal
    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing proposal: {out_path}")

    proposal = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_usage_file": str(usage_path),
        "scanned_pages": scanned_pages,
        "scanned_nodes": scanned_nodes,
        "summary": {
            "unique_node_colors": unique,
            "matched_to_primitives": matched,
            "from_paint_styles": paint_style_count,
            "new_candidates": new_candidates,
        },
        "colors": sorted_colors,
    }

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
        hue, lightness, sat = _hex_to_hls(hex_)
        group = _color_group(hue, sat, lightness)
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
        hue, lightness, sat = _hex_to_hls(c["hex"])
        g = _color_group(hue, sat, lightness)
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
