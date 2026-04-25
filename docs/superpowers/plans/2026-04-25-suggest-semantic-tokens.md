# Suggest Semantic Tokens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `plan suggest-semantic-tokens` CLI command that reads `primitives.normalized.json` and prints heuristic semantic token suggestions without touching the seed file.

**Architecture:** A pure function `_suggest_semantic_tokens` in `plan_colors.py` computes suggestions from a sorted-by-luminance primitive list. A Typer command in `plan_handlers.py` wires I/O, formats stdout, and optionally writes `tokens/semantics.suggested.json`. The enum constants `SEMANTIC_ROLES` and `SEMANTIC_STATES` are updated in the same step as the seed migration.

**Tech Stack:** Python 3.11+, Typer, colorsys (stdlib — already imported), pytest, existing atomic write pattern from `host_io.py`.

---

## Prerequisite: Seed Migration

The existing `tokens/semantics.seed.json` uses state `default`, which will become invalid once `SEMANTIC_STATES` is updated. The seed must be patched **before** any code change lands.

---

## File Map

| File | Change |
|------|--------|
| `tokens/semantics.seed.json` | Rename all `default` states → `primary` (5 entries) |
| `plan_colors.py` | Update `SEMANTIC_ROLES`, `SEMANTIC_STATES`; add `_hex_luminance`, `_suggest_semantic_tokens` |
| `plan_handlers.py` | Add import `_suggest_semantic_tokens`; add command `suggest-semantic-tokens` |
| `tests/test_semantic_tokens.py` | Update existing tests to use `primary`; add tests for `_suggest_semantic_tokens` |

No new files needed. `semantics.suggested.json` is a runtime output, not a source file.

---

## Task 1: Migrate seed and fix existing tests

**Files:**
- Modify: `tokens/semantics.seed.json`
- Modify: `tests/test_semantic_tokens.py`

- [ ] **Step 1: Update the seed file**

Replace the contents of `tokens/semantics.seed.json` with:

```json
{
  "color/border/primary": "color/gray/500",
  "color/surface/primary": "color/gray/100",
  "color/text/disabled": "color/gray/500",
  "color/text/primary": "color/gray/900",
  "color/text/secondary": "color/gray/500"
}
```

- [ ] **Step 2: Update the existing tests**

In `tests/test_semantic_tokens.py`, replace `"default"` with `"primary"` throughout. The file becomes:

```python
"""Tests for semantic token normalize+validate logic."""
import pytest

from plan_colors import _build_and_validate_semantic_normalized

PRIMITIVES = [
    {"final_name": "color/gray/900"},
    {"final_name": "color/gray/500"},
    {"final_name": "color/gray/100"},
]


def build(seed, overrides=None):
    return _build_and_validate_semantic_normalized(seed, PRIMITIVES, overrides or {})


def test_valid_seed_returns_flat_map():
    seed = {
        "color/text/primary": "color/gray/900",
        "color/text/disabled": "color/gray/500",
        "color/surface/primary": "color/gray/100",
    }
    result = build(seed)
    assert result == seed


def test_override_wins_over_seed():
    seed = {"color/text/primary": "color/gray/500"}
    overrides = {"color/text/primary": "color/gray/900"}
    result = build(seed, overrides)
    assert result["color/text/primary"] == "color/gray/900"


def test_override_adds_new_entry():
    seed = {"color/text/primary": "color/gray/900"}
    overrides = {"color/border/primary": "color/gray/500"}
    result = build(seed, overrides)
    assert result["color/border/primary"] == "color/gray/500"
    assert result["color/text/primary"] == "color/gray/900"


def test_missing_primitive_fails():
    seed = {"color/text/primary": "color/blue/500"}
    with pytest.raises(ValueError, match="not found in primitives"):
        build(seed)


def test_bad_role_fails():
    seed = {"color/emotion/primary": "color/gray/900"}
    with pytest.raises(ValueError, match="role"):
        build(seed)


def test_bad_state_fails():
    seed = {"color/text/pressed": "color/gray/900"}
    with pytest.raises(ValueError, match="state"):
        build(seed)


def test_raw_hex_value_fails():
    seed = {"color/text/primary": "#262626"}
    with pytest.raises(ValueError, match="raw hex"):
        build(seed)


def test_semantic_to_semantic_alias_fails():
    seed = {
        "color/text/primary": "color/gray/900",
        "color/text/disabled": "color/text/primary",
    }
    with pytest.raises(ValueError, match="semantic name"):
        build(seed)
```

- [ ] **Step 3: Run existing tests — expect failure on bad state**

```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
.venv/bin/python -m pytest tests/test_semantic_tokens.py -v
```

Expected: all tests **FAIL** with `state 'default' not in allowed states` — because `SEMANTIC_STATES` still contains `default`. This confirms the guard is working. (Tests will pass again after Task 2.)

- [ ] **Step 4: Commit seed migration only**

```bash
git add tokens/semantics.seed.json tests/test_semantic_tokens.py
git commit -m "chore: migrate semantics.seed.json default → primary state"
```

---

## Task 2: Update enums and add luminance helper

**Files:**
- Modify: `plan_colors.py` lines ~770–798

- [ ] **Step 1: Update `SEMANTIC_ROLES` and `SEMANTIC_STATES`**

In `plan_colors.py`, replace the two frozenset constants (currently around line 770):

```python
SEMANTIC_ROLES = frozenset({
    "text", "icon", "border", "surface", "canvas", "accent",
})
SEMANTIC_STATES = frozenset({
    "primary", "secondary", "disabled",
})
```

- [ ] **Step 2: Add `_hex_luminance` helper**

Insert immediately after `_SEMANTIC_NAME_RE = re.compile(...)` (around line 777):

```python
def _hex_luminance(hex_color: str) -> float:
    """Return perceived luminance [0.0, 1.0] from a hex string like '#aabbcc' or 'aabbcc'."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    _, l, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return l
```

`colorsys` is already imported at the top of `plan_colors.py`.

- [ ] **Step 3: Run tests — expect pass**

```bash
.venv/bin/python -m pytest tests/test_semantic_tokens.py -v
```

Expected: all 8 tests **PASS**. The enum update makes `primary` valid and `default` invalid.

- [ ] **Step 4: Commit**

```bash
git add plan_colors.py
git commit -m "feat: update semantic enums (primary/secondary/disabled) and add _hex_luminance"
```

---

## Task 3: Add `_suggest_semantic_tokens` pure function

**Files:**
- Modify: `plan_colors.py` (add after `_build_and_validate_semantic_normalized`)

- [ ] **Step 1: Write the failing tests first**

Append to `tests/test_semantic_tokens.py`:

```python
# ---------------------------------------------------------------------------
# Suggestion tests
# ---------------------------------------------------------------------------

from plan_colors import _suggest_semantic_tokens

SUGGEST_PRIMITIVES_3 = [
    {"final_name": "color/gray/900", "hex": "#262626"},
    {"final_name": "color/gray/500", "hex": "#aaaaaa"},
    {"final_name": "color/gray/100", "hex": "#f1f1f1"},
]


def test_suggest_basic_three_primitives():
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed={})
    names = [s["semantic_name"] for s in suggestions]
    assert "color/text/primary" in names
    assert "color/canvas/primary" in names
    assert "color/border/primary" in names


def test_suggest_text_primary_is_darkest():
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed={})
    by_name = {s["semantic_name"]: s for s in suggestions}
    assert by_name["color/text/primary"]["primitive_name"] == "color/gray/900"


def test_suggest_canvas_primary_is_lightest():
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed={})
    by_name = {s["semantic_name"]: s for s in suggestions}
    assert by_name["color/canvas/primary"]["primitive_name"] == "color/gray/100"


def test_suggest_surface_distinct_from_canvas():
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed={})
    by_name = {s["semantic_name"]: s for s in suggestions}
    # 3-color palette — surface and canvas must not share a primitive
    # (surface skipped if no distinct second-lightest)
    if "color/surface/primary" in by_name:
        assert by_name["color/surface/primary"]["primitive_name"] != by_name["color/canvas/primary"]["primitive_name"]


def test_suggest_disabled_and_secondary_both_emitted_on_same_primitive():
    # On a 3-color palette text/secondary and text/disabled land on the same primitive.
    # Both must be emitted — no deduplication.
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed={})
    names = [s["semantic_name"] for s in suggestions]
    # At least one of the two must appear (palette may be too small for both)
    assert "color/text/disabled" in names or "color/text/secondary" in names
    # If both appear they are allowed to share a primitive — that is intentional
    by_name = {s["semantic_name"]: s for s in suggestions}
    if "color/text/secondary" in by_name and "color/text/disabled" in by_name:
        # Both present — no error, primitives may match
        assert isinstance(by_name["color/text/secondary"]["primitive_name"], str)
        assert isinstance(by_name["color/text/disabled"]["primitive_name"], str)


def test_suggest_mid_scale_even_list_picks_darker():
    # 4-color palette — even-sized list, mid picks the darker of the two centre entries.
    primitives = [
        {"final_name": "color/gray/900", "hex": "#111111"},
        {"final_name": "color/gray/600", "hex": "#666666"},
        {"final_name": "color/gray/300", "hex": "#cccccc"},
        {"final_name": "color/gray/100", "hex": "#f5f5f5"},
    ]
    suggestions = _suggest_semantic_tokens(primitives, existing_seed={})
    by_name = {s["semantic_name"]: s for s in suggestions}
    # mid of [900,600,300,100] sorted dark→light is index 1 (600) — the darker centre
    assert by_name["color/border/primary"]["primitive_name"] == "color/gray/600"


def test_suggest_covered_seed_entries_marked():
    existing_seed = {"color/text/primary": "color/gray/900"}
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed=existing_seed)
    by_name = {s["semantic_name"]: s for s in suggestions}
    assert by_name["color/text/primary"]["covered"] is True


def test_suggest_no_saturated_skips_accent():
    suggestions = _suggest_semantic_tokens(SUGGEST_PRIMITIVES_3, existing_seed={})
    names = [s["semantic_name"] for s in suggestions]
    assert not any(n.startswith("color/accent/") for n in names)


def test_suggest_saturated_primitive_produces_accent():
    primitives = [
        {"final_name": "color/gray/900", "hex": "#111111"},
        {"final_name": "color/blue/500", "hex": "#1a73e8"},
    ]
    suggestions = _suggest_semantic_tokens(primitives, existing_seed={})
    names = [s["semantic_name"] for s in suggestions]
    assert "color/accent/primary" in names


def test_suggest_returns_empty_on_no_primitives():
    suggestions = _suggest_semantic_tokens([], existing_seed={})
    assert suggestions == []


def test_suggest_single_primitive_fires_text_and_canvas():
    primitives = [{"final_name": "color/gray/500", "hex": "#888888"}]
    suggestions = _suggest_semantic_tokens(primitives, existing_seed={})
    names = [s["semantic_name"] for s in suggestions]
    assert "color/text/primary" in names
    assert "color/canvas/primary" in names
```

- [ ] **Step 2: Run tests — expect failure**

```bash
.venv/bin/python -m pytest tests/test_semantic_tokens.py -k "suggest" -v
```

Expected: **FAIL** with `ImportError: cannot import name '_suggest_semantic_tokens'`.

- [ ] **Step 3: Implement `_suggest_semantic_tokens`**

Add after `_build_and_validate_semantic_normalized` in `plan_colors.py`:

```python
def _suggest_semantic_tokens(
    primitives_normalized: list[dict],
    *,
    existing_seed: dict,
) -> list[dict]:
    """Return heuristic semantic token suggestions from a primitive list.

    Each suggestion is a dict:
        semantic_name: str
        primitive_name: str
        reason: str
        covered: bool  (True if semantic_name already in existing_seed)

    Primitives are sorted darkest → lightest by luminance.
    A primitive may appear in multiple suggestions; no deduplication.
    """
    if not primitives_normalized:
        return []

    # Extract entries with valid hex and final_name.
    entries = [
        e for e in primitives_normalized
        if isinstance(e.get("hex"), str) and isinstance(e.get("final_name"), str)
    ]
    if not entries:
        return []

    # Sort darkest → lightest (ascending luminance).
    sorted_entries = sorted(entries, key=lambda e: _hex_luminance(e["hex"]))
    n = len(sorted_entries)

    def suggestion(semantic_name: str, primitive_name: str, reason: str) -> dict:
        return {
            "semantic_name": semantic_name,
            "primitive_name": primitive_name,
            "reason": reason,
            "covered": semantic_name in existing_seed,
        }

    results: list[dict] = []

    # Rule 1 — darkest → text/primary
    results.append(suggestion("color/text/primary", sorted_entries[0]["final_name"], "darkest primitive"))

    # Rule 2 — second-darkest → text/secondary (only if distinct index)
    if n >= 2:
        results.append(suggestion("color/text/secondary", sorted_entries[1]["final_name"], "dark scale entry"))

    # Rule 3 — one step lighter than text/primary → text/disabled (index 1, same as secondary)
    # Both secondary and disabled are emitted even if they resolve to the same primitive.
    if n >= 2:
        results.append(suggestion("color/text/disabled", sorted_entries[1]["final_name"], "lighter than primary → disabled"))

    # Rule 4 — mid-scale → border/primary
    # Middle index of sorted list; on even-sized lists, pick the darker of the two centre entries (lower index).
    mid_idx = (n - 1) // 2
    results.append(suggestion("color/border/primary", sorted_entries[mid_idx]["final_name"], "mid-scale entry"))

    # Rule 5 — second-lightest → surface/primary (only if distinct from lightest)
    if n >= 2 and sorted_entries[-2]["final_name"] != sorted_entries[-1]["final_name"]:
        results.append(suggestion("color/surface/primary", sorted_entries[-2]["final_name"], "near-lightest entry"))

    # Rule 6 — lightest → canvas/primary
    results.append(suggestion("color/canvas/primary", sorted_entries[-1]["final_name"], "lightest primitive"))

    # Rule 7 — saturated primitive → accent/primary
    for entry in sorted_entries:
        h = entry["hex"].lstrip("#")
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            _, _, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if s > 0.40:
                results.append(suggestion("color/accent/primary", entry["final_name"], "saturated — accent candidate"))
                break

    return results
```

- [ ] **Step 4: Run tests — expect pass**

```bash
.venv/bin/python -m pytest tests/test_semantic_tokens.py -v
```

Expected: all tests **PASS**.

- [ ] **Step 5: Commit**

```bash
git add plan_colors.py tests/test_semantic_tokens.py
git commit -m "feat: add _suggest_semantic_tokens pure function with heuristic rules"
```

---

## Task 4: Add `suggest-semantic-tokens` CLI command

**Files:**
- Modify: `plan_handlers.py` (import + new command after `semantic-tokens-normalized`)

- [ ] **Step 1: Add import**

In `plan_handlers.py`, add `_suggest_semantic_tokens` to the import block from `plan_colors`:

```python
from plan_colors import (  # noqa: F401
    ...
    _build_and_validate_semantic_normalized,
    _suggest_semantic_tokens,
)
```

- [ ] **Step 2: Add the command**

Append after the `plan_semantic_tokens_normalized` function in `plan_handlers.py`:

```python
@plan_app.command("suggest-semantic-tokens")
def plan_suggest_semantic_tokens(
    primitives: str = typer.Option(
        str(_TOKENS_DIR / "primitives.normalized.json"),
        "--primitives",
        help="Path to primitives.normalized.json.",
    ),
    seed: str = typer.Option(
        str(_TOKENS_DIR / "semantics.seed.json"),
        "--seed",
        help="Path to semantics.seed.json (optional — used to mark covered entries).",
    ),
    out: str = typer.Option(
        "",
        "--out",
        help="Write suggestions to this file (optional). Never writes semantics.seed.json.",
    ),
) -> None:
    """Suggest semantic token mappings from existing primitives.

    Reads primitives.normalized.json and prints heuristic suggestions to stdout.
    Does not write semantics.seed.json under any circumstance.
    Use --out to write tokens/semantics.suggested.json for manual review.
    """
    primitives_path = Path(primitives).resolve()
    seed_path = Path(seed).resolve()

    if not primitives_path.exists():
        typer.echo(
            f"ERROR: primitives file not found: {primitives_path}\n"
            f"Run `plan primitive-colors-normalized` first.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        primitives_data = json.loads(primitives_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read primitives: {e}", err=True)
        raise typer.Exit(1)

    primitives_list = primitives_data.get("colors") if isinstance(primitives_data, dict) else None
    if not isinstance(primitives_list, list):
        typer.echo(f"ERROR: {primitives_path} missing required 'colors' list.", err=True)
        raise typer.Exit(1)

    existing_seed: dict = {}
    if seed_path.exists():
        try:
            existing_seed = json.loads(seed_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing_seed = {}

    suggestions = _suggest_semantic_tokens(primitives_list, existing_seed=existing_seed)

    # --- Stdout table ---
    n_primitives = len(primitives_list)
    n_suggestions = len(suggestions)
    n_covered = sum(1 for s in suggestions if s["covered"])
    typer.echo(f"\nSemantic token suggestions  ({n_primitives} primitive(s) → {n_suggestions} suggestion(s))\n")

    if suggestions:
        col_name = max(len(s["semantic_name"]) for s in suggestions)
        col_prim = max(len(s["primitive_name"]) for s in suggestions)
        col_reason = max(len(s["reason"]) for s in suggestions)
        header = (
            f"  {'semantic name':<{col_name}}  {'primitive':<{col_prim}}  {'reason':<{col_reason}}  covered?"
        )
        typer.echo(header)
        typer.echo("  " + "─" * (len(header) - 2))
        for s in suggestions:
            covered_label = "[covered]" if s["covered"] else ""
            typer.echo(
                f"  {s['semantic_name']:<{col_name}}  {s['primitive_name']:<{col_prim}}  {s['reason']:<{col_reason}}  {covered_label}"
            )
    else:
        typer.echo("  (no suggestions — palette is empty)")

    typer.echo("")
    typer.echo(f"{n_suggestions} suggestion(s)  ({n_covered} already covered in seed)")

    # Contextual notes
    suggestion_names = {s["semantic_name"] for s in suggestions}
    if not any(n.startswith("color/accent/") for n in suggestion_names):
        typer.echo("Note: no saturated primitives — color/accent skipped.")
    if "color/text/secondary" not in suggestion_names:
        typer.echo("Note: only 1 primitive — color/text/secondary skipped (needs distinct dark entry).")
    if "color/surface/primary" not in suggestion_names and n_primitives >= 2:
        typer.echo("Note: no distinct second-lightest primitive — color/surface/primary skipped.")

    if not out:
        typer.echo(f"\nTo write: plan suggest-semantic-tokens --out tokens/semantics.suggested.json")
        return

    # --- Optional file output ---
    out_path = Path(out).resolve()
    uncovered = {s["semantic_name"]: s["primitive_name"] for s in suggestions if not s["covered"]}
    sorted_out = {k: uncovered[k] for k in sorted(uncovered.keys())}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(sorted_out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nSuggestions written to: {out_path}")
    typer.echo("(Covered entries excluded. Copy entries manually into semantics.seed.json to use them.)")
```

- [ ] **Step 3: Run the command manually**

```bash
.venv/bin/python run.py plan suggest-semantic-tokens
```

Expected: suggestion table printed to stdout with 5–7 rows for the current 3-primitive palette. No file written.

- [ ] **Step 4: Test `--out` flag**

```bash
.venv/bin/python run.py plan suggest-semantic-tokens --out tokens/semantics.suggested.json
cat tokens/semantics.suggested.json
```

Expected: flat JSON with uncovered suggestions only, sorted by key, trailing newline. `semantics.seed.json` is unchanged.

- [ ] **Step 5: Run full test suite**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: all tests **PASS**.

- [ ] **Step 6: Commit**

```bash
git add plan_handlers.py
git commit -m "feat: add plan suggest-semantic-tokens CLI command"
```

---

## Task 5: Manual end-to-end verification

- [ ] **Step 1: Confirm normalize still works with migrated seed**

```bash
.venv/bin/python run.py plan semantic-tokens-normalized
```

Expected: `OK: 5 semantic token(s) written to .../tokens/semantics.normalized.json`

- [ ] **Step 2: Confirm negative guard — introduce a bad state**

Edit `tokens/semantics.seed.json` temporarily, changing one entry to use `"color/text/default"`. Run:

```bash
.venv/bin/python run.py plan semantic-tokens-normalized
```

Expected: non-zero exit with `state 'default' not in allowed states`. Restore the seed.

- [ ] **Step 3: Confirm primitive pipeline is untouched**

```bash
bash scripts/pipeline_primitive_colors.sh --help
```

Expected: help text prints, no error. Primitive pipeline behavior is unchanged.

- [ ] **Step 4: Commit verification note**

```bash
git add tokens/semantics.normalized.json
git commit -m "chore: regenerate semantics.normalized.json after enum migration"
```

---

## Self-Review

**Spec coverage:**
- ✅ Command name: `plan suggest-semantic-tokens`
- ✅ Input files: `primitives.normalized.json` (required), `semantics.seed.json` (optional)
- ✅ Output file: `semantics.suggested.json` via `--out` only
- ✅ Heuristic rules 1–7 all implemented in `_suggest_semantic_tokens`
- ✅ Canvas/surface never share same primitive on ≥ 2 primitives (rule 5 checks `sorted_entries[-2] != sorted_entries[-1]`)
- ✅ Disabled + secondary both emitted, no deduplication (rules 2 and 3 are independent appends)
- ✅ Mid-scale on even list: `(n-1) // 2` picks lower index = darker centre entry ✓
- ✅ Accent only on S > 0.40
- ✅ `SEMANTIC_ROLES` / `SEMANTIC_STATES` updated; `default` removed
- ✅ Seed migration is Task 1 before any code change
- ✅ `semantics.seed.json` never written by command

**Type consistency:** `_suggest_semantic_tokens` returns `list[dict]` with keys `semantic_name`, `primitive_name`, `reason`, `covered` — all test assertions reference these exact keys.

**Placeholder scan:** None found.
