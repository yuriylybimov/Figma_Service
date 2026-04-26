# tests/test_plan_validate_semantic_primitives_cmd.py
import json
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def test_validate_semantic_primitives_passes(tmp_path):
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()

    (tokens_dir / "spacing.seed.json").write_text(
        json.dumps([{"name": "spacing/1", "value": 4}])
    )
    (tokens_dir / "radius.seed.json").write_text(
        json.dumps([{"name": "radius/sm", "value": 4}])
    )
    semantic = {"spacing/component/padding": "spacing/1", "radius/component/button": "radius/sm"}
    (tokens_dir / "primitives-semantic.seed.json").write_text(json.dumps(semantic))

    import os
    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "validate-semantic-primitives"])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output.lower()


def test_validate_semantic_primitives_fails_on_bad_ref(tmp_path):
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    (tokens_dir / "spacing.seed.json").write_text(
        json.dumps([{"name": "spacing/1", "value": 4}])
    )
    semantic = {"spacing/component/x": "spacing/99"}
    (tokens_dir / "primitives-semantic.seed.json").write_text(json.dumps(semantic))

    import os
    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "validate-semantic-primitives"])
    assert result.exit_code == 1
