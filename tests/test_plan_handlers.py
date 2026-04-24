"""Unit tests for plan_handlers host-side logic."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import plan_handlers as ph


# --- _build_lookup ---

def test_build_lookup_basic():
    items = [{"hex": "#ffffff", "name": "color/base/white"}]
    result = ph._build_lookup(items, key="hex", value="name")
    assert result == {"#ffffff": "color/base/white"}


def test_build_lookup_first_seen_wins_on_duplicate():
    items = [
        {"hex": "#3b82f6", "name": "color/blue/500"},
        {"hex": "#3b82f6", "name": "color/blue/500-alt"},
    ]
    warnings = []
    result = ph._build_lookup(items, key="hex", value="name", warn=warnings.append)
    assert result == {"#3b82f6": "color/blue/500"}
    assert len(warnings) == 1
    assert "#3b82f6" in warnings[0]


# --- _classify_colors ---

def _make_color(hex_, fill=1, stroke=0, examples=None):
    return {
        "hex": hex_,
        "fill_count": fill,
        "stroke_count": stroke,
        "examples": examples or [{"page": "P", "node": "N"}],
    }


def test_classify_matched():
    colors = [_make_color("#ffffff")]
    prim = {"#ffffff": "color/base/white"}
    result = ph._classify_colors(colors, prim_lookup=prim, style_lookup={})
    assert result[0]["status"] == "matched"
    assert result[0]["primitive_name"] == "color/base/white"
    assert result[0]["paint_style_name"] is None
    assert result[0]["duplicate_warning"] is False


def test_classify_paint_style():
    colors = [_make_color("#3b82f6")]
    style = {"#3b82f6": "brand/primary"}
    result = ph._classify_colors(colors, prim_lookup={}, style_lookup=style)
    assert result[0]["status"] == "paint_style"
    assert result[0]["paint_style_name"] == "brand/primary"
    assert result[0]["primitive_name"] is None


def test_classify_new_candidate():
    colors = [_make_color("#ef4444")]
    result = ph._classify_colors(colors, prim_lookup={}, style_lookup={})
    assert result[0]["status"] == "new_candidate"
    assert result[0]["primitive_name"] is None
    assert result[0]["paint_style_name"] is None


def test_classify_primitive_wins_over_style():
    colors = [_make_color("#ffffff")]
    prim = {"#ffffff": "color/base/white"}
    style = {"#ffffff": "some/style"}
    result = ph._classify_colors(colors, prim_lookup=prim, style_lookup=style)
    assert result[0]["status"] == "matched"


def test_classify_preserves_duplicate_warning():
    colors = [_make_color("#ffffff")]
    colors[0]["_dup_prim"] = True
    prim = {"#ffffff": "color/base/white"}
    result = ph._classify_colors(colors, prim_lookup=prim, style_lookup={}, dup_prim_hexes={"#ffffff"})
    assert result[0]["duplicate_warning"] is True


# --- _sort_colors ---

def _make_classified(hex_, status, fill=1, stroke=0):
    return {
        "hex": hex_,
        "fill_count": fill,
        "stroke_count": stroke,
        "status": status,
        "primitive_name": None,
        "paint_style_name": None,
        "duplicate_warning": False,
        "examples": [],
    }


def test_sort_status_group_order():
    colors = [
        _make_classified("#aaaaaa", "new_candidate", fill=50),
        _make_classified("#bbbbbb", "paint_style", fill=30),
        _make_classified("#cccccc", "matched", fill=10),
    ]
    result = ph._sort_colors(colors)
    assert [c["status"] for c in result] == ["matched", "paint_style", "new_candidate"]


def test_sort_usage_desc_within_group():
    colors = [
        _make_classified("#aaaaaa", "new_candidate", fill=5, stroke=0),
        _make_classified("#bbbbbb", "new_candidate", fill=20, stroke=0),
    ]
    result = ph._sort_colors(colors)
    assert result[0]["hex"] == "#bbbbbb"


def test_sort_hex_asc_tiebreak():
    colors = [
        _make_classified("#zzzzzz", "new_candidate", fill=10),
        _make_classified("#aaaaaa", "new_candidate", fill=10),
    ]
    result = ph._sort_colors(colors)
    assert result[0]["hex"] == "#aaaaaa"


# --- integration: primitive-colors-from-project command ---

import json
from typer.testing import CliRunner
from run import app

runner = CliRunner()

_USAGE = {
    "scanned_pages": 2,
    "scanned_nodes": 100,
    "totals": {"unique_node_colors": 3, "paint_style_colors": 1, "primitive_variable_colors": 1},
    "node_colors": [
        {"hex": "#ffffff", "fill_count": 50, "stroke_count": 0, "examples": [{"page": "P", "node": "N"}]},
        {"hex": "#3b82f6", "fill_count": 10, "stroke_count": 2, "examples": [{"page": "P", "node": "N2"}]},
        {"hex": "#ef4444", "fill_count": 5, "stroke_count": 0, "examples": [{"page": "P", "node": "N3"}]},
    ],
    "paint_styles": [{"name": "brand/primary", "hex": "#3b82f6", "style_id": "S:1"}],
    "primitive_variables": [{"name": "color/base/white", "hex": "#ffffff"}],
}


def test_command_writes_proposal(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    assert out_file.exists()
    proposal = json.loads(out_file.read_text())
    assert proposal["summary"]["unique_node_colors"] == 3
    assert proposal["summary"]["matched_to_primitives"] == 1
    assert proposal["summary"]["from_paint_styles"] == 1
    assert proposal["summary"]["new_candidates"] == 1


def test_command_sort_order_in_proposal(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"

    runner.invoke(app, [
        "plan", "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    proposal = json.loads(out_file.read_text())
    statuses = [c["status"] for c in proposal["colors"]]
    assert statuses == ["matched", "paint_style", "new_candidate"]


def test_command_does_not_touch_primitives_json(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    primitives = tmp_path / "primitives.json"
    primitives.write_text('{"color":{}}', encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"

    runner.invoke(app, [
        "plan", "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    assert primitives.read_text() == '{"color":{}}'


def test_command_missing_usage_file(tmp_path):
    result = runner.invoke(app, [
        "plan", "primitive-colors-from-project",
        "--usage", str(tmp_path / "nonexistent.json"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_command_malformed_usage_file(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text('{"bad": true}', encoding="utf-8")
    result = runner.invoke(app, [
        "plan", "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_command_warns_on_overwrite(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"
    out_file.write_text("old content", encoding="utf-8")

    result = runner.invoke(app, [
        "plan", "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    assert "WARNING: overwriting" in result.output
    proposal = json.loads(out_file.read_text())
    assert "summary" in proposal


# --- normalize helpers ---

import colorsys

def test_hex_to_hls_white():
    from plan_handlers import _hex_to_hls
    h, l, s = _hex_to_hls("#ffffff")
    assert l == pytest.approx(1.0)

def test_hex_to_hls_black():
    from plan_handlers import _hex_to_hls
    h, l, s = _hex_to_hls("#000000")
    assert l == pytest.approx(0.0)

def test_color_group_gray():
    from plan_handlers import _color_group
    # Low saturation → gray
    assert _color_group(0.5, 0.05) == "gray"

def test_color_group_red():
    from plan_handlers import _color_group
    # hue ~0.0, high saturation → red
    assert _color_group(0.02, 0.8) == "red"

def test_color_group_blue():
    from plan_handlers import _color_group
    # hue ~0.65, high saturation → blue
    assert _color_group(0.65, 0.8) == "blue"

def test_color_group_near_neutral_light_is_gray():
    from plan_handlers import _color_group, _hex_to_hls
    # Very light near-neutral colors with blue hue but low saturation → gray
    for hex_ in ("#f3f4f6", "#f9fafb", "#e5e7eb"):
        hue, lightness, sat = _hex_to_hls(hex_)
        assert _color_group(hue, sat, lightness) == "gray", (
            f"{hex_} (hue={hue:.3f}, sat={sat:.3f}, l={lightness:.3f}) should be gray"
        )

def test_color_group_clearly_blue_not_reclassified():
    from plan_handlers import _color_group
    # High-saturation blue must stay blue regardless of lightness
    assert _color_group(0.60, 0.70, 0.90) == "blue"

def test_assign_scale_single():
    from plan_handlers import _assign_scales
    # Single color → scale 500
    result = _assign_scales([0.5])
    assert result == [500]

def test_assign_scale_two_lightest_first():
    from plan_handlers import _assign_scales
    # Two lightness values: lighter gets lower number
    result = _assign_scales([0.9, 0.1])
    assert result[0] < result[1]

def test_assign_scale_nine_even():
    from plan_handlers import _assign_scales
    # lightness[0]=0.0 (darkest) → scale 900; lightness[8]=1.0 (lightest) → scale 100
    lightness = [i / 8 for i in range(9)]
    result = _assign_scales(lightness)
    assert result == [900, 800, 700, 600, 500, 400, 300, 200, 100]

def test_assign_scale_no_duplicates_identical_lightness():
    from plan_handlers import _assign_scales
    # Identical lightness values must still produce unique scale slots
    result = _assign_scales([0.5, 0.5, 0.5])
    assert len(result) == len(set(result)), f"duplicate scales: {result}"
    assert all(s in [100, 200, 300, 400, 500, 600, 700, 800, 900] for s in result)

def test_assign_scale_collision_resolved_no_none():
    from plan_handlers import _assign_scales
    # All identical lightness: must never produce None or crash
    for n in range(1, 10):
        result = _assign_scales([0.5] * n)
        assert None not in result, f"n={n}: got None in {result}"
        assert len(result) == len(set(result)), f"n={n}: duplicates in {result}"

def test_assign_scale_no_intermediate_slots():
    from plan_handlers import _assign_scales
    # No matter the input, output must only contain standard scale values
    for n in range(1, 10):
        lightness = [0.5] * n
        result = _assign_scales(lightness)
        for s in result:
            assert s in [100, 200, 300, 400, 500, 600, 700, 800, 900], (
                f"n={n}: got non-standard scale {s}"
            )

def test_assign_scale_only_uses_100_900_range():
    from plan_handlers import _assign_scales
    for n in range(2, 10):
        lightness = [i / (n - 1) for i in range(n)]
        result = _assign_scales(lightness)
        assert all(100 <= s <= 900 for s in result)
        assert all(s % 100 == 0 for s in result)

def test_assign_scale_more_than_9_raises():
    from plan_handlers import _assign_scales
    with pytest.raises(ValueError, match="more than 9 colors"):
        _assign_scales([0.1 * i for i in range(10)])

def test_build_normalized_entries_basic():
    from plan_handlers import _build_normalized_entries
    candidates = [
        {"hex": "#2f2f2f", "fill_count": 10, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []},
    ]
    result = _build_normalized_entries(candidates, overrides={})
    assert len(result) == 1
    e = result[0]
    assert e["hex"] == "#2f2f2f"
    assert e["auto_name"].startswith("color/")
    assert e["final_name"] == e["auto_name"]
    assert e["candidate_name"] == "color/candidate/2f2f2f"

def test_build_normalized_entries_override_applied():
    from plan_handlers import _build_normalized_entries
    candidates = [
        {"hex": "#2f2f2f", "fill_count": 10, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []},
    ]
    result = _build_normalized_entries(candidates, overrides={"#2f2f2f": "color/neutral/900"})
    assert result[0]["final_name"] == "color/neutral/900"
    assert result[0]["auto_name"] != "color/neutral/900"

def test_build_normalized_entries_white_fixed():
    from plan_handlers import _build_normalized_entries
    candidates = [
        {"hex": "#ffffff", "fill_count": 5, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []},
    ]
    result = _build_normalized_entries(candidates, overrides={})
    assert result[0]["auto_name"] == "color/white"
    assert result[0]["final_name"] == "color/white"

def test_build_normalized_entries_black_fixed():
    from plan_handlers import _build_normalized_entries
    candidates = [
        {"hex": "#000000", "fill_count": 3, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []},
    ]
    result = _build_normalized_entries(candidates, overrides={})
    assert result[0]["auto_name"] == "color/black"
    assert result[0]["final_name"] == "color/black"

def test_build_normalized_entries_white_excluded_from_gray_scale():
    from plan_handlers import _build_normalized_entries
    # White + a real gray should not produce color/gray/100 for white
    candidates = [
        {"hex": "#ffffff", "fill_count": 5, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []},
        {"hex": "#9ca3af", "fill_count": 3, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []},
    ]
    result = _build_normalized_entries(candidates, overrides={})
    names = {e["hex"]: e["auto_name"] for e in result}
    assert names["#ffffff"] == "color/white"
    assert names["#9ca3af"].startswith("color/gray/")

def test_build_normalized_entries_no_duplicate_final_names():
    from plan_handlers import _build_normalized_entries
    # Several grays with same or similar lightness must produce unique final_names
    candidates = [
        {"hex": h, "fill_count": 1, "stroke_count": 0,
         "status": "new_candidate", "primitive_name": None,
         "paint_style_name": None, "duplicate_warning": False, "examples": []}
        for h in ["#aaaaaa", "#ababab", "#acacac", "#adadad"]
    ]
    result = _build_normalized_entries(candidates, overrides={})
    final_names = [e["final_name"] for e in result]
    assert len(final_names) == len(set(final_names)), f"duplicate final_names: {final_names}"


# --- integration: primitive-colors-normalized command ---

_PROPOSAL = {
    "generated_at": "2025-01-01T00:00:00+00:00",
    "source_usage_file": "/tmp/usage.json",
    "scanned_pages": 1,
    "scanned_nodes": 50,
    "summary": {
        "unique_node_colors": 3,
        "matched_to_primitives": 1,
        "from_paint_styles": 1,
        "new_candidates": 1,
    },
    "colors": [
        {
            "hex": "#ffffff", "fill_count": 50, "stroke_count": 0,
            "status": "matched", "primitive_name": "color/base/white",
            "paint_style_name": None, "duplicate_warning": False, "examples": [],
        },
        {
            "hex": "#3b82f6", "fill_count": 10, "stroke_count": 2,
            "status": "paint_style", "primitive_name": None,
            "paint_style_name": "brand/primary", "duplicate_warning": False, "examples": [],
        },
        {
            "hex": "#ef4444", "fill_count": 5, "stroke_count": 0,
            "status": "new_candidate", "primitive_name": None,
            "paint_style_name": None, "duplicate_warning": False, "examples": [],
        },
    ],
}


def _no_merge(tmp_path):
    """Return --merge args pointing at a nonexistent file, so the real overrides.merge.json is not used."""
    return ["--merge", str(tmp_path / "no_merge.json")]


def test_normalized_command_writes_output(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["summary"]["candidates"] == 1
    assert len(data["colors"]) == 1
    assert data["colors"][0]["hex"] == "#ef4444"


def test_normalized_command_only_processes_new_candidates(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    data = json.loads(out_file.read_text())
    hexes = [c["hex"] for c in data["colors"]]
    assert "#ffffff" not in hexes
    assert "#3b82f6" not in hexes


def test_normalized_command_applies_overrides(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    overrides_file = tmp_path / "overrides.normalized.json"
    # Use a name that differs from the auto-assigned one to confirm override takes effect
    overrides_file.write_text(json.dumps({"#ef4444": "color/error/default"}), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--overrides", str(overrides_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    data = json.loads(out_file.read_text())
    assert data["colors"][0]["final_name"] == "color/error/default"
    assert data["summary"]["overrides_applied"] == 1


def test_normalized_command_empty_overrides_file(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    overrides_file = tmp_path / "overrides.normalized.json"
    overrides_file.write_text("{}", encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--overrides", str(overrides_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    data = json.loads(out_file.read_text())
    assert data["summary"]["overrides_applied"] == 0


def test_normalized_command_missing_overrides_uses_empty(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"
    nonexistent_overrides = tmp_path / "no_overrides.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--overrides", str(nonexistent_overrides),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    data = json.loads(out_file.read_text())
    assert data["summary"]["overrides_applied"] == 0


def test_normalized_command_missing_proposal_file(tmp_path):
    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposal", str(tmp_path / "nonexistent.json"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_normalized_command_malformed_proposal_file(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text('{"bad": true}', encoding="utf-8")
    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(tmp_path / "out.json"),
        *_no_merge(tmp_path),
    ])
    assert result.exit_code != 0


def test_normalized_command_warns_on_overwrite(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"
    out_file.write_text("old content", encoding="utf-8")

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    assert "WARNING: overwriting" in result.output
    data = json.loads(out_file.read_text())
    assert "colors" in data


def test_normalized_output_contains_auto_name_and_candidate_name(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    data = json.loads(out_file.read_text())
    entry = data["colors"][0]
    assert "auto_name" in entry
    assert "candidate_name" in entry
    assert entry["candidate_name"] == "color/candidate/ef4444"


# --- _validate_normalized unit tests ---

def _valid_entry(hex_="#ef4444", final_name="color/red/500"):
    return {
        "hex": hex_,
        "candidate_name": f"color/candidate/{hex_.lstrip('#')}",
        "auto_name": "color/red/500",
        "final_name": final_name,
    }


def test_validate_normalized_valid():
    errors = ph._validate_normalized([_valid_entry()])
    assert errors == []


def test_validate_normalized_missing_required_field():
    entry = _valid_entry()
    del entry["auto_name"]
    errors = ph._validate_normalized([entry])
    assert any("auto_name" in e for e in errors)


def test_validate_normalized_bad_hex_format():
    entry = _valid_entry(hex_="ef4444")  # missing #
    errors = ph._validate_normalized([entry])
    assert any("hex" in e for e in errors)


def test_validate_normalized_bad_hex_wrong_length():
    entry = _valid_entry(hex_="#ef44")
    errors = ph._validate_normalized([entry])
    assert any("hex" in e for e in errors)


def test_validate_normalized_final_name_no_color_prefix():
    entry = _valid_entry(final_name="brand/primary")
    errors = ph._validate_normalized([entry])
    assert any("final_name" in e for e in errors)


def test_validate_normalized_final_name_candidate_prefix_rejected():
    entry = _valid_entry(final_name="color/candidate/ef4444")
    errors = ph._validate_normalized([entry])
    assert any("candidate" in e for e in errors)


def test_validate_normalized_duplicate_final_name():
    entries = [_valid_entry("#ef4444", "color/red/500"), _valid_entry("#cc0000", "color/red/500")]
    errors = ph._validate_normalized(entries)
    assert any("duplicate" in e for e in errors)


def test_validate_normalized_multiple_errors_all_reported():
    entry = {"hex": "bad", "candidate_name": "x", "auto_name": "x", "final_name": "brand/x"}
    errors = ph._validate_normalized([entry])
    assert len(errors) >= 2  # bad hex + bad final_name prefix


# --- validate-normalized CLI tests ---

def _write_normalized(path, colors):
    path.write_text(json.dumps({"generated_at": "2025-01-01T00:00:00+00:00", "colors": colors}), encoding="utf-8")


def test_validate_normalized_command_passes_valid(tmp_path):
    f = tmp_path / "primitives.normalized.json"
    _write_normalized(f, [_valid_entry()])
    result = runner.invoke(app, ["plan", "validate-normalized", "--normalized", str(f)])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_validate_normalized_command_fails_on_missing_file(tmp_path):
    result = runner.invoke(app, [
        "plan", "validate-normalized",
        "--normalized", str(tmp_path / "nonexistent.json"),
    ])
    assert result.exit_code != 0


def test_validate_normalized_command_fails_on_missing_colors_key(tmp_path):
    f = tmp_path / "primitives.normalized.json"
    f.write_text(json.dumps({"generated_at": "2025-01-01T00:00:00+00:00"}), encoding="utf-8")
    result = runner.invoke(app, ["plan", "validate-normalized", "--normalized", str(f)])
    assert result.exit_code != 0


def test_validate_normalized_command_prints_errors_and_exits_nonzero(tmp_path):
    f = tmp_path / "primitives.normalized.json"
    bad_entry = _valid_entry()
    bad_entry["final_name"] = "color/candidate/ef4444"
    _write_normalized(f, [bad_entry])
    result = runner.invoke(app, ["plan", "validate-normalized", "--normalized", str(f)])
    assert result.exit_code != 0
    assert "ERROR" in (result.output + (result.stderr or ""))


# --- sync primitive-colors-normalized (host-side only) ---
# These tests exercise the Python command layer only: argument parsing, file
# validation, JS placeholder substitution, and call ordering.
# _run_validation and _dispatch_sync are both mocked — no browser, no Figma.

_NORMALIZED_DATA = {
    "generated_at": "2025-01-01T00:00:00+00:00",
    "summary": {"candidates": 2, "overrides_applied": 0},
    "colors": [
        {
            "hex": "#ef4444",
            "candidate_name": "color/candidate/ef4444",
            "auto_name": "color/red/500",
            "final_name": "color/red/500",
            "fill_count": 5,
            "stroke_count": 0,
            "examples": [],
        },
        {
            "hex": "#3b82f6",
            "candidate_name": "color/candidate/3b82f6",
            "auto_name": "color/blue/500",
            "final_name": "color/blue/500",
            "fill_count": 10,
            "stroke_count": 2,
            "examples": [],
        },
    ],
}


def _write_normalized_file(path, data=None):
    path.write_text(json.dumps(data or _NORMALIZED_DATA), encoding="utf-8")


_STUB_OK_MODEL = None  # populated lazily below


def _make_stub_ok_model():
    """Return a minimal ExecOkInline that satisfies model validation."""
    import sync_handlers as sh
    from protocol import ExecOkInline
    return ExecOkInline(status="ok", mode="inline", result={}, request_id="test", elapsed_ms=0)


def _patch_sync(monkeypatch):
    """Patch _run_validation and _dispatch_sync; return a dict that collects calls."""
    calls = {"validate": 0, "dispatch": [], "dispatch_kwargs": []}
    ok_model = _make_stub_ok_model()

    def _fake_dispatch(user_js, **kw):
        calls["dispatch"].append(user_js)
        calls["dispatch_kwargs"].append(kw)
        return ({}, ok_model)

    monkeypatch.setattr("sync_handlers._run_validation", lambda **kw: calls.update(validate=calls["validate"] + 1))
    monkeypatch.setattr("sync_handlers._dispatch_sync", _fake_dispatch)
    return calls


def test_sync_normalized_missing_file(tmp_path, monkeypatch):
    _patch_sync(monkeypatch)
    result = runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(tmp_path / "nonexistent.json"),
    ])
    assert result.exit_code != 0


def test_sync_normalized_missing_colors_key(tmp_path, monkeypatch):
    _patch_sync(monkeypatch)
    f = tmp_path / "primitives.normalized.json"
    f.write_text('{"generated_at": "x"}', encoding="utf-8")
    result = runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(f),
    ])
    assert result.exit_code != 0


def test_sync_normalized_dry_run_injects_true(tmp_path, monkeypatch):
    calls = _patch_sync(monkeypatch)
    f = tmp_path / "primitives.normalized.json"
    _write_normalized_file(f)

    result = runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(f),
        "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    js = calls["dispatch"][0]
    assert "true" in js
    assert "__DRY_RUN__" not in js


def test_sync_normalized_real_run_injects_false(tmp_path, monkeypatch):
    calls = _patch_sync(monkeypatch)
    f = tmp_path / "primitives.normalized.json"
    _write_normalized_file(f)

    result = runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(f),
    ])

    assert result.exit_code == 0, result.output
    js = calls["dispatch"][0]
    assert "false" in js
    assert "__DRY_RUN__" not in js


def test_sync_normalized_injects_all_entries(tmp_path, monkeypatch):
    calls = _patch_sync(monkeypatch)
    f = tmp_path / "primitives.normalized.json"
    _write_normalized_file(f)

    runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(f),
        "--dry-run",
    ])

    js = calls["dispatch"][0]
    assert "#ef4444" in js
    assert "#3b82f6" in js
    assert "color/candidate/ef4444" in js
    assert "color/red/500" in js


def test_sync_normalized_no_raw_placeholder_in_js(tmp_path, monkeypatch):
    calls = _patch_sync(monkeypatch)
    f = tmp_path / "primitives.normalized.json"
    _write_normalized_file(f)

    runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(f),
        "--dry-run",
    ])

    js = calls["dispatch"][0]
    assert "__NORMALIZED__" not in js
    assert "__DRY_RUN__" not in js


def test_sync_normalized_calls_validation_before_dispatch(tmp_path, monkeypatch):
    call_order = []
    monkeypatch.setattr("sync_handlers._run_validation", lambda **kw: call_order.append("validate"))
    monkeypatch.setattr(
        "sync_handlers._dispatch_sync",
        lambda user_js, **kw: call_order.append("dispatch"),
    )
    f = tmp_path / "primitives.normalized.json"
    _write_normalized_file(f)

    runner.invoke(app, [
        "sync", "primitive-colors-normalized",
        "--normalized", str(f),
        "--dry-run",
    ])

    assert call_order == ["validate", "dispatch"]


# --- _validate_merge_map unit tests ---

def _make_candidate(hex_):
    return {
        "hex": hex_, "fill_count": 1, "stroke_count": 0,
        "status": "new_candidate", "primitive_name": None,
        "paint_style_name": None, "duplicate_warning": False, "examples": [],
    }


def test_validate_merge_map_valid():
    candidates = {c["hex"] for c in [_make_candidate("#aaaaaa"), _make_candidate("#9d9d9d")]}
    errors = ph._validate_merge_map({"#aaaaaa": "#9d9d9d"}, candidates)
    assert errors == []


def test_validate_merge_map_invalid_source_hex():
    candidates = {"aaaaaa", "#9d9d9d"}
    errors = ph._validate_merge_map({"aaaaaa": "#9d9d9d"}, candidates)
    assert any("source_hex" in e and "valid" in e for e in errors)


def test_validate_merge_map_invalid_canonical_hex():
    candidates = {"#aaaaaa", "9d9d9d"}
    errors = ph._validate_merge_map({"#aaaaaa": "9d9d9d"}, candidates)
    assert any("canonical_hex" in e and "valid" in e for e in errors)


def test_validate_merge_map_source_is_white_forbidden():
    candidates = {"#ffffff", "#9d9d9d"}
    errors = ph._validate_merge_map({"#ffffff": "#9d9d9d"}, candidates)
    assert any("#ffffff" in e and "cannot be merge" in e for e in errors)


def test_validate_merge_map_source_is_black_forbidden():
    candidates = {"#000000", "#9d9d9d"}
    errors = ph._validate_merge_map({"#000000": "#9d9d9d"}, candidates)
    assert any("#000000" in e and "cannot be merge" in e for e in errors)


def test_validate_merge_map_canonical_is_white_forbidden():
    candidates = {"#aaaaaa", "#ffffff"}
    errors = ph._validate_merge_map({"#aaaaaa": "#ffffff"}, candidates)
    assert any("#ffffff" in e and "cannot be merge" in e for e in errors)


def test_validate_merge_map_canonical_is_black_forbidden():
    candidates = {"#aaaaaa", "#000000"}
    errors = ph._validate_merge_map({"#aaaaaa": "#000000"}, candidates)
    assert any("#000000" in e and "cannot be merge" in e for e in errors)


def test_validate_merge_map_source_not_in_candidates():
    candidates = {"#9d9d9d"}
    errors = ph._validate_merge_map({"#aaaaaa": "#9d9d9d"}, candidates)
    assert any("source_hex" in e and "not found" in e for e in errors)


def test_validate_merge_map_canonical_not_in_candidates():
    candidates = {"#aaaaaa"}
    errors = ph._validate_merge_map({"#aaaaaa": "#9d9d9d"}, candidates)
    assert any("canonical_hex" in e and "not found" in e for e in errors)


def test_validate_merge_map_empty_is_valid():
    errors = ph._validate_merge_map({}, set())
    assert errors == []


# --- _apply_merge_map unit tests ---

def test_apply_merge_map_removes_source():
    candidates = [_make_candidate("#aaaaaa"), _make_candidate("#9d9d9d"), _make_candidate("#ef4444")]
    reduced, excluded = ph._apply_merge_map(candidates, {"#aaaaaa": "#9d9d9d"})
    hexes = [c["hex"] for c in reduced]
    assert "#aaaaaa" not in hexes
    assert "#9d9d9d" in hexes
    assert "#ef4444" in hexes
    assert excluded == 1


def test_apply_merge_map_keeps_canonical():
    candidates = [_make_candidate("#aaaaaa"), _make_candidate("#9d9d9d")]
    reduced, _ = ph._apply_merge_map(candidates, {"#aaaaaa": "#9d9d9d"})
    assert any(c["hex"] == "#9d9d9d" for c in reduced)


def test_apply_merge_map_empty_map_unchanged():
    candidates = [_make_candidate("#aaaaaa"), _make_candidate("#9d9d9d")]
    reduced, excluded = ph._apply_merge_map(candidates, {})
    assert reduced == candidates
    assert excluded == 0


def test_apply_merge_map_multiple_sources():
    candidates = [
        _make_candidate("#aaaaaa"), _make_candidate("#ababab"),
        _make_candidate("#9d9d9d"), _make_candidate("#ef4444"),
    ]
    reduced, excluded = ph._apply_merge_map(
        candidates,
        {"#aaaaaa": "#9d9d9d", "#ababab": "#9d9d9d"},
    )
    hexes = [c["hex"] for c in reduced]
    assert "#aaaaaa" not in hexes
    assert "#ababab" not in hexes
    assert "#9d9d9d" in hexes
    assert "#ef4444" in hexes
    assert excluded == 2


# --- integration: primitive-colors-normalized with merge map ---

def _make_proposal_with_many_grays():
    """Proposal with 12 gray new_candidates — exceeds 9-slot limit without merge."""
    grays = [
        "#111111", "#222222", "#333333", "#444444", "#555555",
        "#666666", "#777777", "#888888", "#999999", "#aaaaaa",
        "#9d9d9d", "#bbbbbb",
    ]
    colors = [
        {
            "hex": h, "fill_count": 1, "stroke_count": 0,
            "status": "new_candidate", "primitive_name": None,
            "paint_style_name": None, "duplicate_warning": False, "examples": [],
        }
        for h in grays
    ]
    return {
        "generated_at": "2025-01-01T00:00:00+00:00",
        "source_usage_file": "/tmp/usage.json",
        "scanned_pages": 1, "scanned_nodes": 50,
        "summary": {"unique_node_colors": len(grays), "matched_to_primitives": 0,
                    "from_paint_styles": 0, "new_candidates": len(grays)},
        "colors": colors,
    }


def test_normalized_command_merge_map_reduces_candidates(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_make_proposal_with_many_grays()), encoding="utf-8")
    # Merge 3 sources into their canonicals, bringing 12 → 9
    merge_map = {
        "#aaaaaa": "#9d9d9d",
        "#bbbbbb": "#999999",
        "#888888": "#777777",
    }
    merge_file = tmp_path / "overrides.merge.json"
    merge_file.write_text(json.dumps(merge_map), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(merge_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    data = json.loads(out_file.read_text())
    assert data["summary"]["candidates_before_merge"] == 12
    assert data["summary"]["merged_excluded"] == 3
    assert data["summary"]["candidates"] == 9


def test_normalized_command_merge_source_excluded_from_output(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_make_proposal_with_many_grays()), encoding="utf-8")
    merge_map = {"#aaaaaa": "#9d9d9d", "#bbbbbb": "#999999", "#888888": "#777777"}
    merge_file = tmp_path / "overrides.merge.json"
    merge_file.write_text(json.dumps(merge_map), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(merge_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    output_hexes = {c["hex"] for c in data["colors"]}
    assert "#aaaaaa" not in output_hexes
    assert "#bbbbbb" not in output_hexes
    assert "#888888" not in output_hexes
    assert "#9d9d9d" in output_hexes
    assert "#999999" in output_hexes
    assert "#777777" in output_hexes


def test_normalized_command_merge_summary_printed(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_make_proposal_with_many_grays()), encoding="utf-8")
    merge_map = {"#aaaaaa": "#9d9d9d", "#bbbbbb": "#999999", "#888888": "#777777"}
    merge_file = tmp_path / "overrides.merge.json"
    merge_file.write_text(json.dumps(merge_map), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(merge_file),
        "--out", str(out_file),
    ])

    # Compact merge summary line: before= merged= after=
    assert "before=" in result.output
    assert "merged=" in result.output
    assert "after=" in result.output


def test_normalized_command_missing_merge_file_ok(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(tmp_path / "nonexistent.merge.json"),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output


def test_normalized_command_merge_invalid_source_not_in_candidates(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    merge_map = {"#cc1234": "#ef4444"}  # #cc1234 not a candidate
    merge_file = tmp_path / "overrides.merge.json"
    merge_file.write_text(json.dumps(merge_map), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(merge_file),
        "--out", str(out_file),
    ])

    assert result.exit_code != 0


def test_normalized_command_merge_white_as_source_rejected(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    # Proposal with #ffffff as new_candidate (unusual but possible input)
    proposal = {**_PROPOSAL, "colors": [
        {
            "hex": "#ffffff", "fill_count": 5, "stroke_count": 0,
            "status": "new_candidate", "primitive_name": None,
            "paint_style_name": None, "duplicate_warning": False, "examples": [],
        },
        {
            "hex": "#ef4444", "fill_count": 5, "stroke_count": 0,
            "status": "new_candidate", "primitive_name": None,
            "paint_style_name": None, "duplicate_warning": False, "examples": [],
        },
    ]}
    proposal_file.write_text(json.dumps(proposal), encoding="utf-8")
    merge_map = {"#ffffff": "#ef4444"}
    merge_file = tmp_path / "overrides.merge.json"
    merge_file.write_text(json.dumps(merge_map), encoding="utf-8")

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(merge_file),
        "--out", str(tmp_path / "out.json"),
    ])

    assert result.exit_code != 0


def test_normalized_command_empty_merge_file_no_merge_summary(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    merge_file = tmp_path / "overrides.merge.json"
    merge_file.write_text("{}", encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--merge", str(merge_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    # Empty merge map → no merge summary block, candidates_before_merge equals candidates
    data = json.loads(out_file.read_text())
    assert data["summary"]["merged_excluded"] == 0


# ---------------------------------------------------------------------------
# _suggest_merge_overrides unit tests
# ---------------------------------------------------------------------------

def _make_cleanup_color(hex_, use_count, cleanup_tag="keep"):
    return {
        "hex": hex_,
        "fill_count": use_count,
        "stroke_count": 0,
        "status": "new_candidate",
        "primitive_name": None,
        "paint_style_name": None,
        "duplicate_warning": False,
        "examples": [],
        "use_count": use_count,
        "cleanup_tag": cleanup_tag,
    }


# Nine grays — no overflow, no suggestions.
_NINE_GRAYS = [
    _make_cleanup_color(h, 10)
    for h in ["#111111", "#222222", "#333333", "#444444", "#555555",
              "#666666", "#777777", "#888888", "#999999"]
]

# Ten grays — 1 overflow, 1 suggestion needed.
_TEN_GRAYS = _NINE_GRAYS + [_make_cleanup_color("#aaaaaa", 2, "review_low_use")]


def test_suggest_no_merges_when_group_exactly_9():
    result = ph._suggest_merge_overrides(_NINE_GRAYS)
    assert result == []


def test_suggest_one_merge_when_group_has_10():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    assert len(result) == 1


def test_suggest_source_is_lowest_priority():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    # The review_low_use color with lowest use_count must be the source
    assert result[0]["source_hex"] == "#aaaaaa"


def test_suggest_canonical_is_in_remaining_group():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    remaining_hexes = {c["hex"] for c in _NINE_GRAYS}
    assert result[0]["canonical_hex"] in remaining_hexes


def test_suggest_source_not_same_as_canonical():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    assert result[0]["source_hex"] != result[0]["canonical_hex"]


def test_suggest_group_field_set():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    assert result[0]["group"] == "gray"


def test_suggest_hsl_distance_is_float():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    assert isinstance(result[0]["hsl_distance"], float)


def test_suggest_reason_field_present():
    result = ph._suggest_merge_overrides(_TEN_GRAYS)
    assert "reason" in result[0]
    assert result[0]["reason"]


def test_suggest_prefers_review_low_use_before_keep():
    # Mix: one review_low_use (low use_count), others keep
    colors = [_make_cleanup_color(h, 10, "keep") for h in [
        "#111111", "#222222", "#333333", "#444444", "#555555",
        "#666666", "#777777", "#888888", "#999999",
    ]] + [_make_cleanup_color("#aaaaaa", 50, "review_low_use")]
    result = ph._suggest_merge_overrides(colors)
    assert len(result) == 1
    # review_low_use must be chosen as source even though its use_count is higher
    assert result[0]["source_hex"] == "#aaaaaa"


def test_suggest_among_keep_prefers_lower_use_count():
    # All keep; the one with the lowest use_count should be source
    colors = [_make_cleanup_color(h, uc, "keep") for h, uc in [
        ("#111111", 100), ("#222222", 90), ("#333333", 80), ("#444444", 70),
        ("#555555", 60), ("#666666", 50), ("#777777", 40), ("#888888", 30),
        ("#999999", 20), ("#aaaaaa", 5),   # lowest use_count
    ]]
    result = ph._suggest_merge_overrides(colors)
    assert len(result) == 1
    assert result[0]["source_hex"] == "#aaaaaa"


def test_suggest_skips_white_and_black():
    # White and black in input must never appear as source or canonical
    colors = [
        _make_cleanup_color("#ffffff", 100),
        _make_cleanup_color("#000000", 80),
    ] + _TEN_GRAYS
    result = ph._suggest_merge_overrides(colors)
    for s in result:
        assert s["source_hex"] not in ("#ffffff", "#000000")
        assert s["canonical_hex"] not in ("#ffffff", "#000000")


def test_suggest_exactly_nine_after_merges():
    # 12 grays → need 3 merges to reach 9
    colors = [_make_cleanup_color(f"#{i:02x}{i:02x}{i:02x}", 10 - i, "review_low_use" if i >= 8 else "keep")
              for i in range(1, 13)]
    result = ph._suggest_merge_overrides(colors)
    assert len(result) == 3


def test_suggest_no_duplicate_sources():
    colors = [_make_cleanup_color(f"#{i:02x}{i:02x}{i:02x}", 10 - i)
              for i in range(1, 13)]
    result = ph._suggest_merge_overrides(colors)
    sources = [s["source_hex"] for s in result]
    assert len(sources) == len(set(sources))


def test_suggest_canonical_nearest_hsl():
    # Source #aaaaaa — all remaining grays equidistant in value, but #999999
    # is the nearest gray by hex/lightness
    grays = [_make_cleanup_color(h, 10) for h in
             ["#111111", "#222222", "#333333", "#444444", "#555555",
              "#666666", "#777777", "#888888", "#999999"]]
    extra = _make_cleanup_color("#aaaaaa", 1, "review_low_use")
    result = ph._suggest_merge_overrides(grays + [extra])
    assert len(result) == 1
    # #999999 is HSL-nearest to #aaaaaa among the remaining grays
    assert result[0]["canonical_hex"] == "#999999"


def test_suggest_dedup_covered_excluded():
    # If a hex is in dedup_covered it should not appear as source
    colors = _TEN_GRAYS[:]  # 10 grays; #aaaaaa would normally be source
    result_with = ph._suggest_merge_overrides(colors, dedup_covered={"#aaaaaa"})
    # #aaaaaa excluded → only 9 effective candidates → no overflow → no suggestion
    assert result_with == []


def test_suggest_empty_input_no_error():
    result = ph._suggest_merge_overrides([])
    assert result == []


def test_suggest_deterministic():
    colors = [_make_cleanup_color(f"#{i:02x}{i:02x}{i:02x}", 10 - i)
              for i in range(1, 13)]
    r1 = ph._suggest_merge_overrides(colors)
    r2 = ph._suggest_merge_overrides(colors)
    assert r1 == r2


# ---------------------------------------------------------------------------
# plan suggest-merge-overrides CLI integration tests
# ---------------------------------------------------------------------------

def _make_cleanup_file(tmp_path, colors):
    data = {
        "generated_at": "2025-01-01T00:00:00+00:00",
        "source_proposed_file": "/tmp/p.json",
        "source_detail_file": "/tmp/d.json",
        "threshold": 3,
        "summary": {"total": len(colors), "keep": 0, "review_low_use": 0},
        "colors": colors,
    }
    p = tmp_path / "primitives.cleanup.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _make_dedup_file(tmp_path, groups=None):
    data = {
        "generated_at": "2025-01-01T00:00:00+00:00",
        "source_cleanup_file": "/tmp/c.json",
        "hsl_delta_threshold": 0.01,
        "summary": {},
        "groups": groups or [],
    }
    p = tmp_path / "primitives.dedup.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_suggest_command_no_overflow_writes_empty_merges(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _NINE_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["summary"]["merges_suggested"] == 0
    assert data["merges"] == []
    assert data["merge_map"] == {}


def test_suggest_command_overflow_writes_merges(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    data = json.loads(out_file.read_text())
    assert data["summary"]["merges_suggested"] == 1
    assert len(data["merges"]) == 1
    assert len(data["merge_map"]) == 1


def test_suggest_command_merge_map_keys_are_sources(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    sources_from_merges = {s["source_hex"] for s in data["merges"]}
    assert set(data["merge_map"].keys()) == sources_from_merges


def test_suggest_command_merge_map_values_are_canonicals(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    canonicals_from_merges = {s["canonical_hex"] for s in data["merges"]}
    assert set(data["merge_map"].values()) == canonicals_from_merges


def test_suggest_command_does_not_write_overrides_merge_json(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert not (tmp_path / "overrides.merge.json").exists()


def test_suggest_command_missing_cleanup_fails(tmp_path):
    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(tmp_path / "nonexistent.json"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_suggest_command_malformed_cleanup_fails(tmp_path):
    bad = tmp_path / "primitives.cleanup.json"
    bad.write_text('{"bad": true}', encoding="utf-8")
    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(bad),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_suggest_command_missing_dedup_still_works(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    out_file = tmp_path / "overrides.merge.proposed.json"

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(tmp_path / "nonexistent_dedup.json"),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    data = json.loads(out_file.read_text())
    assert "merges" in data


def test_suggest_command_output_has_required_keys(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _NINE_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    for key in ("generated_at", "source_cleanup_file", "source_dedup_file",
                "summary", "merges", "merge_map"):
        assert key in data, f"missing key: {key}"


def test_suggest_command_warns_on_overwrite(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _NINE_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"
    out_file.write_text("old content", encoding="utf-8")

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert "WARNING: overwriting" in result.output
    data = json.loads(out_file.read_text())
    assert "merges" in data


def test_suggest_command_dedup_merge_excluded_from_candidates(tmp_path):
    # dedup says #aaaaaa should merge into #999999 — so #aaaaaa must not appear
    # as a source suggestion from the overflow algorithm
    colors = _TEN_GRAYS[:]  # 10 grays; without dedup, #aaaaaa would be source
    cleanup_file = _make_cleanup_file(tmp_path, colors)
    dedup_groups = [{
        "canonical_hex": "#999999",
        "recommendation": "merge",
        "members": [
            {"hex": "#999999", "use_count": 10, "cleanup_tag": "keep"},
            {"hex": "#aaaaaa", "use_count": 2, "cleanup_tag": "review_low_use"},
        ],
    }]
    dedup_file = _make_dedup_file(tmp_path, dedup_groups)
    out_file = tmp_path / "overrides.merge.proposed.json"

    runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    sources = [m["source_hex"] for m in data["merges"]]
    assert "#aaaaaa" not in sources


def test_suggest_command_summary_counts_match_output(tmp_path):
    colors = [_make_cleanup_color(f"#{i:02x}{i:02x}{i:02x}", 10 - i)
              for i in range(1, 13)]  # 12 grays → 3 merges needed
    cleanup_file = _make_cleanup_file(tmp_path, colors)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    assert data["summary"]["merges_suggested"] == len(data["merges"])
    assert data["summary"]["merges_suggested"] == len(data["merge_map"])


# ---------------------------------------------------------------------------
# _fmt_group_block unit tests
# ---------------------------------------------------------------------------

def _make_normalized_entry(hex_, final_name, auto_name=None):
    return {
        "hex": hex_,
        "candidate_name": f"color/candidate/{hex_.lstrip('#')}",
        "auto_name": auto_name or final_name,
        "final_name": final_name,
        "fill_count": 1,
        "stroke_count": 0,
        "examples": [],
    }


class TestFmtGroupBlock:
    def test_groups_grays_under_color_gray_header(self):
        entries = [
            _make_normalized_entry("#f9fafb", "color/gray/100"),
            _make_normalized_entry("#6b7280", "color/gray/500"),
        ]
        lines = ph._fmt_group_block(entries)
        assert any("color / gray (2)" in l for l in lines)

    def test_scale_appears_in_output(self):
        entries = [_make_normalized_entry("#f9fafb", "color/gray/100")]
        lines = ph._fmt_group_block(entries)
        assert any("100" in l and "#f9fafb" in l for l in lines)

    def test_fixed_white_black_in_fixed_section(self):
        entries = [
            _make_normalized_entry("#ffffff", "color/white"),
            _make_normalized_entry("#000000", "color/black"),
        ]
        lines = ph._fmt_group_block(entries)
        assert any("Fixed" in l for l in lines)
        assert any("white" in l and "#ffffff" in l for l in lines)
        assert any("black" in l and "#000000" in l for l in lines)

    def test_override_marked_with_asterisk(self):
        entry = _make_normalized_entry("#ef4444", "color/error/500", auto_name="color/red/500")
        lines = ph._fmt_group_block([entry])
        assert any("*" in l for l in lines)

    def test_no_asterisk_when_no_override(self):
        entry = _make_normalized_entry("#ef4444", "color/red/500")
        lines = ph._fmt_group_block([entry])
        assert not any("*" in l for l in lines)

    def test_scales_sorted_ascending(self):
        entries = [
            _make_normalized_entry("#111111", "color/gray/900"),
            _make_normalized_entry("#f9fafb", "color/gray/100"),
            _make_normalized_entry("#6b7280", "color/gray/500"),
        ]
        lines = ph._fmt_group_block(entries)
        scale_lines = [l for l in lines if l.strip() and l.startswith("    ")]
        scale_values = []
        for l in scale_lines:
            parts = l.strip().split()
            if parts and parts[0].isdigit():
                scale_values.append(int(parts[0]))
        assert scale_values == sorted(scale_values)

    def test_multiple_groups_all_present(self):
        entries = [
            _make_normalized_entry("#ef4444", "color/red/500"),
            _make_normalized_entry("#3b82f6", "color/blue/500"),
            _make_normalized_entry("#9ca3af", "color/gray/400"),
        ]
        lines = ph._fmt_group_block(entries)
        text = "\n".join(lines)
        assert "color / red" in text
        assert "color / blue" in text
        assert "color / gray" in text

    def test_empty_input_returns_empty_list(self):
        assert ph._fmt_group_block([]) == []

    def test_groups_ordered_gray_first_then_alphabetical_fixed_last(self):
        entries = [
            _make_normalized_entry("#ef4444", "color/red/500"),
            _make_normalized_entry("#3b82f6", "color/blue/500"),
            _make_normalized_entry("#9ca3af", "color/gray/400"),
            _make_normalized_entry("#a855f7", "color/purple/500"),
            _make_normalized_entry("#ffffff", "color/white"),
        ]
        lines = ph._fmt_group_block(entries)
        header_lines = [l for l in lines if l.strip().startswith("color /") or "Fixed" in l]
        names = [l.strip().split()[2] if "color /" in l else "Fixed" for l in header_lines]
        assert names == ["gray", "blue", "purple", "red", "Fixed"]


# ---------------------------------------------------------------------------
# _fmt_merge_table unit tests
# ---------------------------------------------------------------------------

class TestFmtMergeTable:
    def test_empty_returns_empty_list(self):
        assert ph._fmt_merge_table([]) == []

    def test_header_present(self):
        suggestion = {
            "source_hex": "#aaaaaa", "canonical_hex": "#9d9d9d",
            "group": "gray", "hsl_distance": 0.025,
            "reason": "review_low_use, use_count=1, nearest in group",
        }
        lines = ph._fmt_merge_table([suggestion])
        assert any("source" in l and "canonical" in l for l in lines)

    def test_source_and_canonical_in_row(self):
        suggestion = {
            "source_hex": "#aaaaaa", "canonical_hex": "#9d9d9d",
            "group": "gray", "hsl_distance": 0.025,
            "reason": "review_low_use, use_count=2, nearest in group",
        }
        lines = ph._fmt_merge_table([suggestion])
        row = "\n".join(lines)
        assert "#aaaaaa" in row
        assert "#9d9d9d" in row

    def test_use_count_extracted_from_reason(self):
        suggestion = {
            "source_hex": "#aaaaaa", "canonical_hex": "#9d9d9d",
            "group": "gray", "hsl_distance": 0.025,
            "reason": "review_low_use, use_count=7, nearest in group",
        }
        lines = ph._fmt_merge_table([suggestion])
        assert any("7" in l for l in lines[1:])


# ---------------------------------------------------------------------------
# plan primitive-colors-normalized: grouped output assertions
# ---------------------------------------------------------------------------

def test_normalized_output_is_grouped(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    # Grouped header format: "color / <group> (N)"
    assert "color / " in result.output


def test_normalized_output_no_flat_hex_list(tmp_path):
    """The old flat list style (one hex per line, ungrouped) should not appear."""
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    # Old format was "  #ef4444  color/red/500" — hex followed by full name on same line
    # New format nests hex under group header; full name never appears in terminal output
    assert "color/red/" not in result.output or "color / red" in result.output


def test_normalized_override_marker_in_output(tmp_path):
    proposal_file = tmp_path / "primitives.proposed.json"
    proposal_file.write_text(json.dumps(_PROPOSAL), encoding="utf-8")
    overrides_file = tmp_path / "overrides.normalized.json"
    overrides_file.write_text(json.dumps({"#ef4444": "color/error/default"}), encoding="utf-8")
    out_file = tmp_path / "primitives.normalized.json"

    result = runner.invoke(app, [
        "plan", "primitive-colors-normalized",
        "--proposed", str(proposal_file),
        "--overrides", str(overrides_file),
        "--out", str(out_file),
        *_no_merge(tmp_path),
    ])

    assert result.exit_code == 0, result.output
    assert "*" in result.output
    assert "(* = override applied)" in result.output


# ---------------------------------------------------------------------------
# plan suggest-merge-overrides: table output assertions
# ---------------------------------------------------------------------------

def test_suggest_output_has_table_header(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    assert "source" in result.output
    assert "canonical" in result.output


def test_suggest_output_hex_values_present(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert "#aaaaaa" in result.output


def test_suggest_output_file_path_shown(tmp_path):
    cleanup_file = _make_cleanup_file(tmp_path, _TEN_GRAYS)
    dedup_file = _make_dedup_file(tmp_path)
    out_file = tmp_path / "overrides.merge.proposed.json"

    result = runner.invoke(app, [
        "plan", "suggest-merge-overrides",
        "--cleanup", str(cleanup_file),
        "--dedup", str(dedup_file),
        "--out", str(out_file),
    ])

    assert str(out_file) in result.output


# ---------------------------------------------------------------------------
# _audit_palette unit tests
# ---------------------------------------------------------------------------

def _make_normalized_list(*entries):
    return list(entries)


class TestAuditPalette:
    def test_total_count(self):
        entries = [
            _make_normalized_entry("#f9fafb", "color/gray/100"),
            _make_normalized_entry("#6b7280", "color/gray/500"),
            _make_normalized_entry("#ffffff", "color/white"),
        ]
        audit = ph._audit_palette(entries)
        assert audit["total"] == 3

    def test_groups_extracted(self):
        entries = [
            _make_normalized_entry("#f9fafb", "color/gray/100"),
            _make_normalized_entry("#9ca3af", "color/gray/400"),
            _make_normalized_entry("#ef4444", "color/red/500"),
        ]
        audit = ph._audit_palette(entries)
        assert "gray" in audit["groups"]
        assert "red" in audit["groups"]
        assert audit["groups"]["gray"] == [100, 400]
        assert audit["groups"]["red"] == [500]

    def test_fixed_colors_separated(self):
        entries = [
            _make_normalized_entry("#ffffff", "color/white"),
            _make_normalized_entry("#000000", "color/black"),
        ]
        audit = ph._audit_palette(entries)
        assert "white" in audit["fixed"]
        assert "black" in audit["fixed"]
        assert "gray" not in audit["groups"]

    def test_missing_scales_detected(self):
        entries = [_make_normalized_entry("#f9fafb", "color/gray/100")]
        audit = ph._audit_palette(entries)
        assert "gray" in audit["missing"]
        assert 200 in audit["missing"]["gray"]
        assert 100 not in audit["missing"]["gray"]

    def test_full_nine_slot_group_has_no_missing(self):
        hexes_scales = [
            ("#111111", 900), ("#222222", 800), ("#333333", 700),
            ("#444444", 600), ("#555555", 500), ("#666666", 400),
            ("#777777", 300), ("#888888", 200), ("#f9fafb", 100),
        ]
        entries = [_make_normalized_entry(h, f"color/gray/{s}") for h, s in hexes_scales]
        audit = ph._audit_palette(entries)
        assert "gray" not in audit["missing"]

    def test_suspicious_low_chroma_non_gray_detected(self):
        # #f0f0ff is a very pale blue — perceptually near-neutral but classified as blue
        # Use a color we know will trigger: near-white with slight hue
        entries = [_make_normalized_entry("#fafafa", "color/blue/100")]
        audit = ph._audit_palette(entries)
        # If chroma < threshold it should appear in suspicious
        from plan_handlers import _hex_to_hls, _perceived_chroma, _LOW_CHROMA_THRESHOLD
        hue, lightness, sat = _hex_to_hls("#fafafa")
        chroma = _perceived_chroma(sat, lightness)
        if chroma < _LOW_CHROMA_THRESHOLD:
            assert any(s["hex"] == "#fafafa" for s in audit["suspicious"])
        else:
            assert not any(s["hex"] == "#fafafa" for s in audit["suspicious"])

    def test_gray_colors_never_suspicious(self):
        entries = [_make_normalized_entry("#9ca3af", "color/gray/400")]
        audit = ph._audit_palette(entries)
        assert not any(s["hex"] == "#9ca3af" for s in audit["suspicious"])

    def test_empty_input(self):
        audit = ph._audit_palette([])
        assert audit["total"] == 0
        assert audit["groups"] == {}
        assert audit["fixed"] == []
        assert audit["missing"] == {}
        assert audit["suspicious"] == []


# ---------------------------------------------------------------------------
# plan audit-palette CLI tests
# ---------------------------------------------------------------------------

def _write_normalized_for_audit(path, colors):
    path.write_text(json.dumps({
        "generated_at": "2025-01-01T00:00:00+00:00",
        "colors": colors,
    }), encoding="utf-8")


_AUDIT_COLORS = [
    _make_normalized_entry("#f9fafb", "color/gray/100"),
    _make_normalized_entry("#6b7280", "color/gray/500"),
    _make_normalized_entry("#111827", "color/gray/900"),
    _make_normalized_entry("#ef4444", "color/red/500"),
    _make_normalized_entry("#ffffff", "color/white"),
    _make_normalized_entry("#000000", "color/black"),
]


class TestAuditPaletteCLI:
    def test_exits_zero_on_valid_file(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert result.exit_code == 0, result.output

    def test_shows_total_token_count(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert str(len(_AUDIT_COLORS)) in result.output

    def test_shows_group_names(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert "gray" in result.output
        assert "red" in result.output

    def test_shows_fixed_colors(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert "white" in result.output
        assert "black" in result.output

    def test_shows_missing_slots(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert "missing" in result.output.lower()

    def test_shows_suspicious_section(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert "Suspicious" in result.output

    def test_missing_file_exits_nonzero(self, tmp_path):
        result = runner.invoke(app, [
            "plan", "audit-palette",
            "--normalized", str(tmp_path / "nonexistent.json"),
        ])
        assert result.exit_code != 0

    def test_missing_colors_key_exits_nonzero(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        f.write_text(json.dumps({"generated_at": "x"}), encoding="utf-8")
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert result.exit_code != 0

    def test_does_not_write_any_file(self, tmp_path):
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, _AUDIT_COLORS)
        before = set(tmp_path.iterdir())
        runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        after = set(tmp_path.iterdir())
        assert before == after

    def test_full_nine_slot_gray_no_missing_section(self, tmp_path):
        hexes_scales = [
            ("#111111", 900), ("#222222", 800), ("#333333", 700),
            ("#444444", 600), ("#555555", 500), ("#666666", 400),
            ("#777777", 300), ("#888888", 200), ("#f9fafb", 100),
        ]
        colors = [_make_normalized_entry(h, f"color/gray/{s}") for h, s in hexes_scales]
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_for_audit(f, colors)
        result = runner.invoke(app, ["plan", "audit-palette", "--normalized", str(f)])
        assert result.exit_code == 0, result.output
        # All 9 slots filled — missing section should not appear for gray
        assert "Missing scale slots" not in result.output


# ---------------------------------------------------------------------------
# sync primitive-colors-normalized: --verbose and summary output
# ---------------------------------------------------------------------------

def _patch_sync_with_result(monkeypatch, js_result: dict):
    """Patch _run_validation and _dispatch_sync; _dispatch_sync returns (js_result, ok_model)."""
    ok_model = _make_stub_ok_model()
    monkeypatch.setattr("sync_handlers._run_validation", lambda **kw: None)
    monkeypatch.setattr(
        "sync_handlers._dispatch_sync",
        lambda user_js, **kw: (js_result, ok_model),
    )


_JS_RESULT_DRY = {
    "collection": "primitives",
    "mode": "dry-run-mode",
    "dry_run": True,
    "renamed": 0,
    "created": 2,
    "skipped": 0,
    "total": 2,
    "log": [
        {"action": "would-rename-or-create", "candidate_name": "color/candidate/ef4444",
         "final_name": "color/red/500", "hex": "#ef4444", "note": "(would check for color/candidate/ef4444)"},
        {"action": "would-rename-or-create", "candidate_name": "color/candidate/3b82f6",
         "final_name": "color/blue/500", "hex": "#3b82f6", "note": "(would check for color/candidate/3b82f6)"},
    ],
}


class TestSyncNormalizedOutput:
    def test_dry_run_prints_summary(self, tmp_path, monkeypatch):
        _patch_sync_with_result(monkeypatch, _JS_RESULT_DRY)
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_file(f)
        result = runner.invoke(app, [
            "sync", "primitive-colors-normalized",
            "--normalized", str(f),
            "--dry-run",
        ])
        assert result.exit_code == 0, result.output
        assert "Dry-run summary" in result.output

    def test_dry_run_shows_total_created(self, tmp_path, monkeypatch):
        _patch_sync_with_result(monkeypatch, _JS_RESULT_DRY)
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_file(f)
        result = runner.invoke(app, [
            "sync", "primitive-colors-normalized",
            "--normalized", str(f),
            "--dry-run",
        ])
        assert "total=2" in result.output
        assert "created=2" in result.output

    def test_real_run_prints_sync_summary(self, tmp_path, monkeypatch):
        js_result = {**_JS_RESULT_DRY, "dry_run": False, "renamed": 1, "created": 1, "skipped": 0}
        _patch_sync_with_result(monkeypatch, js_result)
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_file(f)
        result = runner.invoke(app, [
            "sync", "primitive-colors-normalized",
            "--normalized", str(f),
        ])
        assert result.exit_code == 0, result.output
        assert "Sync summary" in result.output
        assert "renamed=1" in result.output

    def test_verbose_shows_log_entries(self, tmp_path, monkeypatch):
        _patch_sync_with_result(monkeypatch, _JS_RESULT_DRY)
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_file(f)
        result = runner.invoke(app, [
            "sync", "primitive-colors-normalized",
            "--normalized", str(f),
            "--dry-run", "--verbose",
        ])
        assert result.exit_code == 0, result.output
        assert "Detailed log" in result.output
        assert "color/red/500" in result.output

    def test_no_verbose_hides_log_entries(self, tmp_path, monkeypatch):
        _patch_sync_with_result(monkeypatch, _JS_RESULT_DRY)
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_file(f)
        result = runner.invoke(app, [
            "sync", "primitive-colors-normalized",
            "--normalized", str(f),
            "--dry-run",
        ])
        assert "Detailed log" not in result.output
        assert "would-rename-or-create" not in result.output

    def test_summary_uses_js_result_counts(self, tmp_path, monkeypatch):
        js_result = {**_JS_RESULT_DRY, "renamed": 3, "created": 5, "skipped": 1, "total": 9}
        _patch_sync_with_result(monkeypatch, js_result)
        f = tmp_path / "primitives.normalized.json"
        _write_normalized_file(f)
        result = runner.invoke(app, [
            "sync", "primitive-colors-normalized",
            "--normalized", str(f),
            "--dry-run",
        ])
        assert "total=9" in result.output
        assert "created=5" in result.output
        assert "renamed=3" in result.output
        assert "skipped=1" in result.output
