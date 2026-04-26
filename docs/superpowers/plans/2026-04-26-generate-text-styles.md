# Phase 7.6 — Generate Text Styles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `plan generate-text-styles` CLI command that reads `tokens/typography/config.json` + `tokens/typography/scale.json` and overwrites `tokens/typography/text-styles.generated.json` deterministically.

**Architecture:** A pure function `_generate_text_styles(config, scale)` does the cartesian product `role × size × weight`, resolves all values to token reference strings (no raw numbers), validates fail-fast on missing scale entries or invalid weights, and returns a sorted list. The CLI command wraps it with file I/O. Both live in `plan_handlers.py`, following the existing pattern for plan commands. Output JSON is sorted-keys, sorted by style name.

**Tech Stack:** Python 3, Typer CLI, stdlib `json`, pytest + typer.testing.CliRunner.

---

## Files

| Action  | Path                                                                 | Responsibility                              |
|---------|----------------------------------------------------------------------|---------------------------------------------|
| Modify  | `plan_handlers.py`                                                   | Add `_generate_text_styles()` + CLI command |
| Create  | `tests/test_generate_text_styles.py`                                 | Unit + CLI + reproducibility tests          |

---

## Task 1 — Pure generator function with fail-fast validation

**Files:**
- Modify: `plan_handlers.py` (add `_generate_text_styles` before the CLI commands)
- Create: `tests/test_generate_text_styles.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_generate_text_styles.py`:

```python
import pytest
from plan_handlers import _generate_text_styles


MINIMAL_CONFIG = {
    "roles": {
        "heading": ["lg", "sm"],
        "label": ["xs"],
    },
    "weights": ["regular", "semibold"],
    "shared": {
        "fontFamily": "font-family/font-family-sans-primary",
        "letterSpacing": "letter-spacing/tracking-0",
    },
}

MINIMAL_SCALE = {
    "heading": {
        "lg": {"fontSize": "font-size/font-size-32", "lineHeight": "line-height/line-height-36"},
        "sm": {"fontSize": "font-size/font-size-20", "lineHeight": "line-height/line-height-24"},
    },
    "label": {
        "xs": {"fontSize": "font-size/font-size-10", "lineHeight": "line-height/line-height-16"},
    },
}


def test_returns_correct_count():
    # 2 sizes for heading + 1 for label = 3 sizes; 2 weights = 6 styles
    styles = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    assert len(styles) == 6


def test_style_names_follow_convention():
    styles = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    names = {s["name"] for s in styles}
    assert "typography/heading/lg/regular" in names
    assert "typography/heading/lg/semibold" in names
    assert "typography/label/xs/regular" in names


def test_all_values_are_token_references():
    styles = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    for style in styles:
        assert style["fontFamily"].startswith("font-family/"), style
        assert style["fontSize"].startswith("font-size/"), style
        assert style["fontWeight"].startswith("font-weight/"), style
        assert style["lineHeight"].startswith("line-height/"), style
        assert style["letterSpacing"].startswith("letter-spacing/"), style


def test_font_weight_token_reference_uses_weight_name():
    styles = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    regular_style = next(s for s in styles if s["name"] == "typography/heading/lg/regular")
    semibold_style = next(s for s in styles if s["name"] == "typography/heading/lg/semibold")
    assert regular_style["fontWeight"] == "font-weight/font-weight-regular"
    assert semibold_style["fontWeight"] == "font-weight/font-weight-semibold"


def test_shared_properties_applied_to_all_styles():
    styles = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    for style in styles:
        assert style["fontFamily"] == "font-family/font-family-sans-primary"
        assert style["letterSpacing"] == "letter-spacing/tracking-0"


def test_output_sorted_by_name():
    styles = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    names = [s["name"] for s in styles]
    assert names == sorted(names)


def test_missing_role_in_scale_raises():
    bad_scale = {
        "heading": {
            "lg": {"fontSize": "font-size/font-size-32", "lineHeight": "line-height/line-height-36"},
            # "sm" missing
        },
        "label": {
            "xs": {"fontSize": "font-size/font-size-10", "lineHeight": "line-height/line-height-16"},
        },
    }
    with pytest.raises(ValueError, match="heading/sm"):
        _generate_text_styles(MINIMAL_CONFIG, bad_scale)


def test_missing_role_group_in_scale_raises():
    bad_scale = {
        "heading": {
            "lg": {"fontSize": "font-size/font-size-32", "lineHeight": "line-height/line-height-36"},
            "sm": {"fontSize": "font-size/font-size-20", "lineHeight": "line-height/line-height-24"},
        },
        # "label" role missing entirely
    }
    with pytest.raises(ValueError, match="label"):
        _generate_text_styles(MINIMAL_CONFIG, bad_scale)


def test_invalid_weight_raises():
    bad_config = {
        **MINIMAL_CONFIG,
        "weights": ["regular", "ultrablack"],  # invalid
    }
    with pytest.raises(ValueError, match="ultrablack"):
        _generate_text_styles(bad_config, MINIMAL_SCALE)


def test_deterministic_across_two_calls():
    styles_a = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    styles_b = _generate_text_styles(MINIMAL_CONFIG, MINIMAL_SCALE)
    assert styles_a == styles_b
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
.venv/bin/python -m pytest tests/test_generate_text_styles.py -v
```

Expected: `ImportError: cannot import name '_generate_text_styles' from 'plan_handlers'`

- [ ] **Step 3: Add `_generate_text_styles` to `plan_handlers.py`**

Open `plan_handlers.py`. Add this function after the existing imports and before the first `@plan_app.command(...)` decorator. The valid weights match the seed file at `tokens/font-weight.seed.json`:

```python
_VALID_WEIGHTS = {"regular", "medium", "semibold", "bold"}


def _generate_text_styles(config: dict, scale: dict) -> list[dict]:
    """Generate typography styles from config + scale. All values are token references.

    Raises ValueError on missing scale entries or unknown weights.
    Returns styles sorted by name.
    """
    roles: dict[str, list[str]] = config["roles"]
    weights: list[str] = config["weights"]
    shared: dict[str, str] = config["shared"]

    invalid_weights = [w for w in weights if w not in _VALID_WEIGHTS]
    if invalid_weights:
        raise ValueError(
            f"Invalid weight(s): {invalid_weights}. Valid: {sorted(_VALID_WEIGHTS)}"
        )

    styles: list[dict] = []

    for role, sizes in roles.items():
        role_scale = scale.get(role)
        if role_scale is None:
            raise ValueError(
                f"scale.json missing role '{role}'. "
                f"Add a '{role}' key to tokens/typography/scale.json."
            )
        for size in sizes:
            size_entry = role_scale.get(size)
            if size_entry is None:
                raise ValueError(
                    f"scale.json missing size '{size}' under role '{role}' ({role}/{size}). "
                    f"Add it to tokens/typography/scale.json."
                )
            for weight in weights:
                styles.append({
                    "name": f"typography/{role}/{size}/{weight}",
                    "fontFamily": shared["fontFamily"],
                    "fontSize": size_entry["fontSize"],
                    "fontWeight": f"font-weight/font-weight-{weight}",
                    "lineHeight": size_entry["lineHeight"],
                    "letterSpacing": shared["letterSpacing"],
                })

    return sorted(styles, key=lambda s: s["name"])
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/python -m pytest tests/test_generate_text_styles.py -v
```

Expected: 10 PASSED

- [ ] **Step 5: Commit**

```bash
git add plan_handlers.py tests/test_generate_text_styles.py
git commit -m "feat(typography): add _generate_text_styles pure function with fail-fast validation"
```

---

## Task 2 — CLI command `plan generate-text-styles`

**Files:**
- Modify: `plan_handlers.py` (add command after `plan_validate_primitives`)
- Modify: `tests/test_generate_text_styles.py` (add CLI tests)

- [ ] **Step 1: Add CLI tests to `tests/test_generate_text_styles.py`**

Add these imports and fixtures at the **top** of `tests/test_generate_text_styles.py` (after the existing `import pytest` and `from plan_handlers import _generate_text_styles`), then append the test functions at the bottom:

```python
# Add near the top of the file (after existing imports):
import json
from pathlib import Path
from typer.testing import CliRunner
from run import app

runner = CliRunner()
```

Then append these at the bottom of the file:

```python
FULL_CONFIG = {
    "roles": {
        "heading": ["lg", "md", "sm"],
        "body": ["lg", "sm"],
        "label": ["lg", "sm", "xs"],
    },
    "weights": ["regular", "medium", "semibold"],
    "shared": {
        "fontFamily": "font-family/font-family-sans-primary",
        "letterSpacing": "letter-spacing/tracking-0",
    },
}

FULL_SCALE = {
    "heading": {
        "lg": {"fontSize": "font-size/font-size-32", "lineHeight": "line-height/line-height-36"},
        "md": {"fontSize": "font-size/font-size-24", "lineHeight": "line-height/line-height-28"},
        "sm": {"fontSize": "font-size/font-size-20", "lineHeight": "line-height/line-height-24"},
    },
    "body": {
        "lg": {"fontSize": "font-size/font-size-16", "lineHeight": "line-height/line-height-20"},
        "sm": {"fontSize": "font-size/font-size-14", "lineHeight": "line-height/line-height-20"},
    },
    "label": {
        "lg": {"fontSize": "font-size/font-size-14", "lineHeight": "line-height/line-height-16"},
        "sm": {"fontSize": "font-size/font-size-12", "lineHeight": "line-height/line-height-16"},
        "xs": {"fontSize": "font-size/font-size-10", "lineHeight": "line-height/line-height-16"},
    },
}


def test_cli_generates_output_file(tmp_path):
    config_file = tmp_path / "config.json"
    scale_file = tmp_path / "scale.json"
    out_file = tmp_path / "text-styles.generated.json"

    config_file.write_text(json.dumps(FULL_CONFIG))
    scale_file.write_text(json.dumps(FULL_SCALE))

    result = runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(scale_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert data["$generated"] is True
    assert len(data["styles"]) == 24  # (3+2+3 sizes) × 3 weights


def test_cli_output_has_correct_metadata(tmp_path):
    config_file = tmp_path / "config.json"
    scale_file = tmp_path / "scale.json"
    out_file = tmp_path / "text-styles.generated.json"

    config_file.write_text(json.dumps(FULL_CONFIG))
    scale_file.write_text(json.dumps(FULL_SCALE))

    runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(scale_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    assert data["$schema"] == "composable-typography/v1"
    assert data["$generated"] is True
    assert "tokens/typography/config.json" in data["$source"]
    assert "tokens/typography/scale.json" in data["$source"]
    assert "tokens/text-styles.seed.json" in data["$deprecated"]


def test_cli_output_styles_sorted_by_name(tmp_path):
    config_file = tmp_path / "config.json"
    scale_file = tmp_path / "scale.json"
    out_file = tmp_path / "text-styles.generated.json"

    config_file.write_text(json.dumps(FULL_CONFIG))
    scale_file.write_text(json.dumps(FULL_SCALE))

    runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(scale_file),
        "--out", str(out_file),
    ])

    data = json.loads(out_file.read_text())
    names = [s["name"] for s in data["styles"]]
    assert names == sorted(names)


def test_cli_reproducible_output(tmp_path):
    config_file = tmp_path / "config.json"
    scale_file = tmp_path / "scale.json"
    out_file = tmp_path / "text-styles.generated.json"

    config_file.write_text(json.dumps(FULL_CONFIG))
    scale_file.write_text(json.dumps(FULL_SCALE))

    args = [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(scale_file),
        "--out", str(out_file),
    ]

    runner.invoke(app, args)
    first_content = out_file.read_text()

    runner.invoke(app, args)
    second_content = out_file.read_text()

    assert first_content == second_content


def test_cli_fails_on_missing_config(tmp_path):
    scale_file = tmp_path / "scale.json"
    scale_file.write_text(json.dumps(FULL_SCALE))

    result = runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(tmp_path / "missing.json"),
        "--scale", str(scale_file),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_cli_fails_on_missing_scale(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(FULL_CONFIG))

    result = runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(tmp_path / "missing.json"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_cli_fails_on_missing_scale_entry(tmp_path):
    config_file = tmp_path / "config.json"
    scale_file = tmp_path / "scale.json"

    config_file.write_text(json.dumps(FULL_CONFIG))
    bad_scale = {k: v for k, v in FULL_SCALE.items() if k != "label"}  # drop label
    scale_file.write_text(json.dumps(bad_scale))

    result = runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(scale_file),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code == 1
    assert "label" in result.output.lower()


def test_cli_fails_on_invalid_weight(tmp_path):
    bad_config = {**FULL_CONFIG, "weights": ["regular", "ultrablack"]}
    config_file = tmp_path / "config.json"
    scale_file = tmp_path / "scale.json"

    config_file.write_text(json.dumps(bad_config))
    scale_file.write_text(json.dumps(FULL_SCALE))

    result = runner.invoke(app, [
        "plan", "generate-text-styles",
        "--config", str(config_file),
        "--scale", str(scale_file),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code == 1
    assert "ultrablack" in result.output.lower()
```

- [ ] **Step 2: Run new tests to verify they fail**

```
.venv/bin/python -m pytest tests/test_generate_text_styles.py -v -k "cli"
```

Expected: all CLI tests FAIL with "No such command 'generate-text-styles'"

- [ ] **Step 3: Add `plan generate-text-styles` command to `plan_handlers.py`**

Append this command at the end of `plan_handlers.py`, after the last existing `@plan_app.command(...)` block:

```python
@plan_app.command("generate-text-styles")
def plan_generate_text_styles(
    config: str = typer.Option(
        str(_TOKENS_DIR / "typography" / "config.json"),
        "--config",
        help="Path to config.json (default: tokens/typography/config.json).",
    ),
    scale: str = typer.Option(
        str(_TOKENS_DIR / "typography" / "scale.json"),
        "--scale",
        help="Path to scale.json (default: tokens/typography/scale.json).",
    ),
    out: str = typer.Option(
        str(_TOKENS_DIR / "typography" / "text-styles.generated.json"),
        "--out",
        help="Output path (default: tokens/typography/text-styles.generated.json).",
    ),
) -> None:
    """Generate text-styles.generated.json from config.json + scale.json.

    Overwrites output on every run. Source of truth is config + scale, not
    the generated file. Re-run whenever config or scale changes.
    """
    config_path = Path(config).resolve()
    scale_path = Path(scale).resolve()
    out_path = Path(out).resolve()

    if not config_path.exists():
        typer.echo(f"ERROR: config file not found: {config_path}", err=True)
        raise typer.Exit(1)
    if not scale_path.exists():
        typer.echo(f"ERROR: scale file not found: {scale_path}", err=True)
        raise typer.Exit(1)

    try:
        config_data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read config: {e}", err=True)
        raise typer.Exit(1)

    try:
        scale_data = json.loads(scale_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read scale: {e}", err=True)
        raise typer.Exit(1)

    try:
        styles = _generate_text_styles(config_data, scale_data)
    except ValueError as e:
        typer.echo(f"ERROR: {e}", err=True)
        raise typer.Exit(1)

    result = {
        "$schema": "composable-typography/v1",
        "$generated": True,
        "$source": ["tokens/typography/config.json", "tokens/typography/scale.json"],
        "$deprecated": ["tokens/text-styles.seed.json"],
        "styles": styles,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"✓ {len(styles)} text styles written to {out_path}")
```

- [ ] **Step 4: Run all tests to verify they pass**

```
.venv/bin/python -m pytest tests/test_generate_text_styles.py -v
```

Expected: all 18 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add plan_handlers.py tests/test_generate_text_styles.py
git commit -m "feat(typography): add plan generate-text-styles CLI command"
```

---

## Task 3 — Run generator against real files and verify output matches

**Files:**
- No file changes — verification only

- [ ] **Step 1: Run the generator against the real config + scale**

```
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
.venv/bin/python run.py plan generate-text-styles
```

Expected output:
```
✓ 24 text styles written to .../tokens/typography/text-styles.generated.json
```

- [ ] **Step 2: Verify style count**

```
.venv/bin/python -c "
import json
data = json.load(open('tokens/typography/text-styles.generated.json'))
print(f'styles: {len(data[\"styles\"])}')
print('first:', data['styles'][0]['name'])
print('last:', data['styles'][-1]['name'])
"
```

Expected:
```
styles: 24
first: typography/body/lg/medium
last: typography/label/xs/semibold
```

(Exact first/last depend on sort order of role names — `body` sorts before `heading` and `label`.)

- [ ] **Step 3: Verify reproducibility**

```
.venv/bin/python run.py plan generate-text-styles
.venv/bin/python -c "
import hashlib, json
text = open('tokens/typography/text-styles.generated.json').read()
print('sha256:', hashlib.sha256(text.encode()).hexdigest()[:16])
"
# Run again and confirm same hash
.venv/bin/python run.py plan generate-text-styles
.venv/bin/python -c "
import hashlib
text = open('tokens/typography/text-styles.generated.json').read()
print('sha256:', hashlib.sha256(text.encode()).hexdigest()[:16])
"
```

Expected: both lines print the same sha256 prefix.

- [ ] **Step 4: Run the full test suite to check for regressions**

```
.venv/bin/python -m pytest tests/ -v
```

Expected: all existing tests PASS, all new tests PASS, zero regressions.

- [ ] **Step 5: Commit the regenerated file**

```bash
git add tokens/typography/text-styles.generated.json
git commit -m "chore(typography): regenerate text-styles.generated.json from generator"
```

---

## Risks

| Risk | Mitigation |
|------|------------|
| `sort_keys=True` reorders fields inside each style object | Accepted — output is a generated artifact, not hand-edited; consumers read by key not position |
| Real config/scale may diverge from hand-authored generated file | Step 3 catches this; generator is authoritative, file gets overwritten |
| Future weight names added to config but not to `_VALID_WEIGHTS` | Fail-fast `ValueError` surfaces immediately on next generator run |
