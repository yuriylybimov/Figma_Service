# Primitive Token Type Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the token system beyond colors to support spacing, radius, stroke-width, font-family, font-weight, font-size, line-height, letter-spacing, and opacity — following the same seed → validate → sync pattern already proven for colors.

**Architecture:** Each new token type follows the existing pipeline: a hand-authored seed JSON is the source of truth; a validator checks it before any sync; a JS template syncs values to Figma variables. No Figma reads are required; no existing color commands are modified.

**Tech Stack:** Python 3 (Typer CLI, Pydantic), pytest, plain JSON seed files, JavaScript Figma variable templates.

---

## Constraints (always active)

- Do NOT modify or refactor the existing color pipeline.
- Do NOT change existing working commands or CLI behavior.
- Seed files are the only source of truth — never auto-overwrite them.
- Figma reading is allowed only for audit/suggestion, never as source of truth.
- Do NOT run `sync` during development — use `--dry-run` only.
- Do NOT use Git commands.

---

## Scope overview

| Roadmap item | Plan phase | Status |
|---|---|---|
| 2. Expand primitive token types | Phase 1–3 | ✅ DONE |
| 3. Create / structure semantic seed file | Phase 4.1 | ✅ DONE |
| 3a. Audit real typography from Figma | Phase 4.5 | ✅ DONE |
| 3b. Refine typography semantics from audit | Phase 4.6 | ✅ DONE |
| 4. Define semantic tokens (manual) | Phase 4 (manual step) | ✅ DONE |
| 5. Validate semantic tokens | Phase 5 | ✅ DONE |
| 6. Sync primitive tokens to Figma | Phase 6 | ✅ DONE |
| 7. Read primitive variables (audit only) | Phase 7 (optional) | ⬜ TODO |
| 7.5. Composable typography system (config + scale → generated styles) | Phase 7.5 | ✅ DONE |
| 7.6. Generate text styles from config + scale | Phase 7.6 | ✅ DONE |
| 8. Sync text styles to Figma | Phase 8 | ✅ DONE |
| 9. Create component token seed files | Phase 9 | ⬜ TODO |
| 10. Validate component tokens | Phase 9 | ⬜ TODO |
| 11. Sync component variables to Figma | Phase 10 | ⬜ TODO |

> **Typography flow:**
> Figma → audit (4.5) → semantic refinement (4.6) → validation (5) → composable system (7.5) → generate text styles (7.6) → sync (8)
>
> **Text style note:**
> Text styles are **generated artifacts** — the source of truth is `tokens/typography/config.json` + `tokens/typography/scale.json`. `tokens/text-styles.generated.json` is the output, not the input.
> `tokens/text-styles.seed.json` — ⚠️ DEPRECATED. Not used in the current pipeline. See Phase 7.5.

---

## Phase 1 — Infrastructure: primitive token registry

**Goal:** Add a single place that lists every supported token type with its Figma variable type, unit, and allowed-value rules. Nothing syncs yet.

**Why first:** Every later phase reads this registry. Defining it up front prevents ad-hoc checks scattered across validators.

**Reuses:** No color pipeline code changed. New file only.

**Files:**
- Create: `primitive_types.py` — registry dict + type definitions
- Create: `tests/test_primitive_types.py`

### Task 1.1 — Define the primitive type registry

- [ ] **Step 1: Write the failing test**

```python
# tests/test_primitive_types.py
from primitive_types import PRIMITIVE_TYPES, PrimitiveTypeDef

def test_registry_contains_expected_types():
    expected = {
        "spacing", "radius", "stroke-width",
        "font-family", "font-weight", "font-size",
        "line-height", "letter-spacing", "opacity",
    }
    assert set(PRIMITIVE_TYPES.keys()) == expected

def test_each_type_has_required_fields():
    for name, td in PRIMITIVE_TYPES.items():
        assert isinstance(td, PrimitiveTypeDef), name
        assert td.figma_type in ("FLOAT", "STRING"), name
        assert isinstance(td.unit, (str, type(None))), name

def test_float_types_have_no_string_unit():
    float_types = {k for k, v in PRIMITIVE_TYPES.items() if v.figma_type == "FLOAT"}
    assert "font-family" not in float_types
    assert "font-weight" in float_types
```

- [ ] **Step 2: Run test to verify it fails**

```
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
.venv/bin/python -m pytest tests/test_primitive_types.py -v
```

Expected: `ModuleNotFoundError: No module named 'primitive_types'`

- [ ] **Step 3: Create `primitive_types.py`**

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PrimitiveTypeDef:
    figma_type: Literal["FLOAT", "STRING"]
    unit: str | None  # e.g. "px", "%" — informational only, not sent to Figma


PRIMITIVE_TYPES: dict[str, PrimitiveTypeDef] = {
    "spacing":        PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "radius":         PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "stroke-width":   PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "font-family":    PrimitiveTypeDef(figma_type="STRING", unit=None),
    "font-weight":    PrimitiveTypeDef(figma_type="FLOAT", unit=None),
    "font-size":      PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "line-height":    PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "letter-spacing": PrimitiveTypeDef(figma_type="FLOAT", unit="px"),
    "opacity":        PrimitiveTypeDef(figma_type="FLOAT", unit=None),
}
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_primitive_types.py -v
```

Expected: 3 PASSED

---

## Phase 2 — Infrastructure: generic seed validator

**Goal:** Write a reusable validator that checks any primitive seed file against the registry. Works for all non-color types.

**Reuses:** Same error-list pattern as `_validate_normalized()` in `plan_colors.py`. Pure function, no I/O.

**Files:**
- Create: `validate_primitives.py` — `validate_primitive_seed(type_key, entries)` function
- Create: `tests/test_validate_primitives.py`

### Task 2.1 — Implement `validate_primitive_seed`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validate_primitives.py
from validate_primitives import validate_primitive_seed


def test_valid_spacing_seed():
    entries = [
        {"name": "spacing/1", "value": 4.0},
        {"name": "spacing/2", "value": 8.0},
    ]
    errors = validate_primitive_seed("spacing", entries)
    assert errors == []


def test_wrong_type_key_rejected():
    errors = validate_primitive_seed("color", [])
    assert any("unknown type" in e.lower() for e in errors)


def test_float_type_rejects_string_value():
    entries = [{"name": "spacing/1", "value": "4px"}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("value" in e.lower() for e in errors)


def test_string_type_accepts_string_value():
    entries = [{"name": "font-family/sans", "value": "Inter"}]
    errors = validate_primitive_seed("font-family", entries)
    assert errors == []


def test_string_type_rejects_float_value():
    entries = [{"name": "font-family/sans", "value": 14.0}]
    errors = validate_primitive_seed("font-family", entries)
    assert any("value" in e.lower() for e in errors)


def test_name_must_start_with_type_key():
    entries = [{"name": "wrong/1", "value": 4.0}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("name" in e.lower() for e in errors)


def test_duplicate_names_rejected():
    entries = [
        {"name": "spacing/1", "value": 4.0},
        {"name": "spacing/1", "value": 8.0},
    ]
    errors = validate_primitive_seed("spacing", entries)
    assert any("duplicate" in e.lower() for e in errors)


def test_missing_name_field_rejected():
    entries = [{"value": 4.0}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("name" in e.lower() for e in errors)


def test_missing_value_field_rejected():
    entries = [{"name": "spacing/1"}]
    errors = validate_primitive_seed("spacing", entries)
    assert any("value" in e.lower() for e in errors)


def test_opacity_range_1_0_is_valid():
    entries = [{"name": "opacity/subtle", "value": 0.5}]
    errors = validate_primitive_seed("opacity", entries)
    assert errors == []


def test_opacity_above_1_rejected():
    entries = [{"name": "opacity/full", "value": 1.5}]
    errors = validate_primitive_seed("opacity", entries)
    assert any("opacity" in e.lower() or "range" in e.lower() for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_validate_primitives.py -v
```

Expected: `ModuleNotFoundError: No module named 'validate_primitives'`

- [ ] **Step 3: Create `validate_primitives.py`**

```python
from primitive_types import PRIMITIVE_TYPES


def validate_primitive_seed(type_key: str, entries: list[dict]) -> list[str]:
    errors: list[str] = []

    if type_key not in PRIMITIVE_TYPES:
        errors.append(f"Unknown type key '{type_key}'. Valid: {sorted(PRIMITIVE_TYPES)}")
        return errors

    td = PRIMITIVE_TYPES[type_key]
    seen_names: set[str] = set()

    for i, entry in enumerate(entries):
        label = f"Entry {i}"

        if "name" not in entry:
            errors.append(f"{label}: missing 'name' field")
            continue
        if "value" not in entry:
            errors.append(f"{label}: missing 'value' field")
            continue

        name: str = entry["name"]
        value = entry["value"]
        label = f"Entry '{name}'"

        if not name.startswith(f"{type_key}/"):
            errors.append(f"{label}: name must start with '{type_key}/', got '{name}'")

        if name in seen_names:
            errors.append(f"Duplicate name: '{name}'")
        seen_names.add(name)

        if td.figma_type == "FLOAT":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"{label}: value must be a number for type '{type_key}', got {type(value).__name__}")
            elif type_key == "opacity" and not (0.0 <= float(value) <= 1.0):
                errors.append(f"{label}: opacity value must be in range [0, 1], got {value}")

        if td.figma_type == "STRING":
            if not isinstance(value, str):
                errors.append(f"{label}: value must be a string for type '{type_key}', got {type(value).__name__}")

    return errors
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_validate_primitives.py -v
```

Expected: 11 PASSED

---

## Phase 3 — Primitive seed files + per-type CLI commands ✅ DONE

**Goal:** For each of the 9 token types, create a minimal seed file and a `plan validate-primitives <type>` CLI command. Sync is NOT added here.

**Split:** Types are grouped by Figma variable type:
- **Group A** (FLOAT / size): spacing, radius, stroke-width, font-size, line-height, letter-spacing
- **Group B** (FLOAT / scale): font-weight, opacity
- **Group C** (STRING): font-family

This grouping matters for seed file structure and later sync templates, but Phase 3 treats all types identically — one seed file + validator command each.

**Reuses:** `validate_primitive_seed()` from Phase 2.

**Files:**
- Create: `tokens/spacing.seed.json`
- Create: `tokens/radius.seed.json`
- Create: `tokens/stroke-width.seed.json`
- Create: `tokens/font-family.seed.json`
- Create: `tokens/font-weight.seed.json`
- Create: `tokens/font-size.seed.json`
- Create: `tokens/line-height.seed.json`
- Create: `tokens/letter-spacing.seed.json`
- Create: `tokens/opacity.seed.json`
- Modify: `plan_handlers.py` — add `plan validate-primitives <type>` command
- Create: `tests/test_plan_validate_primitives.py`

### Task 3.1 — Create seed files (one per type)

Start with spacing as the simplest. Each seed file has the same shape: an array of `{name, value}` objects.

- [ ] **Step 1: Create `tokens/spacing.seed.json`**

```json
[
  { "name": "spacing/1", "value": 4 },
  { "name": "spacing/2", "value": 8 },
  { "name": "spacing/3", "value": 12 },
  { "name": "spacing/4", "value": 16 },
  { "name": "spacing/5", "value": 20 },
  { "name": "spacing/6", "value": 24 },
  { "name": "spacing/8", "value": 32 },
  { "name": "spacing/10", "value": 40 },
  { "name": "spacing/12", "value": 48 },
  { "name": "spacing/16", "value": 64 }
]
```

- [ ] **Step 2: Create `tokens/radius.seed.json`**

```json
[
  { "name": "radius/none", "value": 0 },
  { "name": "radius/sm", "value": 4 },
  { "name": "radius/md", "value": 8 },
  { "name": "radius/lg", "value": 12 },
  { "name": "radius/xl", "value": 16 },
  { "name": "radius/full", "value": 9999 }
]
```

- [ ] **Step 3: Create `tokens/stroke-width.seed.json`**

```json
[
  { "name": "stroke-width/hairline", "value": 0.5 },
  { "name": "stroke-width/thin", "value": 1 },
  { "name": "stroke-width/base", "value": 1.5 },
  { "name": "stroke-width/thick", "value": 2 },
  { "name": "stroke-width/heavy", "value": 4 }
]
```

- [ ] **Step 4: Create `tokens/font-family.seed.json`**

```json
[
  { "name": "font-family/sans", "value": "Inter" },
  { "name": "font-family/mono", "value": "JetBrains Mono" }
]
```

- [ ] **Step 5: Create `tokens/font-weight.seed.json`**

```json
[
  { "name": "font-weight/regular", "value": 400 },
  { "name": "font-weight/medium", "value": 500 },
  { "name": "font-weight/semibold", "value": 600 },
  { "name": "font-weight/bold", "value": 700 }
]
```

- [ ] **Step 6: Create `tokens/font-size.seed.json`**

```json
[
  { "name": "font-size/xs", "value": 11 },
  { "name": "font-size/sm", "value": 13 },
  { "name": "font-size/base", "value": 15 },
  { "name": "font-size/md", "value": 17 },
  { "name": "font-size/lg", "value": 20 },
  { "name": "font-size/xl", "value": 24 },
  { "name": "font-size/2xl", "value": 32 },
  { "name": "font-size/3xl", "value": 40 }
]
```

- [ ] **Step 7: Create `tokens/line-height.seed.json`**

```json
[
  { "name": "line-height/tight", "value": 16 },
  { "name": "line-height/snug", "value": 20 },
  { "name": "line-height/base", "value": 24 },
  { "name": "line-height/relaxed", "value": 28 },
  { "name": "line-height/loose", "value": 32 }
]
```

- [ ] **Step 8: Create `tokens/letter-spacing.seed.json`**

```json
[
  { "name": "letter-spacing/tight", "value": -0.5 },
  { "name": "letter-spacing/normal", "value": 0 },
  { "name": "letter-spacing/wide", "value": 0.5 },
  { "name": "letter-spacing/wider", "value": 1 },
  { "name": "letter-spacing/widest", "value": 2 }
]
```

- [ ] **Step 9: Create `tokens/opacity.seed.json`**

```json
[
  { "name": "opacity/0", "value": 0 },
  { "name": "opacity/subtle", "value": 0.05 },
  { "name": "opacity/faint", "value": 0.1 },
  { "name": "opacity/light", "value": 0.3 },
  { "name": "opacity/mid", "value": 0.5 },
  { "name": "opacity/strong", "value": 0.7 },
  { "name": "opacity/full", "value": 1 }
]
```

---

### Task 3.2 — Add `plan validate-primitives` CLI command

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_validate_primitives.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_plan_validate_primitives.py -v
```

Expected: all FAILED (command does not exist yet)

- [ ] **Step 3: Add `validate-primitives` command to `plan_handlers.py`**

Open `plan_handlers.py`. Locate the `plan_app` Typer sub-application. Add after the last existing command:

```python
@plan_app.command("validate-primitives")
def plan_validate_primitives(
    type_key: str = typer.Argument(..., help="Token type: spacing, radius, font-size, etc."),
    seed_file: Optional[str] = typer.Option(None, "--seed-file", help="Path to seed JSON. Defaults to tokens/<type>.seed.json"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Validate a primitive token seed file."""
    from validate_primitives import validate_primitive_seed
    import json
    from pathlib import Path

    path = Path(seed_file) if seed_file else Path("tokens") / f"{type_key}.seed.json"
    if not path.exists():
        typer.echo(f"Seed file not found: {path}", err=True)
        raise typer.Exit(1)

    entries = json.loads(path.read_text())
    errors = validate_primitive_seed(type_key, entries)

    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}")
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"✓ {type_key} seed is valid ({len(entries)} entries)")
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_plan_validate_primitives.py -v
```

Expected: 4 PASSED

- [ ] **Step 5: Manually validate all 9 seed files**

```
.venv/bin/python run.py plan validate-primitives spacing
.venv/bin/python run.py plan validate-primitives radius
.venv/bin/python run.py plan validate-primitives stroke-width
.venv/bin/python run.py plan validate-primitives font-family
.venv/bin/python run.py plan validate-primitives font-weight
.venv/bin/python run.py plan validate-primitives font-size
.venv/bin/python run.py plan validate-primitives line-height
.venv/bin/python run.py plan validate-primitives letter-spacing
.venv/bin/python run.py plan validate-primitives opacity
```

Expected: 9 lines each showing `✓ <type> seed is valid`.

---

## Phase 4 — Semantic seed file structure 🟡 PARTIAL

**Goal:** Create a structured semantic seed file for non-color token types. User will then manually fill in the semantic → primitive mappings (roadmap item 4 is a manual step).

**Status:** Phase 4.1 ✅ DONE — seed file created. Phase 4.5 ✅ DONE — typography audit complete. Phase 4.6 ⬜ TODO — typography semantics not yet refined. Do not run Phase 5 validation until Phase 4.6 is complete and all nulls are resolved.

**Reuses:** Same flat JSON approach as `semantics.seed.json` for colors.

**Files:**
- ✅ Created: `tokens/primitives-semantic.seed.json` (draft, user-editable — nulls allowed)
- ✅ Created: `docs/tokens/semantic-seed-guide.md` — explains the format

### Task 4.1 — Create semantic seed file ✅ DONE

**Verified:** `tokens/primitives-semantic.seed.json` exists.

- [x] **Step 1: Create `tokens/primitives-semantic.seed.json`**

This file is intentionally sparse. The user fills in the values as roadmap item 4 (manual step). The keys show the expected naming convention; the `null` values are placeholders the user replaces before validation.

```json
{
  "_comment": "Semantic token seed — maps semantic names to primitive token names. Replace null with a primitive name before running plan validate-semantic-primitives.",
  "spacing/component/padding-sm": null,
  "spacing/component/padding-md": null,
  "spacing/component/gap": null,
  "spacing/layout/section": null,
  "radius/component/button": null,
  "radius/component/card": null,
  "radius/component/input": null,
  "font-size/body/sm": null,
  "font-size/body/md": null,
  "font-size/heading/sm": null,
  "font-size/heading/md": null,
  "font-size/heading/lg": null,
  "font-weight/body": null,
  "font-weight/heading": null,
  "font-weight/label": null,
  "font-family/body": null,
  "font-family/heading": null,
  "line-height/body": null,
  "line-height/heading": null,
  "letter-spacing/body": null,
  "letter-spacing/heading": null,
  "opacity/disabled": null,
  "opacity/overlay": null,
  "stroke-width/border": null,
  "stroke-width/focus-ring": null
}
```

- [x] **Step 2: Verify the file exists and is valid JSON**

```
.venv/bin/python -c "import json; json.load(open('tokens/primitives-semantic.seed.json')); print('valid JSON')"
```

Expected: `valid JSON`

- [ ] **Step 3: ⬅ MANUAL STEP — fill in `primitives-semantic.seed.json`** (blocked on Phase 4.6)

Open `tokens/primitives-semantic.seed.json` and replace each `null` with the name of a primitive token defined in the corresponding seed file. Example:

```json
"spacing/component/padding-sm": "spacing/2",
"radius/component/button": "radius/md",
"font-family/body": "font-family/sans"
```

Rules:
- Each value must be a string matching a `name` in one of the 9 seed files.
- Semantic name prefix must match primitive prefix (e.g., `spacing/…` → `spacing/…`).
- Remove entries you don't need; don't leave `null` in the file before syncing.

---

## Phase 4.5 — Typography audit ✅ DONE

**Goal:** Understand real typography usage in Figma before finalizing semantic tokens.

**Verified:** `tokens/typography-audit.json` exists — audit complete.

**Note:** Output saved to `tokens/typography-audit.json` (not `text-styles.suggested.json` as originally planned). This file is the authoritative audit input for Phase 4.6.

### Task 4.5.1 — Read Figma text styles ✅ DONE

- [x] **Step 1: Run typography audit against the Figma file**
- [x] **Step 2: Save output** — saved to `tokens/typography-audit.json`
- [x] **Step 3: Audit text node usage** — captured in audit output
- [x] **Step 4: Analyze typography combinations** — feeds into Phase 4.6

**Output:** `tokens/typography-audit.json`

---

## Phase 4.6 — Refine typography semantics

**Goal:** Update `tokens/primitives-semantic.seed.json` based on the typography audit. Replace guessed mappings with real ones. Resolve remaining nulls.

**Prerequisite:** Phase 4.5 completed and output reviewed.

**Constraints:**
- Do NOT modify primitive seeds (add missing primitives only if necessary).
- Do NOT sync.

### Task 4.6.1 — Resolve nulls and fix guessed mappings

- [ ] **Step 1: Open `tokens/primitives-semantic.seed.json`**

Review all existing mappings against the audit output. Correct any that were guessed.

- [ ] **Step 2: Resolve remaining nulls**

Current nulls to resolve (as of Phase 4 draft):

| Token | Resolution guidance |
|-------|-------------------|
| `letter-spacing/heading` | Check audit for heading letter-spacing value; add primitive if non-zero |
| `opacity/scrim` | Decide between `opacity/opacity-50` and `opacity/opacity-70` |

- [ ] **Step 3: Align typography semantic tokens with real usage**

Ensure:
- `font-size/body/*`, `font-size/heading/*`, `font-size/label/*` match actual Figma text styles
- `line-height/body/*`, `line-height/heading/*` reflect real line heights used
- `letter-spacing/heading` is set if headings use non-zero tracking

- [ ] **Step 4: Verify no nulls remain**

```
.venv/bin/python -c "
import json
data = json.load(open('tokens/primitives-semantic.seed.json'))
nulls = [k for k, v in data.items() if v is None and not k.startswith('_')]
print('nulls:', nulls if nulls else 'none — ready for Phase 5')
"
```

Expected: `nulls: none — ready for Phase 5`

**Result:** Semantic layer becomes production-ready. Proceed to Phase 5 validation.

---

## Phase 5 — Semantic token validator

**Prerequisite:** Phase 4.6 must be complete. No `null` values are allowed in `tokens/primitives-semantic.seed.json` at this stage.

**Goal:** Validate the semantic seed file — all values must reference an existing primitive name in the correct seed file.

**Reuses:** Same error-list pattern as `_validate_normalized()`.

**Files:**
- Create: `validate_semantic_primitives.py`
- Create: `tests/test_validate_semantic_primitives.py`
- Modify: `plan_handlers.py` — add `plan validate-semantic-primitives` command

### Task 5.1 — Implement `validate_semantic_primitives`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validate_semantic_primitives.py
from validate_semantic_primitives import validate_semantic_primitives


SPACING_SEED = [
    {"name": "spacing/1", "value": 4},
    {"name": "spacing/2", "value": 8},
]
RADIUS_SEED = [
    {"name": "radius/sm", "value": 4},
    {"name": "radius/md", "value": 8},
]

ALL_SEEDS = {
    "spacing": SPACING_SEED,
    "radius": RADIUS_SEED,
}


def test_valid_semantic_mapping():
    semantic = {
        "spacing/component/padding": "spacing/1",
        "radius/component/button": "radius/sm",
    }
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert errors == []


def test_unknown_primitive_reference():
    semantic = {"spacing/component/x": "spacing/99"}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("spacing/99" in e for e in errors)


def test_type_mismatch_in_semantic_name():
    # semantic name starts with "spacing" but references a radius primitive
    semantic = {"spacing/component/x": "radius/sm"}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("type" in e.lower() or "mismatch" in e.lower() for e in errors)


def test_semantic_name_with_unknown_prefix():
    semantic = {"unknown/x": "spacing/1"}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("unknown" in e.lower() or "prefix" in e.lower() for e in errors)


def test_null_values_rejected():
    semantic = {"spacing/component/x": None}
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert any("null" in e.lower() or "none" in e.lower() or "value" in e.lower() for e in errors)


def test_duplicate_semantic_keys_impossible():
    # JSON object keys are deduplicated by python json.loads — test that identical values do not produce false errors
    semantic = {
        "spacing/a": "spacing/1",
        "spacing/b": "spacing/1",
    }
    errors = validate_semantic_primitives(semantic, ALL_SEEDS)
    assert errors == []
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_validate_semantic_primitives.py -v
```

Expected: `ModuleNotFoundError: No module named 'validate_semantic_primitives'`

- [ ] **Step 3: Create `validate_semantic_primitives.py`**

```python
from primitive_types import PRIMITIVE_TYPES


def validate_semantic_primitives(
    semantic: dict[str, str | None],
    primitive_seeds: dict[str, list[dict]],
) -> list[str]:
    errors: list[str] = []

    # Build lookup: type_key → set of names
    primitives_by_type: dict[str, set[str]] = {
        tk: {e["name"] for e in entries}
        for tk, entries in primitive_seeds.items()
    }

    for semantic_name, primitive_ref in semantic.items():
        if semantic_name.startswith("_"):
            continue  # skip comment keys

        if primitive_ref is None:
            errors.append(f"'{semantic_name}': value is null — replace with a primitive name before validating")
            continue

        # Infer expected type from semantic name prefix
        semantic_prefix = semantic_name.split("/")[0]
        if semantic_prefix not in PRIMITIVE_TYPES:
            errors.append(f"'{semantic_name}': prefix '{semantic_prefix}' is not a known primitive type")
            continue

        # Infer type from primitive reference prefix
        ref_prefix = primitive_ref.split("/")[0]
        if ref_prefix != semantic_prefix:
            errors.append(
                f"'{semantic_name}': type mismatch — semantic prefix is '{semantic_prefix}' "
                f"but reference '{primitive_ref}' starts with '{ref_prefix}'"
            )
            continue

        if ref_prefix not in primitives_by_type:
            errors.append(f"'{semantic_name}': no seed loaded for type '{ref_prefix}'")
            continue

        if primitive_ref not in primitives_by_type[ref_prefix]:
            errors.append(f"'{semantic_name}': references '{primitive_ref}' which does not exist in the {ref_prefix} seed")

    return errors
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_validate_semantic_primitives.py -v
```

Expected: 6 PASSED

### Task 5.2 — Add `plan validate-semantic-primitives` CLI command

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_plan_validate_semantic_primitives_cmd.py -v
```

Expected: FAILED (command does not exist)

- [ ] **Step 3: Add `validate-semantic-primitives` command to `plan_handlers.py`**

```python
@plan_app.command("validate-semantic-primitives")
def plan_validate_semantic_primitives(
    semantic_file: Optional[str] = typer.Option(None, "--semantic-file"),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Validate the semantic primitive seed file against all loaded primitive seeds."""
    import json
    from pathlib import Path
    from validate_primitives import validate_primitive_seed
    from validate_semantic_primitives import validate_semantic_primitives

    tokens_path = Path(tokens_dir)
    sem_path = Path(semantic_file) if semantic_file else tokens_path / "primitives-semantic.seed.json"

    if not sem_path.exists():
        typer.echo(f"Semantic seed file not found: {sem_path}", err=True)
        raise typer.Exit(1)

    semantic = json.loads(sem_path.read_text())

    # Load all primitive seeds present in tokens_dir
    primitive_seeds: dict[str, list[dict]] = {}
    from primitive_types import PRIMITIVE_TYPES
    for type_key in PRIMITIVE_TYPES:
        seed_path = tokens_path / f"{type_key}.seed.json"
        if seed_path.exists():
            primitive_seeds[type_key] = json.loads(seed_path.read_text())

    errors = validate_semantic_primitives(semantic, primitive_seeds)
    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}")
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"✓ Semantic primitives valid ({len(semantic)} entries)")
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_plan_validate_semantic_primitives_cmd.py -v
```

Expected: 2 PASSED

---

## Phase 6 — Sync primitive tokens to Figma ✅ DONE

**Goal:** Add a `sync primitive-tokens <type>` command that syncs a validated primitive seed to a Figma variable collection.

**Verified:**
- `scripts/variables/sync_primitive_tokens.js` — exists ✅
- `sync_handlers.py` line 290: `@sync_app.command("primitive-tokens")` — exists ✅

**Files:**
- ✅ Created: `scripts/variables/sync_primitive_tokens.js`
- ✅ Modified: `sync_handlers.py` — `sync primitive-tokens` command live
- ✅ Created: `tests/test_sync_primitive_tokens.py`

### Task 6.1 — JS template for primitive token sync

- [ ] **Step 1: Create `scripts/variables/sync_primitive_tokens.js`**

```javascript
// Syncs primitive tokens (non-color) to a Figma variable collection.
// Host injects: __ENTRIES__ (JSON array), __DRY_RUN__ (true|false), __TYPE_KEY__ (string)

const entries = __ENTRIES__;
const dryRun = __DRY_RUN__;
const typeKey = "__TYPE_KEY__";

const FIGMA_TYPE_MAP = {
  "spacing":        "FLOAT",
  "radius":         "FLOAT",
  "stroke-width":   "FLOAT",
  "font-family":    "STRING",
  "font-weight":    "FLOAT",
  "font-size":      "FLOAT",
  "line-height":    "FLOAT",
  "letter-spacing": "FLOAT",
  "opacity":        "FLOAT",
};

const figmaType = FIGMA_TYPE_MAP[typeKey];
if (!figmaType) {
  return { ok: false, error: `Unknown token type: ${typeKey}` };
}

const collectionName = "primitives";
let collection = null;
let modeId = null;

if (!dryRun) {
  const existing = figma.variables.getLocalVariableCollections()
    .find(c => c.name === collectionName);
  if (existing) {
    collection = existing;
    modeId = existing.modes[0].modeId;
  } else {
    collection = figma.variables.createVariableCollection(collectionName);
    modeId = collection.modes[0].modeId;
  }
}

const log = [];
let created = 0, skipped = 0;

for (const entry of entries) {
  const { name, value } = entry;

  if (dryRun) {
    log.push({ action: "would-create", name, value });
    created++;
    continue;
  }

  const existingVars = figma.variables.getLocalVariables(figmaType);
  const existing = existingVars.find(v => v.name === name);
  if (existing) {
    log.push({ action: "skipped", name, reason: "already exists" });
    skipped++;
    continue;
  }

  const variable = figma.variables.createVariable(name, collection.id, figmaType);
  variable.setValueForMode(modeId, value);
  log.push({ action: "created", name, value });
  created++;
}

return {
  collection: collectionName,
  type_key: typeKey,
  dry_run: dryRun,
  created,
  skipped,
  total: entries.length,
  log,
};
```

### Task 6.2 — Add `sync primitive-tokens` command

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_primitive_tokens.py
import json
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def _make_ok_result(dry_run=True, created=2, skipped=0):
    return {
        "collection": "primitives",
        "type_key": "spacing",
        "dry_run": dry_run,
        "created": created,
        "skipped": skipped,
        "total": created + skipped,
        "log": [],
    }


def test_sync_primitive_tokens_dry_run(tmp_path):
    seed = [{"name": "spacing/1", "value": 4}, {"name": "spacing/2", "value": 8}]
    seed_file = tmp_path / "spacing.seed.json"
    seed_file.write_text(json.dumps(seed))

    with patch("sync_handlers._run_validation") as mock_val, \
         patch("sync_handlers._dispatch_sync") as mock_sync:
        mock_val.return_value = None
        ok = MagicMock()
        ok.model_dump.return_value = _make_ok_result(dry_run=True, created=2)
        mock_sync.return_value = (_make_ok_result(dry_run=True, created=2), ok)

        result = runner.invoke(app, [
            "sync", "primitive-tokens", "spacing",
            "--seed-file", str(seed_file),
            "--dry-run",
            "-f", "https://figma.com/file/FAKE",
        ])

    assert result.exit_code == 0, result.output
    assert "dry" in result.output.lower() or "2" in result.output


def test_sync_primitive_tokens_missing_seed(tmp_path):
    result = runner.invoke(app, [
        "sync", "primitive-tokens", "spacing",
        "--seed-file", str(tmp_path / "missing.json"),
        "--dry-run",
        "-f", "https://figma.com/file/FAKE",
    ])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_sync_primitive_tokens.py -v
```

Expected: FAILED (command does not exist)

- [ ] **Step 3: Add `sync primitive-tokens` command to `sync_handlers.py`**

Open `sync_handlers.py`. Locate the `sync_app` Typer sub-application. Add after the last existing sync command:

```python
@sync_app.command("primitive-tokens")
def sync_primitive_tokens(
    type_key: str = typer.Argument(..., help="Token type: spacing, radius, font-size, etc."),
    figma_file: str = typer.Option(..., "-f", "--file", help="Figma file URL"),
    seed_file: Optional[str] = typer.Option(None, "--seed-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Sync primitive token seed to Figma variables. Always runs validate-runtime-context first."""
    import json
    from pathlib import Path
    from validate_primitives import validate_primitive_seed

    path = Path(seed_file) if seed_file else Path("tokens") / f"{type_key}.seed.json"
    if not path.exists():
        typer.echo(f"Seed file not found: {path}", err=True)
        raise typer.Exit(1)

    entries = json.loads(path.read_text())
    errors = validate_primitive_seed(type_key, entries)
    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}", err=True)
        raise typer.Exit(1)

    _run_validation(figma_file, quiet=quiet)

    script_path = Path(__file__).parent / "scripts" / "variables" / "sync_primitive_tokens.js"
    script = script_path.read_text()
    user_js = (
        script
        .replace("__ENTRIES__", json.dumps(entries))
        .replace("__DRY_RUN__", "true" if dry_run else "false")
        .replace('"__TYPE_KEY__"', f'"{type_key}"')
    )

    result, ok_model = _dispatch_sync(user_js, figma_file, quiet=quiet)

    if json_output:
        typer.echo(json.dumps(result))
        return

    mode = "[DRY RUN] " if dry_run else ""
    typer.echo(f"{mode}sync primitive-tokens {type_key}")
    typer.echo(f"  created: {result.get('created', 0)}")
    typer.echo(f"  skipped: {result.get('skipped', 0)}")
    typer.echo(f"  total:   {result.get('total', 0)}")

    if verbose:
        for entry in result.get("log", []):
            typer.echo(f"  {entry['action']:12} {entry['name']}")
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_sync_primitive_tokens.py -v
```

Expected: 2 PASSED

---

## Phase 7 (optional) — Read/audit primitive variables from Figma

**Goal:** A read command that fetches existing non-color primitive variables from Figma for audit. No modifications; used only to compare what is in Figma vs. what is in seed files.

**Risk:** None — read-only. Optional phase; skip if not needed.

**Files:**
- Create: `scripts/variables/read_primitive_variables.js`
- Modify: `read_handlers.py` — add `read primitive-variables <type>` command

### Task 7.1 — JS template for reading primitive variables

- [ ] **Step 1: Create `scripts/variables/read_primitive_variables.js`**

```javascript
// Returns all FLOAT or STRING variables in the "primitives" collection matching __TYPE_KEY__.
const typeKey = "__TYPE_KEY__";

const FIGMA_TYPE_MAP = {
  "spacing": "FLOAT", "radius": "FLOAT", "stroke-width": "FLOAT",
  "font-family": "STRING", "font-weight": "FLOAT", "font-size": "FLOAT",
  "line-height": "FLOAT", "letter-spacing": "FLOAT", "opacity": "FLOAT",
};

const figmaType = FIGMA_TYPE_MAP[typeKey];
const collection = figma.variables.getLocalVariableCollections()
  .find(c => c.name === "primitives");

if (!collection) return { type_key: typeKey, variables: [], error: "No 'primitives' collection found" };

const modeId = collection.modes[0].modeId;
const variables = figma.variables.getLocalVariables(figmaType)
  .filter(v => v.name.startsWith(`${typeKey}/`))
  .map(v => ({ name: v.name, value: v.valuesByMode[modeId] }));

return { type_key: typeKey, collection: "primitives", variables };
```

### Task 7.2 — Add `read primitive-variables` command to `read_handlers.py`

- [ ] **Step 1: Add read command**

Open `read_handlers.py`. Add after the last existing read command:

```python
@read_app.command("primitive-variables")
def read_primitive_variables(
    type_key: str = typer.Argument(..., help="Token type to audit"),
    figma_file: str = typer.Option(..., "-f", "--file"),
    out: Optional[str] = typer.Option(None, "--out"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Read existing primitive variables from Figma for audit (read-only)."""
    from pathlib import Path
    script_path = Path(__file__).parent / "scripts" / "variables" / "read_primitive_variables.js"
    script = script_path.read_text().replace('"__TYPE_KEY__"', f'"{type_key}"')
    _dispatch_read(script, figma_file, out=out, quiet=quiet)
```

- [ ] **Step 2: Smoke-test with dry-run (no Figma needed)**

```
.venv/bin/python run.py read --help
```

Expected: `primitive-variables` appears in the command list.

---

## Phase 7.5 — Composable typography system ✅ DONE

**Goal:** Define a composable typography system where `config.json` + `scale.json` are the sources of truth, and `text-styles.generated.json` is the generated output.

**Architecture change from original plan:** Text styles are **generated artifacts**, not hand-authored seeds. The pipeline is:
```
config.json + scale.json → generate → text-styles.generated.json
```

**Verified:**
- `tokens/typography/config.json` — exists ✅
- `tokens/typography/scale.json` — exists ✅
- `tokens/typography/text-styles.generated.json` — exists ✅ (hand-created, not yet reproducible — generator is Phase 7.6)

**⚠️ Note:** `text-styles.generated.json` currently exists but was hand-authored, not produced by a generator. It must NOT be treated as Phase 7.6 complete. The file must be fully reproducible from `config.json` + `scale.json` before Phase 7.6 is done. Do not manually edit it — if changes are needed, update `config.json` or `scale.json` and re-run the generator once it exists.

**DEPRECATED:** `tokens/text-styles.seed.json` — ⚠️ not used in this pipeline. Kept as archive only; do not use as Phase 8 input. The deprecated version is preserved at `tokens/text-styles.seed.deprecated.json`.

### Task 7.5.1 — Composable typography system ✅ DONE

- [x] Created `tokens/typography/config.json` — defines roles, weights, shared properties
- [x] Created `tokens/typography/scale.json` — maps roles to primitive token references
- [ ] `tokens/typography/text-styles.generated.json` — file exists but is hand-created; becomes a true artifact only after Phase 7.6 generator is implemented

**Source of truth:** `config.json` + `scale.json`
**Generated artifact:** `text-styles.generated.json` — must be fully reproducible by Phase 7.6 generator (do not hand-edit)

---

## Phase 7.6 — Generate text styles ⬜ TODO

**Goal:** Add a CLI command (or script) that reads `tokens/typography/config.json` + `tokens/typography/scale.json`, resolves primitive token values from seed files, and writes `tokens/typography/text-styles.generated.json`.

**Prerequisite:** Phase 7.5 complete (architecture established).

**Constraints:**
- Do NOT modify config.json or scale.json manually to fix output — fix the generator instead.
- Do NOT sync.
- `text-styles.generated.json` must never be the source of truth.

**Files:**
- Create or modify: generator command (e.g., `plan generate-text-styles` or a standalone script)
- Output: `tokens/typography/text-styles.generated.json`

### Task 7.6.1 — Implement `generate-text-styles` command

- [ ] **Step 1: Write the failing test**

Test that the generator reads `config.json` + `scale.json`, resolves primitive refs, and produces correct composite entries.

- [ ] **Step 2: Implement the generator**

Inputs:
- `tokens/typography/config.json` — roles, weights, shared properties
- `tokens/typography/scale.json` — per-role font-size and line-height primitive refs
- Primitive seed files — to resolve token names to values

Output:
- `tokens/typography/text-styles.generated.json` — array of `{name, font_family, font_size, font_weight, line_height, letter_spacing}`

- [ ] **Step 3: Add CLI command**

```
.venv/bin/python run.py plan generate-text-styles
```

- [ ] **Step 4: Run generator and verify output**

```
.venv/bin/python run.py plan generate-text-styles
.venv/bin/python -c "import json; data=json.load(open('tokens/typography/text-styles.generated.json')); print(f'{len(data)} styles generated')"
```

**Output:** `tokens/typography/text-styles.generated.json` — ready as Phase 8 input.

---

## Phase 8 — Sync text styles to Figma ⬜ TODO

**Goal:** Add a `sync text-styles` command that creates Figma text styles from `tokens/typography/text-styles.generated.json`.

**Prerequisite:** Phase 7.6 complete — `tokens/typography/text-styles.generated.json` is current and has been reviewed. Do NOT use `tokens/text-styles.seed.json` (deprecated).

**Risk:** Writes to Figma. Use `--dry-run` during development.

**Files:**
- Create: `scripts/variables/sync_text_styles.js`
- Modify: `sync_handlers.py` — add `sync text-styles` command
- Create: `tests/test_sync_text_styles.py`

### Task 8.1 — JS template for text styles

- [ ] **Step 1: Create `scripts/variables/sync_text_styles.js`**

```javascript
// Creates Figma text styles from resolved typography semantic tokens.
// Host injects __STYLES__ (array of {name, font_family, font_size, font_weight, line_height, letter_spacing})
// and __DRY_RUN__.

const styles = __STYLES__;
const dryRun = __DRY_RUN__;

const log = [];
let created = 0, skipped = 0;

const existingStyles = figma.getLocalTextStyles();
const existingByName = Object.fromEntries(existingStyles.map(s => [s.name, s]));

for (const style of styles) {
  if (existingByName[style.name]) {
    log.push({ action: "skipped", name: style.name, reason: "already exists" });
    skipped++;
    continue;
  }

  if (dryRun) {
    log.push({ action: "would-create", name: style.name });
    created++;
    continue;
  }

  const textStyle = figma.createTextStyle();
  textStyle.name = style.name;
  textStyle.fontSize = style.font_size;
  textStyle.fontName = { family: style.font_family, style: "Regular" };
  textStyle.lineHeight = { value: style.line_height, unit: "PIXELS" };
  textStyle.letterSpacing = { value: style.letter_spacing, unit: "PIXELS" };
  log.push({ action: "created", name: style.name });
  created++;
}

return { dry_run: dryRun, created, skipped, total: styles.length, log };
```

### Task 8.2 — Host-side text style sync CLI

**Input:** `tokens/typography/text-styles.generated.json` (produced by Phase 7.6 generator)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_text_styles.py
import json
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def test_sync_text_styles_dry_run(tmp_path):
    typography_dir = tmp_path / "tokens" / "typography"
    typography_dir.mkdir(parents=True)

    styles = [
        {"name": "body/sm", "font_family": "Urbanist", "font_size": 14, "font_weight": 400, "line_height": 20, "letter_spacing": 0},
    ]
    (typography_dir / "text-styles.generated.json").write_text(json.dumps(styles))

    with patch("sync_handlers._run_validation"), \
         patch("sync_handlers._dispatch_sync") as mock_sync:
        ok = MagicMock()
        mock_sync.return_value = ({"dry_run": True, "created": 1, "skipped": 0, "total": 1, "log": []}, ok)

        import os
        os.chdir(tmp_path)

        result = runner.invoke(app, [
            "sync", "text-styles",
            "--dry-run",
            "-f", "https://figma.com/file/FAKE",
        ])

    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_sync_text_styles.py -v
```

Expected: FAILED

- [ ] **Step 3: Add `sync text-styles` to `sync_handlers.py`**

Reads from `tokens/typography/text-styles.generated.json`. Does NOT resolve from semantic tokens — the generator (Phase 7.6) already did that.

```python
@sync_app.command("text-styles")
def sync_text_styles(
    figma_file: str = typer.Option(..., "-f", "--file"),
    generated_file: str = typer.Option("tokens/typography/text-styles.generated.json", "--generated-file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Sync text styles to Figma from the generated text-styles file."""
    import json
    from pathlib import Path

    path = Path(generated_file)
    if not path.exists():
        typer.echo(f"Generated file not found: {path}. Run 'plan generate-text-styles' first.", err=True)
        raise typer.Exit(1)

    styles = json.loads(path.read_text())
    if not styles:
        typer.echo("No text styles in generated file.", err=True)
        raise typer.Exit(1)

    _run_validation(figma_file, quiet=quiet)

    script_path = Path(__file__).parent / "scripts" / "variables" / "sync_text_styles.js"
    script = script_path.read_text()
    user_js = (
        script
        .replace("__STYLES__", json.dumps(styles))
        .replace("__DRY_RUN__", "true" if dry_run else "false")
    )

    result, ok_model = _dispatch_sync(user_js, figma_file, quiet=quiet)

    if json_output:
        typer.echo(json.dumps(result))
        return

    mode = "[DRY RUN] " if dry_run else ""
    typer.echo(f"{mode}sync text-styles")
    typer.echo(f"  created: {result.get('created', 0)}")
    typer.echo(f"  skipped: {result.get('skipped', 0)}")
    typer.echo(f"  total:   {result.get('total', 0)}")
    if verbose:
        for entry in result.get("log", []):
            typer.echo(f"  {entry['action']:12} {entry['name']}")
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_sync_text_styles.py -v
```

Expected: PASSED

---

## Phase 9 — Component token seed files + validator

**Goal:** Introduce component-level tokens. Component tokens reference semantic tokens (not primitives directly). Source of truth is a component seed file per component (or one unified file). Validation ensures all references resolve through semantic → primitive chain.

**Reuses:** Same seed pattern; validator builds on `validate_semantic_primitives.py`.

**Files:**
- Create: `tokens/components.seed.json` — component token definitions
- Create: `validate_component_tokens.py`
- Create: `tests/test_validate_component_tokens.py`
- Modify: `plan_handlers.py` — add `plan validate-component-tokens` command

### Task 9.1 — Create component seed file

- [ ] **Step 1: Create `tokens/components.seed.json`**

This file maps component-scoped token names to semantic token names. User edits this file.

```json
{
  "_comment": "Component token seed — maps component tokens to semantic tokens. Replace null with a semantic name before validating.",
  "button/padding-x": "spacing/component/padding-md",
  "button/padding-y": "spacing/component/padding-sm",
  "button/radius": "radius/component/button",
  "button/border-width": "stroke-width/border",
  "button/font-size": "font-size/body/md",
  "button/font-weight": "font-weight/label",
  "input/padding-x": "spacing/component/padding-md",
  "input/padding-y": "spacing/component/padding-sm",
  "input/radius": "radius/component/input",
  "input/border-width": "stroke-width/border",
  "card/radius": "radius/component/card",
  "card/padding": "spacing/component/padding-md"
}
```

### Task 9.2 — Implement `validate_component_tokens`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validate_component_tokens.py
from validate_component_tokens import validate_component_tokens


SEMANTIC = {
    "spacing/component/padding-md": "spacing/2",
    "radius/component/button": "radius/sm",
}
PRIMITIVE_SEEDS = {
    "spacing": [{"name": "spacing/2", "value": 8}],
    "radius": [{"name": "radius/sm", "value": 4}],
}


def test_valid_component_tokens():
    components = {
        "button/padding-x": "spacing/component/padding-md",
        "button/radius": "radius/component/button",
    }
    errors = validate_component_tokens(components, SEMANTIC, PRIMITIVE_SEEDS)
    assert errors == []


def test_reference_to_unknown_semantic_key():
    components = {"button/padding-x": "spacing/component/missing"}
    errors = validate_component_tokens(components, SEMANTIC, PRIMITIVE_SEEDS)
    assert any("spacing/component/missing" in e for e in errors)


def test_null_value_rejected():
    components = {"button/x": None}
    errors = validate_component_tokens(components, SEMANTIC, PRIMITIVE_SEEDS)
    assert any("null" in e.lower() or "none" in e.lower() or "value" in e.lower() for e in errors)


def test_non_string_value_rejected():
    components = {"button/x": 42}
    errors = validate_component_tokens(components, SEMANTIC, PRIMITIVE_SEEDS)
    assert any("string" in e.lower() for e in errors)
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_validate_component_tokens.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `validate_component_tokens.py`**

```python
def validate_component_tokens(
    components: dict[str, str | None],
    semantic: dict[str, str | None],
    primitive_seeds: dict[str, list[dict]],
) -> list[str]:
    errors: list[str] = []

    primitives_by_type: dict[str, set[str]] = {
        tk: {e["name"] for e in entries}
        for tk, entries in primitive_seeds.items()
    }

    for comp_name, sem_ref in components.items():
        if comp_name.startswith("_"):
            continue

        if sem_ref is None:
            errors.append(f"'{comp_name}': value is null")
            continue

        if not isinstance(sem_ref, str):
            errors.append(f"'{comp_name}': value must be a string, got {type(sem_ref).__name__}")
            continue

        if sem_ref not in semantic:
            errors.append(f"'{comp_name}': references semantic token '{sem_ref}' which does not exist in the semantic seed")
            continue

        prim_ref = semantic[sem_ref]
        if prim_ref is None:
            errors.append(f"'{comp_name}': semantic token '{sem_ref}' has a null primitive reference — fill in the semantic seed first")
            continue

        prim_prefix = prim_ref.split("/")[0]
        if prim_prefix not in primitives_by_type:
            errors.append(f"'{comp_name}': no primitive seed loaded for type '{prim_prefix}'")
            continue

        if prim_ref not in primitives_by_type[prim_prefix]:
            errors.append(f"'{comp_name}': primitive '{prim_ref}' (via semantic '{sem_ref}') does not exist in the {prim_prefix} seed")

    return errors
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_validate_component_tokens.py -v
```

Expected: 4 PASSED

### Task 9.3 — Add `plan validate-component-tokens` CLI command

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_validate_component_tokens_cmd.py
import json
import os
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def test_validate_component_tokens_passes(tmp_path):
    td = tmp_path / "tokens"
    td.mkdir()

    (td / "spacing.seed.json").write_text(json.dumps([{"name": "spacing/2", "value": 8}]))
    (td / "primitives-semantic.seed.json").write_text(
        json.dumps({"spacing/component/padding": "spacing/2"})
    )
    (td / "components.seed.json").write_text(
        json.dumps({"button/padding": "spacing/component/padding"})
    )

    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "validate-component-tokens"])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output.lower()


def test_validate_component_tokens_fails_on_missing_semantic(tmp_path):
    td = tmp_path / "tokens"
    td.mkdir()

    (td / "spacing.seed.json").write_text(json.dumps([{"name": "spacing/2", "value": 8}]))
    (td / "primitives-semantic.seed.json").write_text(json.dumps({}))
    (td / "components.seed.json").write_text(
        json.dumps({"button/padding": "spacing/component/missing"})
    )

    os.chdir(tmp_path)
    result = runner.invoke(app, ["plan", "validate-component-tokens"])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_plan_validate_component_tokens_cmd.py -v
```

Expected: FAILED

- [ ] **Step 3: Add `validate-component-tokens` command to `plan_handlers.py`**

```python
@plan_app.command("validate-component-tokens")
def plan_validate_component_tokens(
    component_file: Optional[str] = typer.Option(None, "--component-file"),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Validate component token seed against semantic and primitive seeds."""
    import json
    from pathlib import Path
    from primitive_types import PRIMITIVE_TYPES
    from validate_component_tokens import validate_component_tokens

    td = Path(tokens_dir)
    comp_path = Path(component_file) if component_file else td / "components.seed.json"
    sem_path = td / "primitives-semantic.seed.json"

    if not comp_path.exists():
        typer.echo(f"Component seed not found: {comp_path}", err=True)
        raise typer.Exit(1)
    if not sem_path.exists():
        typer.echo(f"Semantic seed not found: {sem_path}", err=True)
        raise typer.Exit(1)

    components = json.loads(comp_path.read_text())
    semantic   = json.loads(sem_path.read_text())

    primitive_seeds: dict[str, list[dict]] = {}
    for type_key in PRIMITIVE_TYPES:
        p = td / f"{type_key}.seed.json"
        if p.exists():
            primitive_seeds[type_key] = json.loads(p.read_text())

    errors = validate_component_tokens(components, semantic, primitive_seeds)
    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}")
        raise typer.Exit(1)

    if not quiet:
        typer.echo(f"✓ Component tokens valid ({len(components)} entries)")
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_plan_validate_component_tokens_cmd.py -v
```

Expected: 2 PASSED

---

## Phase 10 — Sync component variables to Figma

**Goal:** Add `sync component-tokens` command that syncs validated component tokens as alias variables pointing to semantic variables in Figma.

**Risk:** Writes to Figma. Use `--dry-run`. Requires semantic variables to already exist in Figma (Phase 6 output).

**Files:**
- Create: `scripts/variables/sync_component_tokens.js`
- Modify: `sync_handlers.py` — add `sync component-tokens` command
- Create: `tests/test_sync_component_tokens.py`

### Task 10.1 — JS template for component token sync

- [ ] **Step 1: Create `scripts/variables/sync_component_tokens.js`**

```javascript
// Syncs component tokens as alias variables pointing to semantic variables.
// Host injects __ENTRIES__ (array of {comp_name, sem_name, prim_type}) and __DRY_RUN__.

const entries = __ENTRIES__;
const dryRun = __DRY_RUN__;

const FIGMA_TYPE_MAP = {
  "spacing": "FLOAT", "radius": "FLOAT", "stroke-width": "FLOAT",
  "font-family": "STRING", "font-weight": "FLOAT", "font-size": "FLOAT",
  "line-height": "FLOAT", "letter-spacing": "FLOAT", "opacity": "FLOAT",
};

const log = [];
let created = 0, skipped = 0;

let compCollection = null;
let modeId = null;

if (!dryRun) {
  compCollection = figma.variables.getLocalVariableCollections()
    .find(c => c.name === "components");
  if (!compCollection) {
    compCollection = figma.variables.createVariableCollection("components");
  }
  modeId = compCollection.modes[0].modeId;
}

for (const entry of entries) {
  const { comp_name, sem_name, prim_type } = entry;
  const figmaType = FIGMA_TYPE_MAP[prim_type] || "FLOAT";

  if (dryRun) {
    log.push({ action: "would-create", name: comp_name, alias_to: sem_name });
    created++;
    continue;
  }

  const existingVars = figma.variables.getLocalVariables(figmaType);
  const existing = existingVars.find(v => v.name === comp_name);
  if (existing) {
    log.push({ action: "skipped", name: comp_name, reason: "already exists" });
    skipped++;
    continue;
  }

  // Find the semantic variable to alias to
  const semanticVar = figma.variables.getLocalVariables(figmaType)
    .find(v => v.name === sem_name);
  if (!semanticVar) {
    log.push({ action: "error", name: comp_name, reason: `semantic variable '${sem_name}' not found in Figma` });
    continue;
  }

  const variable = figma.variables.createVariable(comp_name, compCollection.id, figmaType);
  variable.setValueForMode(modeId, figma.variables.createVariableAlias(semanticVar));
  log.push({ action: "created", name: comp_name, alias_to: sem_name });
  created++;
}

return {
  collection: "components",
  dry_run: dryRun,
  created,
  skipped,
  total: entries.length,
  log,
};
```

### Task 10.2 — Add `sync component-tokens` command

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_component_tokens.py
import json
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def test_sync_component_tokens_dry_run(tmp_path):
    td = tmp_path / "tokens"
    td.mkdir()

    (td / "spacing.seed.json").write_text(json.dumps([{"name": "spacing/2", "value": 8}]))
    (td / "primitives-semantic.seed.json").write_text(
        json.dumps({"spacing/component/padding": "spacing/2"})
    )
    (td / "components.seed.json").write_text(
        json.dumps({"button/padding": "spacing/component/padding"})
    )

    with patch("sync_handlers._run_validation"), \
         patch("sync_handlers._dispatch_sync") as mock_sync:
        ok = MagicMock()
        mock_sync.return_value = (
            {"dry_run": True, "created": 1, "skipped": 0, "total": 1, "log": []},
            ok,
        )

        import os
        os.chdir(tmp_path)

        result = runner.invoke(app, [
            "sync", "component-tokens",
            "--dry-run",
            "-f", "https://figma.com/file/FAKE",
        ])

    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/bin/python -m pytest tests/test_sync_component_tokens.py -v
```

Expected: FAILED

- [ ] **Step 3: Add `sync component-tokens` command to `sync_handlers.py`**

```python
@sync_app.command("component-tokens")
def sync_component_tokens(
    figma_file: str = typer.Option(..., "-f", "--file"),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """Sync component tokens to Figma as alias variables pointing to semantic variables."""
    import json
    from pathlib import Path
    from primitive_types import PRIMITIVE_TYPES
    from validate_component_tokens import validate_component_tokens

    td = Path(tokens_dir)
    comp_path = td / "components.seed.json"
    sem_path  = td / "primitives-semantic.seed.json"

    if not comp_path.exists():
        typer.echo(f"Component seed not found: {comp_path}", err=True)
        raise typer.Exit(1)
    if not sem_path.exists():
        typer.echo(f"Semantic seed not found: {sem_path}", err=True)
        raise typer.Exit(1)

    components = json.loads(comp_path.read_text())
    semantic   = json.loads(sem_path.read_text())

    primitive_seeds: dict[str, list[dict]] = {}
    for type_key in PRIMITIVE_TYPES:
        p = td / f"{type_key}.seed.json"
        if p.exists():
            primitive_seeds[type_key] = json.loads(p.read_text())

    errors = validate_component_tokens(components, semantic, primitive_seeds)
    if errors:
        for e in errors:
            typer.echo(f"  ERROR: {e}", err=True)
        raise typer.Exit(1)

    # Build entries for JS: each entry resolves the primitive type
    entries = []
    for comp_name, sem_ref in components.items():
        if comp_name.startswith("_") or sem_ref is None:
            continue
        prim_ref = semantic.get(sem_ref, "")
        prim_type = prim_ref.split("/")[0] if prim_ref else "spacing"
        entries.append({"comp_name": comp_name, "sem_name": sem_ref, "prim_type": prim_type})

    _run_validation(figma_file, quiet=quiet)

    script_path = Path(__file__).parent / "scripts" / "variables" / "sync_component_tokens.js"
    script = script_path.read_text()
    user_js = (
        script
        .replace("__ENTRIES__", json.dumps(entries))
        .replace("__DRY_RUN__", "true" if dry_run else "false")
    )

    result, ok_model = _dispatch_sync(user_js, figma_file, quiet=quiet)

    if json_output:
        typer.echo(json.dumps(result))
        return

    mode = "[DRY RUN] " if dry_run else ""
    typer.echo(f"{mode}sync component-tokens")
    typer.echo(f"  created: {result.get('created', 0)}")
    typer.echo(f"  skipped: {result.get('skipped', 0)}")
    typer.echo(f"  total:   {result.get('total', 0)}")
    if verbose:
        for entry in result.get("log", []):
            typer.echo(f"  {entry['action']:12} {entry.get('name', '')}")
```

- [ ] **Step 4: Run test to verify it passes**

```
.venv/bin/python -m pytest tests/test_sync_component_tokens.py -v
```

Expected: PASSED

---

## Full test run

After all phases are complete:

- [ ] **Run the full test suite**

```
.venv/bin/python -m pytest tests/ -v
```

Expected: all existing tests PASS, all new tests PASS, zero regressions.

---

## Risks per phase

| Phase | Risk | Mitigation |
|---|---|---|
| 1 | None — new file, no existing code touched | — |
| 2 | None — pure function, no I/O | — |
| 3 | Seed files may need adjustment to match project's actual design scale | Author seed files as stubs; user edits before sync |
| 3 | Adding CLI command to `plan_handlers.py` could conflict with existing imports | Follow existing import pattern; add after last command |
| 4 | Semantic seed entries with `null` values could slip through to sync | Phase 5 validator explicitly rejects `null`; Phase 6 validates before sync |
| 4.5 | Figma file may have no named text styles — only inline typography on nodes | Fall back to reading text node usage; document gap in audit output |
| 4.6 | Guessed semantic mappings may not match real design intent | Always derive from Phase 4.5 audit; don't guess from primitive names |
| 5 | Semantic name prefix convention may differ from primitive prefix | Validator enforces prefix match; error message is explicit |
| 6 | Figma sync may fail if Scripter is not open or collection already has conflicting vars | Always use `--dry-run` first; idempotent design skips existing names |
| 7 | Read command may return empty if "primitives" collection does not exist yet | Returns empty array, not error; safe for audit |
| 7.5 | config.json/scale.json may reference primitive token names that don't exist in seed files | Generator (Phase 7.6) resolves references and fails fast on missing primitives |
| 7.6 | Generator output drifts from Figma if config/scale change without regenerating | Re-run `plan generate-text-styles` whenever config or scale changes; never hand-edit generated file |
| 8 | `sync text-styles` reads from `text-styles.generated.json` — file must be current | Phase 7.6 generates the file; Phase 8 fails fast if it is missing or stale |
| 9 | Component seed references may drift if semantic seed is updated | Re-run `plan validate-component-tokens` whenever semantic seed changes |
| 10 | Figma alias creation requires semantic variable to already exist in Figma | Sync script logs an error per entry and continues; dry-run catches missing vars |

---

## Recommended starting point

**Start with Phase 1 (Task 1.1)** — create `primitive_types.py`. It is:
- Zero risk (no existing code touched)
- Small (one file, one data structure)
- A prerequisite for every other phase
- Testable in isolation in under 5 minutes
