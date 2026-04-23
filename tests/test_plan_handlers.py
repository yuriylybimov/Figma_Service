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
