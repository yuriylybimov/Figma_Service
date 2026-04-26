import json
import os
from typer.testing import CliRunner
from run import app

runner = CliRunner()

VALID_STYLE = {
    "name": "typography/heading/sm/regular",
    "fontFamily": "font-family/font-family-sans-primary",
    "fontSize": "font-size/font-size-20",
    "fontWeight": "font-weight/font-weight-regular",
    "lineHeight": "line-height/line-height-24",
    "letterSpacing": "letter-spacing/tracking-0",
}

_ROLES_SIZES = [
    ("heading", "lg"), ("heading", "md"), ("heading", "sm"),
    ("body", "lg"), ("body", "sm"),
    ("label", "lg"), ("label", "sm"), ("label", "xs"),
]
_WEIGHTS = ["regular", "medium", "semibold"]


def _make_24_styles(override: dict | None = None, override_index: int = 0) -> list[dict]:
    """Return exactly 24 valid styles, optionally replacing one entry with overridden fields."""
    styles = []
    for role, size in _ROLES_SIZES:
        for weight in _WEIGHTS:
            style = {
                "name": f"typography/{role}/{size}/{weight}",
                "fontFamily": f"font-family/font-family-{role}",
                "fontSize": f"font-size/font-size-{14 + len(styles)}",
                "fontWeight": f"font-weight/font-weight-{weight}",
                "lineHeight": f"line-height/line-height-{20 + len(styles)}",
                "letterSpacing": "letter-spacing/tracking-0",
            }
            styles.append(style)
    assert len(styles) == 24
    if override is not None:
        styles[override_index] = dict(styles[override_index], **override)
    return styles


def _write_generated(tmp_path, styles, generated=True):
    typography_dir = tmp_path / "tokens" / "typography"
    typography_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "$schema": "composable-typography/v1",
        "$generated": generated,
        "styles": styles,
    }
    (typography_dir / "text-styles.generated.json").write_text(json.dumps(out))
    return str(typography_dir / "text-styles.generated.json")


def _invoke(tmp_path, extra_args=()):
    os.chdir(tmp_path)
    return runner.invoke(app, ["plan", "validate-text-styles"] + list(extra_args))


# --- file-level checks ---

def test_passes_on_valid_file(tmp_path):
    _write_generated(tmp_path, _make_24_styles())
    result = _invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert "pass" in result.output.lower() or "valid" in result.output.lower()


def test_fails_when_file_missing(tmp_path):
    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "validate-text-styles"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower() or "missing" in result.output.lower()


def test_fails_when_generated_flag_false(tmp_path):
    _write_generated(tmp_path, _make_24_styles(), generated=False)
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "$generated" in result.output


def test_fails_when_generated_flag_missing(tmp_path):
    typography_dir = tmp_path / "tokens" / "typography"
    typography_dir.mkdir(parents=True)
    out = {"$schema": "composable-typography/v1", "styles": _make_24_styles()}
    (typography_dir / "text-styles.generated.json").write_text(json.dumps(out))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "$generated" in result.output


# --- style count ---

def test_fails_on_wrong_style_count(tmp_path):
    _write_generated(tmp_path, [VALID_STYLE])  # 1, not 24
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "24" in result.output


def test_passes_with_exactly_24_styles(tmp_path):
    _write_generated(tmp_path, _make_24_styles())
    result = _invoke(tmp_path)
    assert result.exit_code == 0, result.output


# --- name format ---

def test_fails_on_bad_name_format(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"name": "heading/sm/regular"}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "name" in result.output.lower()


def test_fails_on_name_with_wrong_segment_count(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"name": "typography/heading/regular"}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1


# --- raw value detection ---

def test_fails_when_font_family_is_raw_string(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"fontFamily": "Urbanist"}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "fontFamily" in result.output or "raw" in result.output.lower()


def test_fails_when_font_size_is_raw_number(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"fontSize": 20}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "fontSize" in result.output or "raw" in result.output.lower()


def test_fails_when_font_weight_is_raw_number(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"fontWeight": 400}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "fontWeight" in result.output or "raw" in result.output.lower()


def test_fails_when_line_height_is_raw_number(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"lineHeight": 24}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "lineHeight" in result.output or "raw" in result.output.lower()


def test_fails_when_letter_spacing_is_raw_number(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"letterSpacing": 0}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "letterSpacing" in result.output or "raw" in result.output.lower()


def test_fails_when_ref_has_wrong_prefix(tmp_path):
    _write_generated(tmp_path, _make_24_styles(override={"fontSize": "color/primary"}))
    result = _invoke(tmp_path)
    assert result.exit_code == 1


# --- duplicate names ---

def test_fails_on_duplicate_names(tmp_path):
    styles = _make_24_styles()
    styles[1] = dict(styles[1], name=styles[0]["name"])  # duplicate first name
    _write_generated(tmp_path, styles)
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "duplicate" in result.output.lower()


# --- custom --file flag ---

def test_accepts_custom_file_path(tmp_path):
    path = _write_generated(tmp_path, _make_24_styles())
    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "validate-text-styles", "--file", path])
    assert result.exit_code == 0, result.output
    assert "not found" not in result.output.lower()
