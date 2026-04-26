import json
import os
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def _write_seed(path, entries):
    path.write_text(json.dumps(entries))


def _minimal_seeds(tokens_dir):
    pass


def _minimal_config(typography_dir):
    config = {
        "roles": {"heading": ["sm"], "body": ["sm"]},
        "weights": ["regular", "semibold"],
        "shared": {
            "fontFamily": "font-family/font-family-sans-primary",
            "letterSpacing": "letter-spacing/tracking-0"
        }
    }
    (typography_dir / "config.json").write_text(json.dumps(config))


def _minimal_scale(typography_dir):
    scale = {
        "heading": {"sm": {"fontSize": "font-size/font-size-20", "lineHeight": "line-height/line-height-24"}},
        "body": {"sm": {"fontSize": "font-size/font-size-14", "lineHeight": "line-height/line-height-20"}},
    }
    (typography_dir / "scale.json").write_text(json.dumps(scale))


def test_generate_text_styles_produces_correct_output(tmp_path):
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    typography_dir = tokens_dir / "typography"
    typography_dir.mkdir()

    _minimal_seeds(tokens_dir)
    _minimal_config(typography_dir)
    _minimal_scale(typography_dir)

    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "generate-text-styles"])
    assert result.exit_code == 0, result.output

    out = json.loads((typography_dir / "text-styles.generated.json").read_text())
    styles = out["styles"]

    # heading/sm/regular + heading/sm/semibold + body/sm/regular + body/sm/semibold = 4 styles
    assert len(styles) == 4

    heading_sm_regular = next(s for s in styles if s["name"] == "typography/heading/sm/regular")
    assert heading_sm_regular["fontFamily"] == "font-family/font-family-sans-primary"
    assert heading_sm_regular["fontSize"] == "font-size/font-size-20"
    assert heading_sm_regular["fontWeight"] == "font-weight/font-weight-regular"
    assert heading_sm_regular["lineHeight"] == "line-height/line-height-24"
    assert heading_sm_regular["letterSpacing"] == "letter-spacing/tracking-0"


def test_generate_text_styles_fails_on_missing_scale_entry(tmp_path):
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    typography_dir = tokens_dir / "typography"
    typography_dir.mkdir()

    _minimal_seeds(tokens_dir)
    config = {
        "roles": {"body": ["sm", "lg"]},
        "weights": ["regular"],
        "shared": {
            "fontFamily": "font-family/font-family-sans-primary",
            "letterSpacing": "letter-spacing/tracking-0"
        }
    }
    # scale is missing body/lg entry
    scale = {
        "body": {"sm": {"fontSize": "font-size/font-size-14", "lineHeight": "line-height/line-height-20"}}
    }
    (typography_dir / "config.json").write_text(json.dumps(config))
    (typography_dir / "scale.json").write_text(json.dumps(scale))

    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "generate-text-styles"])
    assert result.exit_code == 1
    assert "body/lg" in result.output


def test_generate_is_idempotent(tmp_path):
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    typography_dir = tokens_dir / "typography"
    typography_dir.mkdir()

    _minimal_seeds(tokens_dir)
    _minimal_config(typography_dir)
    _minimal_scale(typography_dir)

    os.chdir(tmp_path)
    runner.invoke(app, ["plan", "generate-text-styles"])
    first = (typography_dir / "text-styles.generated.json").read_text()
    runner.invoke(app, ["plan", "generate-text-styles"])
    second = (typography_dir / "text-styles.generated.json").read_text()
    assert first == second
