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


def _hex_to_hls(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return colorsys.rgb_to_hls(r, g, b)  # (hue, lightness, saturation)


def _color_group(hue: float, saturation: float) -> str:
    if saturation < _GRAY_SATURATION_THRESHOLD:
        return "gray"
    for lo, hi, name in _HUE_GROUPS:
        if lo <= hue < hi:
            return name
    return "gray"


def _assign_scales(lightness_values: list[float]) -> list[int]:
    """Map N lightness values (same-group, in input order) → 100-900 scale integers.
    Lighter = lower scale number. With fewer than 9 values, picks evenly spaced slots."""
    n = len(lightness_values)
    if n == 0:
        return []
    if n == 1:
        return [500]
    order = sorted(range(n), key=lambda i: lightness_values[i], reverse=True)
    slot_indices = [round(i * 8 / (n - 1)) for i in range(n)]
    result = [0] * n
    for rank, orig_idx in enumerate(order):
        result[orig_idx] = _SCALES[slot_indices[rank]]
    return result


def _build_normalized_entries(
    candidates: list[dict],
    *,
    overrides: dict[str, str],
) -> list[dict]:
    """Classify candidates into groups, assign scales, apply overrides."""
    groups: dict[str, list] = {}
    for idx, c in enumerate(candidates):
        hue, lightness, sat = _hex_to_hls(c["hex"])
        group = _color_group(hue, sat)
        groups.setdefault(group, []).append((idx, c, lightness))

    auto_names: dict[str, str] = {}
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
