"""Pure logic: convert raw Figma primitive usage into ranked seed suggestions.

No I/O. No Figma calls. No seed file writes.
Input:  dict returned by read_primitive_usage.js (raw lists per type key).
Output: list of {name, value, use_count, raw_values, [candidate]} dicts,
        sorted ascending by value.
"""

import re
from collections import defaultdict

from primitive_types import PRIMITIVE_TYPES


# Maps token type → raw payload key
_RAW_KEY: dict[str, str] = {
    "spacing":        "spacing",
    "radius":         "radius",
    "stroke-width":   "stroke_width",
    "font-size":      "font_size",
    "font-weight":    "font_weight",
    "font-family":    "font_family",
    "line-height":    "line_height",
    "letter-spacing": "letter_spacing",
    "opacity":        "opacity",
}

# Dedup rounding step per FLOAT type.
# spacing / radius / line-height use 4px grid for normalization (user request).
# All other types use a small step that only collapses floating-point noise.
_ROUND_TO: dict[str, float] = {
    "spacing":        4.0,
    "radius":         4.0,
    "stroke-width":   0.5,
    "font-size":      0.5,
    "font-weight":    1.0,
    "line-height":    4.0,
    "letter-spacing": 0.5,
    "opacity":        0.01,
}

# Radius values >= this threshold are full-radius candidates (e.g. pill shapes).
_FULL_RADIUS_THRESHOLD = 9999

# Spacing range guard — must match SPACING_MIN / SPACING_MAX in read_primitive_usage.js.
# Values outside this range are not surfaced as token candidates.
# Sub-4 values are sub-pixel noise or border widths, not spacing tokens.
# Values above 128 are almost certainly layout dimensions, not spacing tokens.
SPACING_MIN: float = 4.0
SPACING_MAX: float = 128.0


def _round_to(value: float, step: float) -> float:
    return round(round(value / step) * step, 10)


def _count_and_rank(values: list, *, round_to: float = 0.5) -> dict:
    """Count occurrences after rounding. Returns {rounded_value: count}."""
    from collections import Counter
    rounded = [_round_to(v, round_to) for v in values]
    return dict(Counter(rounded))


def _group_with_raw(values: list[float], *, round_to: float) -> dict:
    """Group raw values by their rounded bucket.

    Returns:
        {bucket_value: {"count": int, "raw": [original values]}}
    """
    groups: dict[float, dict] = defaultdict(lambda: {"count": 0, "raw": []})
    for v in values:
        bucket = _round_to(v, round_to)
        groups[bucket]["count"] += 1
        groups[bucket]["raw"].append(v)
    return dict(groups)


def _sanitize_family_name(family: str) -> str:
    """'SF Pro Display' → 'sf-pro-display'"""
    return re.sub(r"\s+", "-", family.strip()).lower()


def suggest_primitive_entries(type_key: str, raw: dict) -> list[dict]:
    """Return ranked suggestions for one token type.

    Args:
        type_key: e.g. 'spacing', 'font-family'
        raw:      dict from read_primitive_usage.js

    Returns:
        List of {name, value, use_count, raw_values} sorted ascending by value.
        radius entries with value >= 9999 additionally carry {"candidate": "full-radius"}.
        For font-family (STRING): sorted alphabetically by name; no raw_values field.
    """
    if type_key not in PRIMITIVE_TYPES:
        raise ValueError(f"unknown type '{type_key}'. Valid: {sorted(PRIMITIVE_TYPES)}")

    raw_key = _RAW_KEY[type_key]
    values: list = raw.get(raw_key, [])

    if not values:
        return []

    td = PRIMITIVE_TYPES[type_key]

    if td.figma_type == "STRING":
        # font-family: exact string dedup, alphabetical, no raw_values
        from collections import Counter
        counts = Counter(v for v in values if isinstance(v, str))
        entries = sorted(counts.items(), key=lambda x: x[0])
        return [
            {
                "name": f"{type_key}/{_sanitize_family_name(family)}",
                "value": family,
                "use_count": count,
            }
            for family, count in entries
        ]

    # FLOAT types — group by rounded bucket, preserve raw originals per bucket.
    step = _ROUND_TO[type_key]
    numeric = [float(v) for v in values if isinstance(v, (int, float))]

    # Spacing safety filter: drop values outside the intentional token range.
    # Primary gate is the JS (Auto Layout-only nodes, same bounds), but the
    # Python layer re-applies the same constants as a defensive second pass.
    if type_key == "spacing":
        numeric = [v for v in numeric if SPACING_MIN <= v <= SPACING_MAX]

    # Full-radius candidates (radius >= threshold) bypass grid normalization:
    # each distinct exact value becomes its own bucket so none are merged away.
    if type_key == "radius":
        normal = [v for v in numeric if v < _FULL_RADIUS_THRESHOLD]
        full = [v for v in numeric if v >= _FULL_RADIUS_THRESHOLD]
        groups = _group_with_raw(normal, round_to=step)
        # One bucket per distinct exact full-radius value
        full_groups = _group_with_raw(full, round_to=1.0)
        groups.update(full_groups)
    else:
        groups = _group_with_raw(numeric, round_to=step)

    sorted_buckets = sorted(groups.keys())
    result = []
    for i, bucket in enumerate(sorted_buckets, start=1):
        g = groups[bucket]
        entry: dict = {
            "name": f"{type_key}/{i}",
            "value": bucket,
            "use_count": g["count"],
            "raw_values": sorted(g["raw"]),
        }
        if type_key == "radius" and bucket >= _FULL_RADIUS_THRESHOLD:
            entry["candidate"] = "full-radius"
        result.append(entry)

    return result
