"""Tests for `read typography-audit` command and _group_typography_combinations."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from run import app
from read_handlers import _group_typography_combinations

runner = CliRunner()

# ---------------------------------------------------------------------------
# _group_typography_combinations — pure host-side grouping logic
# ---------------------------------------------------------------------------

def _node(family="Inter", style="Regular", size=14, weight=400, lh=20.0, ls=0.0):
    return {
        "fontFamily": family,
        "fontStyle": style,
        "fontSize": size,
        "fontWeight": weight,
        "lineHeight": lh,
        "letterSpacing": ls,
    }


def test_group_empty_list():
    assert _group_typography_combinations([]) == []


def test_group_single_node():
    result = _group_typography_combinations([_node()])
    assert len(result) == 1
    assert result[0]["usageCount"] == 1


def test_group_identical_nodes_counted_together():
    nodes = [_node(), _node(), _node()]
    result = _group_typography_combinations(nodes)
    assert len(result) == 1
    assert result[0]["usageCount"] == 3


def test_group_different_sizes_produce_separate_entries():
    nodes = [_node(size=12), _node(size=14), _node(size=16)]
    result = _group_typography_combinations(nodes)
    assert len(result) == 3


def test_group_different_families_produce_separate_entries():
    nodes = [_node(family="Inter"), _node(family="Roboto")]
    result = _group_typography_combinations(nodes)
    assert len(result) == 2


def test_group_sorted_by_usage_count_descending():
    nodes = [
        _node(size=12),                  # 1 occurrence
        _node(size=14), _node(size=14),  # 2 occurrences
        _node(size=16), _node(size=16), _node(size=16),  # 3 occurrences
    ]
    result = _group_typography_combinations(nodes)
    counts = [r["usageCount"] for r in result]
    assert counts == sorted(counts, reverse=True)


def test_group_preserves_field_values():
    node = _node(family="Roboto", style="Bold", size=18, weight=700, lh=24.0, ls=0.5)
    result = _group_typography_combinations([node])
    r = result[0]
    assert r["fontFamily"] == "Roboto"
    assert r["fontStyle"] == "Bold"
    assert r["fontSize"] == 18
    assert r["fontWeight"] == 700
    assert r["lineHeight"] == 24.0
    assert r["letterSpacing"] == 0.5


def test_group_none_values_treated_as_empty_string_key():
    n1 = {"fontFamily": None, "fontStyle": None, "fontSize": None,
          "fontWeight": None, "lineHeight": None, "letterSpacing": None}
    n2 = {"fontFamily": None, "fontStyle": None, "fontSize": None,
          "fontWeight": None, "lineHeight": None, "letterSpacing": None}
    result = _group_typography_combinations([n1, n2])
    assert len(result) == 1
    assert result[0]["usageCount"] == 2


def test_group_mixed_none_and_value_are_distinct():
    n_none = {"fontFamily": None, "fontStyle": None, "fontSize": None,
              "fontWeight": None, "lineHeight": None, "letterSpacing": None}
    n_val  = _node(family="Inter", style="Regular", size=14, weight=400, lh=20.0, ls=0.0)
    result = _group_typography_combinations([n_none, n_val])
    assert len(result) == 2


# ---------------------------------------------------------------------------
# CLI integration — command wiring (no Figma round-trip)
# ---------------------------------------------------------------------------

_FAKE_BRIDGE_RESULT = {
    "text_styles": [
        {
            "id": "S:abc123",
            "name": "Body/Regular",
            "key": "abc123key",
            "description": "",
            "fontFamily": "Inter",
            "fontStyle": "Regular",
            "fontSize": 14,
            "fontWeight": 400,
            "lineHeight": 20.0,
            "letterSpacing": 0.0,
        }
    ],
    "typography_usage": [
        {
            "fontFamily": "Inter",
            "fontStyle": "Regular",
            "fontSize": 14,
            "fontWeight": 400,
            "lineHeight": 20.0,
            "letterSpacing": 0.0,
            "usageCount": 42,
        }
    ],
    "summary": {
        "text_style_count": 1,
        "unique_typography_combinations": 1,
        "scanned_text_nodes": 42,
    },
}


def _fake_bridge_exec(url, user_js, rid, *, inline_cap, timeout_s, mount_timeout_s):
    return {"status": "ok", "result": _FAKE_BRIDGE_RESULT}


def test_command_exists_in_read_subapp():
    result = runner.invoke(app, ["read", "--help"])
    assert result.exit_code == 0
    assert "typography-audit" in result.output


def test_missing_out_option_exits_nonzero():
    result = runner.invoke(
        app,
        ["read", "typography-audit"],
        env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
    )
    assert result.exit_code != 0


def test_command_writes_output_file(tmp_path):
    out = str(tmp_path / "audit.json")
    with patch("read_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        result = runner.invoke(
            app,
            ["read", "typography-audit", "--out", out],
            env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
        )
    assert result.exit_code == 0
    assert Path(out).exists()


def test_output_file_has_required_keys(tmp_path):
    out = str(tmp_path / "audit.json")
    with patch("read_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        runner.invoke(
            app,
            ["read", "typography-audit", "--out", out],
            env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
        )
    data = json.loads(Path(out).read_text())
    assert "text_styles" in data
    assert "typography_usage" in data
    assert "summary" in data


def test_output_summary_has_required_keys(tmp_path):
    out = str(tmp_path / "audit.json")
    with patch("read_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        runner.invoke(
            app,
            ["read", "typography-audit", "--out", out],
            env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
        )
    data = json.loads(Path(out).read_text())
    summary = data["summary"]
    assert "text_style_count" in summary
    assert "unique_typography_combinations" in summary


def test_text_style_entry_has_required_fields(tmp_path):
    out = str(tmp_path / "audit.json")
    with patch("read_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        runner.invoke(
            app,
            ["read", "typography-audit", "--out", out],
            env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
        )
    data = json.loads(Path(out).read_text())
    style = data["text_styles"][0]
    for field in ("id", "name", "fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing"):
        assert field in style, f"missing field: {field}"


def test_typography_usage_entry_has_usage_count(tmp_path):
    out = str(tmp_path / "audit.json")
    with patch("read_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        runner.invoke(
            app,
            ["read", "typography-audit", "--out", out],
            env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
        )
    data = json.loads(Path(out).read_text())
    usage = data["typography_usage"][0]
    assert "usageCount" in usage
    assert isinstance(usage["usageCount"], int)


# ---------------------------------------------------------------------------
# Guard: seed files must not be modified
# ---------------------------------------------------------------------------

_SEED_NAMES = [
    "font-size.seed.json",
    "font-family.seed.json",
    "font-weight.seed.json",
    "letter-spacing.seed.json",
    "line-height.seed.json",
    "primitives-semantic.seed.json",
]

_TOKENS_DIR = Path(__file__).parent.parent / "tokens"


def _read_seed_checksums():
    result = {}
    for name in _SEED_NAMES:
        p = _TOKENS_DIR / name
        if p.exists():
            result[name] = p.read_bytes()
    return result


def test_no_seed_files_modified(tmp_path):
    before = _read_seed_checksums()
    out = str(tmp_path / "audit.json")
    with patch("read_handlers._bridge_exec", side_effect=_fake_bridge_exec):
        runner.invoke(
            app,
            ["read", "typography-audit", "--out", out],
            env={"FIGMA_FILE_URL": "https://figma.com/file/fake/test"},
        )
    after = _read_seed_checksums()
    for name, content in before.items():
        assert after[name] == content, f"Seed file was modified: {name}"
