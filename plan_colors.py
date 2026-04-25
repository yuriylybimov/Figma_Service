"""Pure color-planning logic — no I/O, no CLI, no side effects."""

import colorsys
import re
from pathlib import Path


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


def _hex_to_group(hex_: str) -> str:
    """Return the color group name for a hex string (e.g. 'gray', 'blue', 'red')."""
    hue, lightness, sat = _hex_to_hls(hex_)
    return _color_group(hue, sat, lightness)


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


def _fmt_color_usage_summary_lines(
    *,
    scanned_nodes,
    scanned_pages,
    unique: int,
    matched: int,
    paint_style_count: int,
    new_candidates: int,
) -> list[str]:
    """Return the Color Usage Summary lines (without top-colors block)."""
    return [
        f"\nColor Usage Summary",
        f"  Scanned: {scanned_nodes} nodes across {scanned_pages} pages",
        f"  Unique colors: {unique}",
        f"  Matched to primitives: {matched}",
        f"  From paint styles: {paint_style_count}",
        f"  New candidates: {new_candidates}",
    ]


def _fmt_top_color_lines(sorted_colors: list[dict], *, limit: int = 10) -> list[str]:
    """Return formatted lines for the top-N colors by usage."""
    lines: list[str] = []
    for c in sorted_colors[:limit]:
        total = c["fill_count"] + c["stroke_count"]
        if c["status"] == "matched":
            label = f"→ {c['primitive_name']} (matched)"
        elif c["status"] == "paint_style":
            label = f"→ {c['paint_style_name']} (paint_style)"
        else:
            label = "→ NEW CANDIDATE"
        lines.append(f"  {c['hex']}  ×{total:<5} {label}")
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
        m = re.search(r"use_count=(\d+)", reason)
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
        group = _hex_to_group(c["hex"])
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


def _build_color_lookups(
    primitive_variables: list[dict],
    paint_styles: list[dict],
) -> tuple[dict[str, str], dict[str, str], set[str], set[str], list[str]]:
    """Build hex→name lookups for primitives and paint styles; collect duplicate warnings.

    Returns (prim_lookup, style_lookup, dup_prim_hexes, dup_style_hexes, warnings).
    Pure: no I/O, no printing.
    """
    warnings: list[str] = []

    def _make_warn(source_label: str, dup_set: set[str]):
        def warn(msg: str) -> None:
            labelled = msg.replace(" — ", f" in {source_label} — ", 1)
            warnings.append(labelled)
            dup_set.add(msg.split("'")[1])
        return warn

    dup_prim: set[str] = set()
    prim_lookup = _build_lookup(
        primitive_variables,
        key="hex",
        value="name",
        warn=_make_warn("primitive_variables", dup_prim),
    )

    dup_style: set[str] = set()
    style_lookup = _build_lookup(
        paint_styles,
        key="hex",
        value="name",
        warn=_make_warn("paint_styles", dup_style),
    )

    return prim_lookup, style_lookup, dup_prim, dup_style, warnings


def _classify_and_count(
    node_colors: list[dict],
    *,
    prim_lookup: dict[str, str],
    style_lookup: dict[str, str],
    dup_prim_hexes: set[str],
    dup_style_hexes: set[str],
) -> tuple[list[dict], int, int, int, int]:
    """Classify, sort, and count colors by status.

    Returns (sorted_colors, matched, paint_style_count, new_candidates, unique).
    Pure: no I/O, no side effects.
    """
    classified = _classify_colors(
        node_colors,
        prim_lookup=prim_lookup,
        style_lookup=style_lookup,
        dup_prim_hexes=dup_prim_hexes,
        dup_style_hexes=dup_style_hexes,
    )
    sorted_colors = _sort_colors(classified)
    matched = sum(1 for c in sorted_colors if c["status"] == "matched")
    paint_style_count = sum(1 for c in sorted_colors if c["status"] == "paint_style")
    new_candidates = sum(1 for c in sorted_colors if c["status"] == "new_candidate")
    unique = len(sorted_colors)
    return sorted_colors, matched, paint_style_count, new_candidates, unique


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


def _build_primitive_color_plan(
    *,
    generated_at: str,
    usage_path: Path,
    scanned_pages,
    scanned_nodes,
    unique: int,
    matched: int,
    paint_style_count: int,
    new_candidates: int,
    sorted_colors: list[dict],
) -> dict:
    """Build the proposal dict written to primitives.proposed.json."""
    return {
        "generated_at": generated_at,
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


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
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


# ---------------------------------------------------------------------------
# Audit
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


# ── Semantic tokens ──────────────────────────────────────────────────────────

SEMANTIC_ROLES = frozenset({
    "text", "icon", "border", "surface", "canvas", "accent", "status", "button",
})
# "icon", "accent", and "status" are valid roles accepted by the validator and
# available for explicit manual mappings, but _suggest_semantic_tokens does not
# emit them automatically — they require deliberate colour choices beyond what
# heuristics can reliably infer.
SEMANTIC_STATES = frozenset({
    "primary", "secondary", "inverse", "disabled",
    "success", "warning", "error", "info", "danger",
})


def _hex_luminance(hex_: str) -> float:
    """Return relative luminance (0–1) per WCAG 2.1, linearising sRGB channels."""
    h = hex_.lstrip("#")
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i*2:i*2+2], 16) / 255 for i in range(3))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)

_SEMANTIC_NAME_RE = re.compile(r"^color/([a-z]+)/([a-z]+)$")


def _validate_semantic_name(name: str) -> str | None:
    """Return error string if invalid, else None."""
    if not isinstance(name, str):
        return f"semantic name must be a string, got {type(name).__name__}"
    m = _SEMANTIC_NAME_RE.match(name)
    if not m:
        return f"semantic name {name!r}: must match 'color/<role>/<state>' (lowercase letters only)"
    role, state = m.group(1), m.group(2)
    if role not in SEMANTIC_ROLES:
        return (
            f"semantic name {name!r}: role {role!r} not in allowed roles "
            f"{sorted(SEMANTIC_ROLES)}"
        )
    if state not in SEMANTIC_STATES:
        return (
            f"semantic name {name!r}: state {state!r} not in allowed states "
            f"{sorted(SEMANTIC_STATES)}"
        )
    return None


def _build_and_validate_semantic_normalized(
    seed: dict,
    primitives_normalized: list[dict],
    overrides: dict,
) -> dict[str, str]:
    """Resolve overrides on top of seed and validate. Raise ValueError on first failure.

    Returns flat {semantic_name: primitive_name} dict on success.
    """
    if not isinstance(seed, dict):
        raise ValueError("seed must be a JSON object (semantic_name → primitive_name)")
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be a JSON object (semantic_name → primitive_name)")
    if not isinstance(primitives_normalized, list):
        raise ValueError("primitives_normalized must be a JSON list of entries")

    primitive_names: set[str] = set()
    for entry in primitives_normalized:
        if isinstance(entry, dict) and isinstance(entry.get("final_name"), str):
            primitive_names.add(entry["final_name"])

    resolved: dict[str, str] = {}
    for k, v in seed.items():
        resolved[k] = v
    for k, v in overrides.items():
        resolved[k] = v

    semantic_names = set(resolved.keys())

    for name in sorted(resolved.keys()):
        value = resolved[name]

        err = _validate_semantic_name(name)
        if err:
            raise ValueError(err)

        if not isinstance(value, str):
            raise ValueError(
                f"semantic {name!r}: value must be a string primitive name, "
                f"got {type(value).__name__}"
            )
        if _HEX_RE.match(value):
            raise ValueError(
                f"semantic {name!r}: value {value!r} is a raw hex; semantics must alias "
                f"a primitive name (e.g. 'color/gray/900'), not a hex"
            )
        if not value.startswith("color/"):
            raise ValueError(
                f"semantic {name!r}: value {value!r} must start with 'color/'"
            )
        if value.startswith("color/candidate/"):
            raise ValueError(
                f"semantic {name!r}: value {value!r} is a candidate placeholder; "
                f"semantics may not alias candidates"
            )
        if value in semantic_names:
            raise ValueError(
                f"semantic {name!r}: value {value!r} is itself a semantic name; "
                f"semantics may only alias primitives"
            )
        if value not in primitive_names:
            raise ValueError(
                f"semantic {name!r}: primitive {value!r} not found in "
                f"primitives.normalized.json"
            )

    return resolved


# Semantic mapping invariants (frozen — do not change without updating contract test):
#   text/primary    = darkest primitive by luminance
#   text/disabled   = nearest lighter than text/primary (strictly higher luminance)
#   canvas/primary  = lightest primitive by luminance
#   surface/primary = second-lightest (omitted when only one gray exists)
#   border/primary  = gray closest to L=0.50 by computed luminance (not by scale name)
#   mapping is luminance-driven, not scale-name-based (gray/400 can beat gray/500)
#   icon/* and accent/* are reserved roles — never auto-generated except accent/primary
def _suggest_semantic_tokens(primitives_normalized: list[dict]) -> dict[str, str]:
    """Return a suggested {semantic_name: primitive_name} mapping from a normalized primitive list.

    Heuristics (luminance-based, pure):
      - color/canvas/primary  → lightest gray (highest luminance)
      - color/surface/primary → next distinct lightest gray (skipped if only one gray)
      - color/text/primary    → darkest gray (lowest luminance)
      - color/text/disabled   → one luminance step lighter than text/primary
      - color/border/primary  → gray closest to L=0.50
      - color/accent/primary  → most saturated non-gray primitive (if any)

    Duplicate primitive values are allowed across different semantic roles.
    Fixed colors (color/white, color/black) are excluded from gray heuristics.
    Returns an empty dict if no qualifying primitives exist.
    """
    valid = [
        e for e in primitives_normalized
        if isinstance(e, dict)
        and isinstance(e.get("final_name"), str)
        and isinstance(e.get("hex"), str)
    ]

    grays = [e for e in valid if e["final_name"].startswith("color/gray/")]

    result: dict[str, str] = {}

    if grays:
        by_lum = sorted(grays, key=lambda e: _hex_luminance(e["hex"]))

        def _nearest(target_lum: float) -> str:
            return min(grays, key=lambda e: abs(_hex_luminance(e["hex"]) - target_lum))["final_name"]

        result["color/canvas/primary"] = by_lum[-1]["final_name"]

        if len(by_lum) >= 2 and by_lum[-2]["final_name"] != by_lum[-1]["final_name"]:
            result["color/surface/primary"] = by_lum[-2]["final_name"]

        result["color/text/primary"] = by_lum[0]["final_name"]
        # disabled: closest lighter gray than text/primary (strictly higher luminance), fallback to primary
        primary_lum = _hex_luminance(by_lum[0]["hex"])
        lighter = [e for e in by_lum[1:] if _hex_luminance(e["hex"]) > primary_lum]
        result["color/text/disabled"] = (
            min(lighter, key=lambda e: _hex_luminance(e["hex"]))["final_name"]
            if lighter
            else by_lum[0]["final_name"]
        )
        # Nearest to L=0.50 by computed luminance — numeric scale (400, 500…) is
        # not a reliable proxy; the actual hex value determines the winner.
        result["color/border/primary"] = _nearest(0.50)

    # accent: most saturated non-gray, non-fixed primitive
    non_gray = [
        e for e in valid
        if not e["final_name"].startswith("color/gray/")
        and e["final_name"] not in ("color/white", "color/black")
    ]
    if non_gray:
        def _saturation(e: dict) -> float:
            _, _, sat = _hex_to_hls(e["hex"])
            return sat
        result["color/accent/primary"] = max(non_gray, key=_saturation)["final_name"]

    return result


_GENERIC_NODE_NAMES = frozenset({
    "frame", "group", "container", "rectangle", "layer", "",
})

_AUTO_SUGGEST_ROLES = frozenset({"text", "surface", "border", "canvas"})


def _is_generic_name(name: str) -> bool:
    return name.strip().lower() in _GENERIC_NODE_NAMES


def _multi_role_warning(entry: dict) -> str | None:
    """Return a warning string if the color plays multiple roles above the 30% threshold."""
    counts = {
        "fill": entry.get("fill_count", 0),
        "stroke": entry.get("stroke_count", 0),
        "text_fill": entry.get("text_count", 0),
    }
    dominant_role, dominant_count = max(counts.items(), key=lambda kv: kv[1])
    if dominant_count == 0:
        return None
    for role, count in counts.items():
        if role != dominant_role and count >= dominant_count * 0.30:
            return (
                f"color plays multiple roles: dominant={dominant_role} ({dominant_count}), "
                f"secondary={role} ({count})"
            )
    return None


def _infer_role(entry: dict, luminance: float) -> str | None:
    """Infer a single semantic role from multi-signal context. Returns None if ambiguous."""
    fill = entry.get("fill_count", 0)
    stroke = entry.get("stroke_count", 0)
    text = entry.get("text_count", 0)
    total = fill + stroke + text
    if total == 0:
        return None

    dominant = entry.get("dominant_role", "fill")

    if dominant == "text_fill" or (text > fill and text > stroke):
        return "text"

    if dominant == "stroke" or (stroke > fill and stroke > text):
        # Only infer border when stroke-dominant usage comes from structural nodes
        # (FRAME, RECTANGLE, INSTANCE). VECTOR-heavy stroke usage is icon/chart lines,
        # not borders — skip rather than mis-label.
        samples = entry.get("sample_nodes", [])
        stroke_samples = [s for s in samples if s.get("role") == "stroke"]
        vector_strokes = sum(1 for s in stroke_samples if s.get("type") == "VECTOR")
        if stroke_samples and vector_strokes / len(stroke_samples) > 0.5:
            return None
        return "border"

    # fill dominant — disambiguate canvas vs surface using context signals
    samples = entry.get("sample_nodes", [])

    def _is_global_surface() -> bool:
        """Return True only when sample nodes span multiple distinct contexts.

        A color used exclusively within one component (e.g. every sample is
        "search bar" inside "container") is component-specific and must not
        be promoted to a global surface token. Require at least 3 distinct
        parent_frame_names OR at least 2 distinct component_names to pass.
        The OR form means either broad layout spread or multi-component spread
        is sufficient; the AND form is too strict for small sample sets.
        3-frame threshold avoids false positives from typo-pair duplicates
        (e.g. "container" / "conteiner" counted as two distinct values).
        """
        distinct_frames = {
            s.get("parent_frame_name", "").strip()
            for s in samples
            if s.get("parent_frame_name", "").strip()
        }
        distinct_components = {
            s.get("component_name", "").strip()
            for s in samples
            if s.get("component_name", "").strip()
        }
        return len(distinct_frames) >= 3 or len(distinct_components) >= 2

    if luminance > 0.92:
        for s in samples:
            pfn = (s.get("parent_frame_name") or "").lower()
            if "dashboard" in pfn or "page" in pfn:
                return "canvas"
        for s in samples:
            cn = (s.get("component_name") or "").lower()
            if "card" in cn or "modal" in cn:
                return "surface" if _is_global_surface() else None
        if luminance >= 0.97:
            return "canvas"
        return "surface" if _is_global_surface() else None

    # Mid-luminance fill: surface — only for neutral/low-saturation colors.
    # Saturated fills (icons, charts, accents) are skipped here; they belong
    # to roles not auto-emitted by this function.
    _, _, sat = _hex_to_hls(entry.get("hex", "#000000"))
    if _perceived_chroma(sat, luminance) > 0.08:
        return None

    return "surface" if _is_global_surface() else None


def _compute_confidence(entry: dict, role: str, has_multi_role_warning: bool) -> str:
    """Return 'high', 'medium', or 'low' per architecture confidence rules."""
    use_count = entry.get("use_count", 0)
    samples = entry.get("sample_nodes", [])

    if use_count < 10:
        return "low"

    if has_multi_role_warning:
        return "low"

    all_generic = all(_is_generic_name(s.get("name", "")) for s in samples)

    pages = {s.get("page", "") for s in samples}
    components = {s.get("component_name", "") for s in samples if s.get("component_name")}
    single_page = len(pages) == 1
    single_component = len(components) == 1 and len(samples) > 1

    has_semantic_node = any(
        not _is_generic_name(s.get("name", ""))
        or (s.get("component_name") or "").strip() not in ("", *_GENERIC_NODE_NAMES)
        for s in samples
    )

    if all_generic or (single_page and single_component):
        return "medium"

    if has_semantic_node and not single_page:
        return "high"

    return "medium"


def _suggest_semantic_tokens_contextual(
    context: list[dict],
    primitives_normalized: list[dict],
) -> list[dict]:
    """Generate contextual semantic token suggestions from enriched color usage data.

    Inputs:
      context              — output of read color-usage-context (color_usage_context.json)
      primitives_normalized — colors list from primitives.normalized.json

    Returns a list of suggestion dicts, each with all six required fields:
      semantic_name, primitive_name, confidence, reason, usage_examples, warnings

    Rules (from architecture.md):
      - Only roles in _AUTO_SUGGEST_ROLES are auto-generated (text, surface, border, canvas).
      - icon and accent are never auto-generated here.
      - Each suggestion's primitive_name must exist in primitives_normalized.
      - At most one suggestion per (role, state) pair; first/highest-use wins.
      - dominant_role alone is insufficient — multi-signal inference required.
      - Confidence is downgraded per the five downgrade conditions in the spec.
      - A warning is added when the second-strongest role count is ≥ 30% of dominant.
    """
    # Build hex → final_name lookup from primitives
    prim_by_hex: dict[str, str] = {}
    for e in primitives_normalized:
        if isinstance(e, dict) and e.get("hex") and e.get("final_name"):
            prim_by_hex[e["hex"].lower()] = e["final_name"]

    # Track which (semantic_name) slots are already filled; first wins
    taken: dict[str, dict] = {}

    for entry in context:
        hex_ = entry.get("hex", "").lower()
        primitive_name = prim_by_hex.get(hex_)
        if not primitive_name:
            continue

        luminance = _hex_luminance(hex_)
        role = _infer_role(entry, luminance)
        if role is None or role not in _AUTO_SUGGEST_ROLES:
            continue

        semantic_name = f"color/{role}/primary"
        if semantic_name in taken:
            continue

        samples = entry.get("sample_nodes", [])
        usage_examples = [
            {
                "name": s.get("name", ""),
                "type": s.get("type", ""),
                "role": s.get("role", ""),
                "page": s.get("page", ""),
                "parent_frame_name": s.get("parent_frame_name", ""),
                "component_name": s.get("component_name", ""),
            }
            for s in samples[:5]
        ]

        warnings: list[str] = []
        multi_warn = _multi_role_warning(entry)
        if multi_warn:
            warnings.append(multi_warn)

        has_multi_role_warning = bool(multi_warn)
        confidence = _compute_confidence(entry, role, has_multi_role_warning)

        fill = entry.get("fill_count", 0)
        stroke = entry.get("stroke_count", 0)
        text = entry.get("text_count", 0)
        reason = (
            f"inferred role={role!r} from usage distribution "
            f"(fill={fill}, stroke={stroke}, text={text}); "
            f"luminance={round(luminance, 3)}; use_count={entry.get('use_count', 0)}"
        )

        taken[semantic_name] = {
            "semantic_name": semantic_name,
            "primitive_name": primitive_name,
            "confidence": confidence,
            "reason": reason,
            "usage_examples": usage_examples,
            "warnings": warnings,
        }

    return list(taken.values())
