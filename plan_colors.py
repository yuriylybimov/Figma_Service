"""Pure color-planning logic — no I/O, no CLI, no side effects."""

import colorsys
from datetime import datetime, timezone
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
