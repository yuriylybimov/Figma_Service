import json
import os
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def _raw_usage(tmp_path=None):
    """Minimal raw usage payload covering spacing and font-family."""
    return {
        "scanned_pages": 1,
        "scanned_nodes": 10,
        "spacing": [4, 8, 4, 16],
        "radius": [],
        "stroke_width": [],
        "font_size": [],
        "font_weight": [],
        "font_family": ["Inter", "Inter"],
        "line_height": [],
        "letter_spacing": [],
        "opacity": [],
    }


def test_suggest_writes_suggested_files(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage()))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()

    result = runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])
    assert result.exit_code == 0, result.output

    spacing_file = tokens_dir / "spacing.suggested.json"
    assert spacing_file.exists(), "spacing.suggested.json not created"
    data = json.loads(spacing_file.read_text())
    values = [e["value"] for e in data]
    assert 4.0 in values
    assert 8.0 in values
    assert 16.0 in values
    assert all("use_count" in e for e in data)


def test_suggest_output_includes_raw_values(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage()))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()

    runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])

    data = json.loads((tokens_dir / "spacing.suggested.json").read_text())
    for e in data:
        assert "raw_values" in e, f"raw_values missing on {e}"
        assert isinstance(e["raw_values"], list)


def test_suggest_does_not_touch_seed_files(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage()))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    seed_file = tokens_dir / "spacing.seed.json"
    seed_file.write_text("[]")

    runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])

    assert seed_file.read_text() == "[]"  # untouched


def test_suggest_skips_type_with_no_data(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage()))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()

    runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])

    # radius had no values → no suggested file
    assert not (tokens_dir / "radius.suggested.json").exists()


def test_suggest_missing_usage_file_exits_1(tmp_path):
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    result = runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(tmp_path / "missing.json"),
        "--tokens-dir", str(tokens_dir),
    ])
    assert result.exit_code == 1


def test_suggest_overwrites_existing_suggested_file(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage()))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    old = tokens_dir / "spacing.suggested.json"
    old.write_text('[{"name": "spacing/old", "value": 999}]')

    result = runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(old.read_text())
    assert all(e["value"] != 999 for e in data)


def test_suggest_full_radius_candidate_marker_in_file(tmp_path):
    raw = dict(_raw_usage())
    raw["radius"] = [4, 9999, 10000]
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(raw))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()

    result = runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])
    assert result.exit_code == 0, result.output

    data = json.loads((tokens_dir / "radius.suggested.json").read_text())
    full = [e for e in data if e.get("value", 0) >= 9999]
    assert len(full) >= 1
    for e in full:
        assert e.get("candidate") == "full-radius"


def test_suggest_font_family_file_has_no_raw_values(tmp_path):
    raw = dict(_raw_usage())
    raw["font_family"] = ["Inter", "Inter", "SF Pro Display"]
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(raw))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()

    runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])

    data = json.loads((tokens_dir / "font-family.suggested.json").read_text())
    for e in data:
        assert "raw_values" not in e
