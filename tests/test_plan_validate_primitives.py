import json
from pathlib import Path
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def test_validate_primitives_spacing_passes(tmp_path):
    seed = [
        {"name": "spacing/1", "value": 4},
        {"name": "spacing/2", "value": 8},
    ]
    f = tmp_path / "spacing.seed.json"
    f.write_text(json.dumps(seed))
    result = runner.invoke(app, ["plan", "validate-primitives", "spacing", "--seed-file", str(f)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output.lower()


def test_validate_primitives_fails_on_bad_name(tmp_path):
    seed = [{"name": "wrong/1", "value": 4}]
    f = tmp_path / "spacing.seed.json"
    f.write_text(json.dumps(seed))
    result = runner.invoke(app, ["plan", "validate-primitives", "spacing", "--seed-file", str(f)])
    assert result.exit_code == 1
    assert "name" in result.output.lower()


def test_validate_primitives_unknown_type(tmp_path):
    f = tmp_path / "foo.seed.json"
    f.write_text("[]")
    result = runner.invoke(app, ["plan", "validate-primitives", "foo", "--seed-file", str(f)])
    assert result.exit_code == 1
    assert "unknown type" in result.output.lower()


def test_validate_primitives_default_path_used_when_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    seed = [{"name": "radius/sm", "value": 4}]
    (tokens_dir / "radius.seed.json").write_text(json.dumps(seed))
    result = runner.invoke(app, ["plan", "validate-primitives", "radius"])
    assert result.exit_code == 0, result.output
