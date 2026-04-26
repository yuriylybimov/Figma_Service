"""Tests for `plan suggest-semantic-tokens` and `plan suggest-semantic-tokens-contextual` CLI commands."""
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from run import app

runner = CliRunner()

_PRIMITIVES = {
    "colors": [
        {"hex": "#1a1a1a", "candidate_name": "color/candidate/1a1a1a",
         "auto_name": "color/gray/900", "final_name": "color/gray/900",
         "fill_count": 5, "stroke_count": 0, "examples": []},
        {"hex": "#737373", "candidate_name": "color/candidate/737373",
         "auto_name": "color/gray/500", "final_name": "color/gray/500",
         "fill_count": 3, "stroke_count": 0, "examples": []},
        {"hex": "#f5f5f5", "candidate_name": "color/candidate/f5f5f5",
         "auto_name": "color/gray/100", "final_name": "color/gray/100",
         "fill_count": 2, "stroke_count": 0, "examples": []},
    ]
}


def _write_primitives(tmp_path, data=None):
    p = tmp_path / "primitives.normalized.json"
    p.write_text(json.dumps(data or _PRIMITIVES), encoding="utf-8")
    return str(p)


def test_stdout_lists_suggestions(tmp_path):
    prim = _write_primitives(tmp_path)
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim])
    assert result.exit_code == 0
    assert "color/canvas/primary" in result.output
    assert "color/text/primary" in result.output


def test_stdout_shows_token_count(tmp_path):
    prim = _write_primitives(tmp_path)
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim])
    assert result.exit_code == 0
    assert "token(s)" in result.output


def test_no_out_writes_no_file(tmp_path):
    prim = _write_primitives(tmp_path)
    runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim])
    assert not (tmp_path / "semantics.suggested.json").exists()


def test_out_writes_json_file(tmp_path):
    prim = _write_primitives(tmp_path)
    out = str(tmp_path / "semantics.suggested.json")
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim, "--out", out])
    assert result.exit_code == 0
    assert Path(out).exists()


def test_out_json_has_required_keys(tmp_path):
    prim = _write_primitives(tmp_path)
    out = str(tmp_path / "semantics.suggested.json")
    runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim, "--out", out])
    data = json.loads(Path(out).read_text())
    assert "generated_at" in data
    assert "source_primitives_file" in data
    assert "suggestions" in data
    assert isinstance(data["suggestions"], dict)


def test_out_suggestions_are_valid_semantic_names(tmp_path):
    from plan_colors import _validate_semantic_name
    prim = _write_primitives(tmp_path)
    out = str(tmp_path / "out.json")
    runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim, "--out", out])
    data = json.loads(Path(out).read_text())
    for name in data["suggestions"]:
        assert _validate_semantic_name(name) is None, f"{name!r} failed validation"


def test_missing_primitives_file_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens",
                                 "--primitives", str(tmp_path / "missing.json")])
    assert result.exit_code != 0
    assert "ERROR" in result.output


def test_primitives_missing_colors_key_exits_nonzero(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"not_colors": []}), encoding="utf-8")
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", str(p)])
    assert result.exit_code != 0
    assert "ERROR" in result.output


def test_empty_colors_prints_none_message(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"colors": []}), encoding="utf-8")
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", str(p)])
    assert result.exit_code == 0
    assert "none" in result.output


def test_default_out_never_writes_semantics_seed(tmp_path):
    """Guard: omitting --out must never create semantics.seed.json."""
    prim = _write_primitives(tmp_path)
    result = runner.invoke(app, ["plan", "suggest-semantic-tokens", "--primitives", prim])
    assert result.exit_code == 0
    # No file anywhere in tmp_path named semantics.seed.json
    for f in tmp_path.rglob("semantics.seed.json"):
        pytest.fail(f"Command wrote semantics.seed.json at {f}")


# ---------------------------------------------------------------------------
# suggest-semantic-tokens-contextual (experimental)
# ---------------------------------------------------------------------------

_CONTEXT = [
    {
        "hex": "#1a1a1a",
        "final_name": "color/gray/900",
        "fill_count": 80,
        "stroke_count": 10,
        "text_count": 10,
        "use_count": 100,
        "page_count": 2,
        "samples": [],
    },
    {
        "hex": "#f5f5f5",
        "final_name": "color/gray/100",
        "fill_count": 5,
        "stroke_count": 5,
        "text_count": 90,
        "use_count": 100,
        "page_count": 2,
        "samples": [],
    },
]


def _write_context(tmp_path, data=None):
    p = tmp_path / "color_usage_context.json"
    p.write_text(json.dumps(data if data is not None else _CONTEXT), encoding="utf-8")
    return str(p)


def test_contextual_writes_contextual_json(tmp_path):
    prim = _write_primitives(tmp_path)
    ctx = _write_context(tmp_path)
    out = str(tmp_path / "semantics.contextual.json")
    result = runner.invoke(
        app,
        ["plan", "suggest-semantic-tokens-contextual",
         "--context", ctx, "--primitives", prim, "--out", out],
    )
    assert result.exit_code == 0
    assert Path(out).exists()
    data = json.loads(Path(out).read_text())
    assert "suggestions" in data
    assert "generated_at" in data


def test_contextual_out_to_seed_exits_nonzero(tmp_path):
    """Guard: --out pointing to semantics.seed.json must be rejected."""
    prim = _write_primitives(tmp_path)
    ctx = _write_context(tmp_path)
    seed = str(tmp_path / "semantics.seed.json")
    result = runner.invoke(
        app,
        ["plan", "suggest-semantic-tokens-contextual",
         "--context", ctx, "--primitives", prim, "--out", seed],
    )
    assert result.exit_code != 0
    assert "ERROR" in result.output or "ERROR" in (result.stderr or "")
    assert not Path(seed).exists()


def test_contextual_out_to_normalized_exits_nonzero(tmp_path):
    """Guard: --out pointing to semantics.normalized.json must be rejected."""
    prim = _write_primitives(tmp_path)
    ctx = _write_context(tmp_path)
    normalized = str(tmp_path / "semantics.normalized.json")
    result = runner.invoke(
        app,
        ["plan", "suggest-semantic-tokens-contextual",
         "--context", ctx, "--primitives", prim, "--out", normalized],
    )
    assert result.exit_code != 0
    assert not Path(normalized).exists()


def test_contextual_missing_context_exits_nonzero(tmp_path):
    prim = _write_primitives(tmp_path)
    result = runner.invoke(
        app,
        ["plan", "suggest-semantic-tokens-contextual",
         "--context", str(tmp_path / "missing.json"), "--primitives", prim],
    )
    assert result.exit_code != 0
    assert "ERROR" in result.output or "ERROR" in (result.stderr or "")
