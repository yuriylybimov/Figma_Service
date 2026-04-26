# Phase 3.5 — Suggest Primitive Seed Data from Figma

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read real non-color primitive values (spacing, radius, stroke-width, font-*, line-height, letter-spacing, opacity) from a live Figma file and produce suggestion files for manual review — without ever writing to the seed files.

**Architecture:** A Figma-side JS script scans node geometry and text styles on all pages; it returns a raw extraction payload. A host-side pure Python function groups, deduplicates, and ranks the values per token type. A CLI command (`plan suggest-primitive-seeds`) wires these together and writes one suggestion file per type to `tokens/<type>.suggested.json`. Seed files are never touched. No color pipeline code is modified.

**Tech Stack:** Python 3.10 (Typer CLI, pure functions, no Pydantic), pytest, JavaScript (Figma plugin API), JSON.

---

## Constraints (always active)

- Do NOT modify `tokens/<type>.seed.json` files — ever.
- Do NOT modify or refactor the color pipeline.
- Do NOT invent values. Every suggested value must come from Figma.
- Do NOT run `sync` during development — read and plan commands only.
- Suggestion files are advisory output, never source of truth.
- Do NOT use Git commands.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `scripts/variables/read_primitive_usage.js` | Create | Figma-side: scan all pages, collect raw spacing/radius/stroke/font/opacity values from nodes and text styles |
| `suggest_primitives.py` | Create | Host-side pure logic: group raw values by type, deduplicate, rank by frequency, return suggestion dicts |
| `tests/test_suggest_primitives.py` | Create | Unit tests for `suggest_primitives.py` (pure function, no I/O) |
| `read_handlers.py` | Modify | Add `read primitive-usage` command that runs the JS and writes raw output |
| `plan_handlers.py` | Modify | Add `plan suggest-primitive-seeds` command that reads raw output and writes `*.suggested.json` files |
| `tests/test_plan_suggest_primitive_seeds.py` | Create | CLI integration tests for `plan suggest-primitive-seeds` |

---

## Phase 3.5 — Task overview

| Task | What it produces |
|---|---|
| Task 3.5.1 | JS script that reads raw primitive usage from Figma |
| Task 3.5.2 | `read primitive-usage` CLI command |
| Task 3.5.3 | `suggest_primitives.py` pure logic + tests |
| Task 3.5.4 | `plan suggest-primitive-seeds` CLI command + tests |

---

## Task 3.5.1 — JS script: read raw primitive usage from Figma

**Goal:** Scan all pages; collect the raw values that will feed the host-side suggester for every non-color type.

**Files:**
- Create: `scripts/variables/read_primitive_usage.js`

### Global extraction rules (apply to all projects)

These rules define what counts as a primitive candidate across any Figma file. They are not project-specific defaults — they are the stable baseline for all future extractions.

#### Spacing

- **Auto Layout only.** Spacing is collected exclusively from nodes where `layoutMode` is `"HORIZONTAL"` or `"VERTICAL"`. Nodes with `layoutMode === "NONE"` are skipped entirely — their padding properties reflect manual positioning, not intentional spacing tokens.
- **Properties collected:** `paddingLeft`, `paddingRight`, `paddingTop`, `paddingBottom`, `itemSpacing` only. Width, height, x/y position, constraints, and layout dimensions are never collected.
- **Value range:** `4 <= value <= 128`. Values below 4 are sub-pixel noise or border widths, not spacing tokens. Values above 128 are almost always layout dimensions.
- This range is defined as `SPACING_MIN = 4` / `SPACING_MAX = 128` in both the JS (`read_primitive_usage.js`) and Python (`suggest_primitives.py`) — the JS is the primary gate; Python re-applies the same bounds as a defensive second pass.

#### Radius

- Collected from `cornerRadius` (when a single number, not Mixed) and from per-corner properties (`topLeftRadius`, `topRightRadius`, `bottomLeftRadius`, `bottomRightRadius`) when corners differ.
- Zero radius (`cornerRadius === 0`) is kept — it is a valid explicit design token.
- Values `>= 9999` (e.g. Figma's internal `16777200`) are treated as **full-radius candidates** (pill shapes, circles). They bypass 4px grid normalization and are marked `"candidate": "full-radius"` in the suggested output. They are never merged into normal radius buckets.

#### Other types

No special range filters beyond those imposed by Figma's own API (e.g. `opacity < 1`, `letterSpacing.unit === "PIXELS"`). All extracted values are forwarded to the host as-is.

---

### What the script collects

| Token type | Figma source | Filter |
|---|---|---|
| `spacing` | `paddingLeft`, `paddingRight`, `paddingTop`, `paddingBottom`, `itemSpacing` on Auto Layout nodes only (`layoutMode !== "NONE"`) | `4 <= v <= 128` |
| `radius` | `cornerRadius` (single value) and `topLeftRadius`, etc. on FRAME/RECTANGLE/COMPONENT nodes | none at JS level; `>= 9999` flagged in Python |
| `stroke-width` | `strokeWeight` on any node with `strokes.length > 0` | `> 0` |
| `font-size` | `fontSize` from TEXT nodes and local text styles | none |
| `font-weight` | Parsed from `fontName.style` string (e.g. `"Bold"` → `700`) from TEXT nodes and local text styles | none |
| `font-family` | `fontName.family` string from TEXT nodes and local text styles | none |
| `line-height` | `lineHeight.value` when `lineHeight.unit === "PIXELS"` from TEXT nodes and local text styles | none |
| `letter-spacing` | `letterSpacing.value` when `letterSpacing.unit === "PIXELS"` from TEXT nodes and local text styles | none |
| `opacity` | `opacity` when `opacity < 1` from any node | `< 1` |

### Output shape

```json
{
  "scanned_pages": 3,
  "scanned_nodes": 1420,
  "spacing": [4, 8, 8, 16, 4, 24],
  "radius": [4, 8, 0, 12, 4],
  "stroke_width": [1, 1, 2, 1],
  "font_size": [13, 15, 15, 24, 13],
  "font_weight": [400, 600, 400, 700],
  "font_family": ["Inter", "Inter", "SF Pro Display"],
  "line_height": [20, 24, 20, 32],
  "letter_spacing": [0, -0.5, 0],
  "opacity": [0.5, 0.1, 0.5]
}
```

- Values are **raw lists** (with duplicates). Deduplication and ranking happen on the host.
- `null` / `figma.mixed` values are skipped. Zero values included only for `radius`, `letter-spacing`, `opacity`.
- Spacing: only Auto Layout values in range `[4, 128]` collected. Radius: `cornerRadius` used when it is a number (not Mixed). When individual corner radii differ, collect each non-zero value separately.

- [ ] **Step 1: Create `scripts/variables/read_primitive_usage.js`**

```javascript
// read_primitive_usage.js
// Read-only scan: raw primitive (non-color) values across all pages.
// No writes to Figma.

const spacing   = [];
const radius    = [];
const strokeWidth = [];
const fontSize  = [];
const fontWeight = [];
const fontFamily = [];
const lineHeight = [];
const letterSpacing = [];
const opacity   = [];

let scannedNodes = 0;

function recordSpacing(node) {
  for (const prop of ["paddingLeft", "paddingRight", "paddingTop", "paddingBottom", "itemSpacing"]) {
    const v = node[prop];
    if (typeof v === "number" && v > 0) spacing.push(v);
  }
}

function recordRadius(node) {
  const cr = node.cornerRadius;
  if (typeof cr === "number") {
    radius.push(cr);
    return;
  }
  // Mixed corners — collect each individually
  for (const prop of ["topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius"]) {
    const v = node[prop];
    if (typeof v === "number") radius.push(v);
  }
}

function recordText(node) {
  const fs = node.fontSize;
  if (typeof fs === "number") fontSize.push(fs);

  const fw = node.fontWeight;
  if (typeof fw === "number") fontWeight.push(fw);

  const ff = node.fontName;
  if (ff && typeof ff === "object" && typeof ff.family === "string") {
    fontFamily.push(ff.family);
  }

  const lh = node.lineHeight;
  if (lh && lh.unit === "PIXELS" && typeof lh.value === "number") {
    lineHeight.push(lh.value);
  }

  const ls = node.letterSpacing;
  if (ls && ls.unit === "PIXELS" && typeof ls.value === "number") {
    letterSpacing.push(ls.value);
  }
}

for (const page of figma.root.children) {
  const nodes = page.findAll(() => true);
  for (const node of nodes) {
    scannedNodes++;

    if (typeof node.opacity === "number" && node.opacity < 1) {
      opacity.push(node.opacity);
    }

    if (node.strokes && node.strokes.length > 0) {
      const sw = node.strokeWeight;
      if (typeof sw === "number" && sw > 0) strokeWidth.push(sw);
    }

    const t = node.type;
    if (t === "FRAME" || t === "COMPONENT" || t === "COMPONENT_SET" || t === "INSTANCE") {
      recordSpacing(node);
      recordRadius(node);
    }

    if (t === "RECTANGLE" || t === "ELLIPSE" || t === "POLYGON" || t === "STAR" || t === "VECTOR") {
      recordRadius(node);
    }

    if (t === "TEXT") {
      recordText(node);
    }
  }
}

// Collect from text styles (deduplicated by style name)
for (const style of figma.getLocalTextStyles()) {
  const fs = style.fontSize;
  if (typeof fs === "number") fontSize.push(fs);

  const fw = style.fontWeight;
  if (typeof fw === "number") fontWeight.push(fw);

  const ff = style.fontName;
  if (ff && typeof ff.family === "string") fontFamily.push(ff.family);

  const lh = style.lineHeight;
  if (lh && lh.unit === "PIXELS" && typeof lh.value === "number") lineHeight.push(lh.value);

  const ls = style.letterSpacing;
  if (ls && ls.unit === "PIXELS" && typeof ls.value === "number") letterSpacing.push(ls.value);
}

return {
  scanned_pages: figma.root.children.length,
  scanned_nodes: scannedNodes,
  spacing,
  radius,
  stroke_width: strokeWidth,
  font_size: fontSize,
  font_weight: fontWeight,
  font_family: fontFamily,
  line_height: lineHeight,
  letter_spacing: letterSpacing,
  opacity,
};
```

- [ ] **Step 2: Confirm the file exists and is syntactically valid**

```
node --check scripts/variables/read_primitive_usage.js 2>&1 || echo "node not available, skip syntax check"
```

Expected: either `OK` or the "node not available" fallback — no parse errors.

---

## Task 3.5.2 — `read primitive-usage` CLI command

**Goal:** Wire the JS script into the existing read pipeline so the user can capture raw primitive usage to a file.

**Files:**
- Modify: `read_handlers.py` — add `read primitive-usage` command after the existing `color-usage-*` commands

The command follows exactly the pattern of `read color-usage-detail`: load a JS file from `scripts/variables/`, pass it to `_dispatch_read`, require `--out`.

- [ ] **Step 1: Add `read primitive-usage` to `read_handlers.py`**

Open `read_handlers.py`. After the `read_color_usage_summary` command (currently the last color command, around line 395), add:

```python
@read_app.command("primitive-usage")
def read_primitive_usage(
    out: str = typer.Option(..., "--out", help="Write raw primitive usage JSON to this path (required — payload may be large)."),
    timeout: float = typer.Option(30.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Scan Figma file for non-color primitive values (spacing, radius, font-*, etc.); write raw usage JSON to --out."""
    script_path = _SCRIPT_DIR / "read_primitive_usage.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")
    user_js = script_path.read_text(encoding="utf-8")
    _dispatch_read(user_js, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)
```

- [ ] **Step 2: Smoke-test the help output**

```
.venv/bin/python run.py read --help
```

Expected: `primitive-usage` appears in the command list.

---

## Task 3.5.3 — `suggest_primitives.py` pure logic + tests

**Goal:** A pure function that takes the raw usage payload (dict of lists) and returns per-type suggestion dicts ready to be written as seed files.

**Files:**
- Create: `suggest_primitives.py`
- Create: `tests/test_suggest_primitives.py`

### Output shape per type (FLOAT)

```python
[
  {"name": "spacing/1", "value": 4.0, "use_count": 42},
  {"name": "spacing/2", "value": 8.0, "use_count": 31},
  ...
]
```

- Values sorted ascending.
- Names use numeric suffixes for FLOAT types: `spacing/1`, `spacing/2`, ...
- For `font-family` (STRING): names use the sanitised family name: `font-family/inter`, `font-family/sf-pro-display`.
- `use_count` is included for the user's reference; it is NOT part of the validated seed format — the user removes it manually before running `validate-primitives`.
- Minimum use count threshold: values appearing only once are still included (user decides what to keep).

### Grouping rules

| Type | Key in raw payload | Dedup rule |
|---|---|---|
| spacing | `spacing` | round to nearest 0.5, deduplicate |
| radius | `radius` | round to nearest 0.5, deduplicate |
| stroke-width | `stroke_width` | round to nearest 0.5, deduplicate |
| font-size | `font_size` | round to nearest 0.5, deduplicate |
| font-weight | `font_weight` | round to nearest integer, deduplicate |
| font-family | `font_family` | exact string, deduplicate |
| line-height | `line_height` | round to nearest 0.5, deduplicate |
| letter-spacing | `letter_spacing` | round to nearest 0.5, deduplicate |
| opacity | `opacity` | round to 2 decimal places, deduplicate |

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_suggest_primitives.py
from suggest_primitives import suggest_primitive_entries, _count_and_rank, _sanitize_family_name


def test_count_and_rank_basic():
    result = _count_and_rank([4, 8, 4, 16, 8, 4])
    # 4→3, 8→2, 16→1
    assert result[4.0] == 3
    assert result[8.0] == 2
    assert result[16.0] == 1


def test_count_and_rank_rounds_to_half():
    result = _count_and_rank([4.1, 4.2, 8.0], round_to=0.5)
    # 4.1 and 4.2 both round to 4.0
    assert result[4.0] == 2
    assert result[8.0] == 1


def test_count_and_rank_opacity_rounds_to_two_decimals():
    result = _count_and_rank([0.501, 0.499, 0.1], round_to=0.01)
    assert result[0.50] == 2
    assert result[0.1] == 1


def test_sanitize_family_name():
    assert _sanitize_family_name("Inter") == "inter"
    assert _sanitize_family_name("SF Pro Display") == "sf-pro-display"
    assert _sanitize_family_name("JetBrains Mono") == "jetbrains-mono"


def test_suggest_spacing_entries():
    raw = {"spacing": [4, 8, 4, 16]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert values == sorted(values)  # ascending
    assert 4.0 in values
    assert 8.0 in values
    assert 16.0 in values
    for e in result:
        assert e["name"].startswith("spacing/")
        assert "use_count" in e


def test_suggest_spacing_names_are_sequential():
    raw = {"spacing": [4, 8, 16]}
    result = suggest_primitive_entries("spacing", raw)
    names = [e["name"] for e in result]
    assert names == ["spacing/1", "spacing/2", "spacing/3"]


def test_suggest_font_family_uses_sanitized_name():
    raw = {"font_family": ["Inter", "Inter", "SF Pro Display"]}
    result = suggest_primitive_entries("font-family", raw)
    names = [e["name"] for e in result]
    assert "font-family/inter" in names
    assert "font-family/sf-pro-display" in names


def test_suggest_font_family_values_are_strings():
    raw = {"font_family": ["Inter"]}
    result = suggest_primitive_entries("font-family", raw)
    assert result[0]["value"] == "Inter"


def test_suggest_returns_empty_for_empty_input():
    raw = {"spacing": []}
    result = suggest_primitive_entries("spacing", raw)
    assert result == []


def test_suggest_unknown_type_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown type"):
        suggest_primitive_entries("color", {})


def test_suggest_opacity_values_capped_at_1():
    raw = {"opacity": [0.5, 0.5, 1.0, 0.1]}
    result = suggest_primitive_entries("opacity", raw)
    for e in result:
        assert 0.0 <= e["value"] <= 1.0


def test_suggest_deduplicates_after_rounding():
    # 4.0 and 4.1 both round to 4.0; should appear only once
    raw = {"spacing": [4.0, 4.1, 8.0]}
    result = suggest_primitive_entries("spacing", raw)
    values = [e["value"] for e in result]
    assert values.count(4.0) == 1
    assert len(values) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/python -m pytest tests/test_suggest_primitives.py -v
```

Expected: `ModuleNotFoundError: No module named 'suggest_primitives'`

- [ ] **Step 3: Create `suggest_primitives.py`**

```python
"""Pure logic: convert raw Figma primitive usage into ranked seed suggestions.

No I/O. No Figma calls. No seed file writes.
Input: dict returned by read_primitive_usage.js (raw lists per type key).
Output: list of {name, value, use_count} dicts, sorted ascending by value.
"""

import re
from collections import Counter

from primitive_types import PRIMITIVE_TYPES


# Maps token type → raw payload key
_RAW_KEY: dict[str, str] = {
    "spacing":        "spacing",
    "radius":         "radius",
    "stroke-width":   "stroke_width",
    "font-size":      "font_size",
    "font-weight":    "font_weight",
    "font-family":    "font_family",
    "line-height":    "line_height",
    "letter-spacing": "letter_spacing",
    "opacity":        "opacity",
}

# Rounding precision per type (for FLOAT types)
_ROUND_TO: dict[str, float] = {
    "spacing":        0.5,
    "radius":         0.5,
    "stroke-width":   0.5,
    "font-size":      0.5,
    "font-weight":    1.0,
    "line-height":    0.5,
    "letter-spacing": 0.5,
    "opacity":        0.01,
}


def _round_to(value: float, step: float) -> float:
    return round(round(value / step) * step, 10)


def _count_and_rank(values: list, *, round_to: float = 0.5) -> dict:
    """Count occurrences after rounding. Returns {rounded_value: count}."""
    rounded = [_round_to(v, round_to) for v in values]
    return dict(Counter(rounded))


def _sanitize_family_name(family: str) -> str:
    """'SF Pro Display' → 'sf-pro-display'"""
    return re.sub(r"\s+", "-", family.strip()).lower()


def suggest_primitive_entries(type_key: str, raw: dict) -> list[dict]:
    """Return ranked suggestions for one token type.

    Args:
        type_key: e.g. 'spacing', 'font-family'
        raw: dict from read_primitive_usage.js

    Returns:
        List of {name, value, use_count} sorted ascending by value.
        For font-family: sorted alphabetically by name.
    """
    if type_key not in PRIMITIVE_TYPES:
        raise ValueError(f"unknown type '{type_key}'. Valid: {sorted(PRIMITIVE_TYPES)}")

    raw_key = _RAW_KEY[type_key]
    values: list = raw.get(raw_key, [])

    if not values:
        return []

    td = PRIMITIVE_TYPES[type_key]

    if td.figma_type == "STRING":
        # font-family: count exact strings
        counts = Counter(v for v in values if isinstance(v, str))
        entries = sorted(counts.items(), key=lambda x: x[0])  # alphabetical
        return [
            {
                "name": f"{type_key}/{_sanitize_family_name(family)}",
                "value": family,
                "use_count": count,
            }
            for family, count in entries
        ]

    # FLOAT types
    step = _ROUND_TO[type_key]
    counts = _count_and_rank([v for v in values if isinstance(v, (int, float))], round_to=step)

    sorted_values = sorted(counts.keys())
    return [
        {
            "name": f"{type_key}/{i}",
            "value": v,
            "use_count": counts[v],
        }
        for i, v in enumerate(sorted_values, start=1)
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/python -m pytest tests/test_suggest_primitives.py -v
```

Expected: 12 PASSED

---

## Task 3.5.4 — `plan suggest-primitive-seeds` CLI command + tests

**Goal:** CLI command that reads the raw usage JSON (output of `read primitive-usage`), runs `suggest_primitive_entries` for all 9 types, and writes `tokens/<type>.suggested.json` for each type that has at least one suggestion. Never touches `tokens/<type>.seed.json`.

**Files:**
- Modify: `plan_handlers.py` — add `plan suggest-primitive-seeds` command
- Create: `tests/test_plan_suggest_primitive_seeds.py`

### Output file format

Each `tokens/<type>.suggested.json` is a JSON array of suggestion objects:

```json
[
  {"name": "spacing/1", "value": 4.0, "use_count": 42},
  {"name": "spacing/2", "value": 8.0, "use_count": 31}
]
```

The user reviews this file, removes `use_count` from entries they want to keep, and copies selected entries into the seed file manually.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plan_suggest_primitive_seeds.py
import json
import os
from typer.testing import CliRunner
from run import app

runner = CliRunner()


def _raw_usage(tmp_path):
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
    usage_file.write_text(json.dumps(_raw_usage(tmp_path)))
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


def test_suggest_does_not_touch_seed_files(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage(tmp_path)))
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    seed_file = tokens_dir / "spacing.seed.json"
    seed_file.write_text("[]")  # empty seed

    runner.invoke(app, [
        "plan", "suggest-primitive-seeds",
        "--usage", str(usage_file),
        "--tokens-dir", str(tokens_dir),
    ])

    assert seed_file.read_text() == "[]"  # untouched


def test_suggest_skips_type_with_no_data(tmp_path):
    usage_file = tmp_path / "primitive_usage.json"
    usage_file.write_text(json.dumps(_raw_usage(tmp_path)))
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
    usage_file.write_text(json.dumps(_raw_usage(tmp_path)))
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/bin/python -m pytest tests/test_plan_suggest_primitive_seeds.py -v
```

Expected: all FAILED (command does not exist)

- [ ] **Step 3: Add `plan suggest-primitive-seeds` to `plan_handlers.py`**

Open `plan_handlers.py`. At the bottom of the file, after the `plan validate-primitives` command (currently last), add:

```python
@plan_app.command("suggest-primitive-seeds")
def plan_suggest_primitive_seeds(
    usage: str = typer.Option(..., "--usage", help="Path to raw usage JSON written by `read primitive-usage`."),
    tokens_dir: str = typer.Option("tokens", "--tokens-dir", help="Directory where <type>.suggested.json files are written."),
    quiet: bool = typer.Option(False, "--quiet", "-q"),
) -> None:
    """[EXPERIMENTAL] Suggest primitive seed entries from real Figma data.

    Reads raw primitive usage (output of `read primitive-usage`) and writes
    one tokens/<type>.suggested.json per type. Seed files are never modified.
    Output is advisory only — review and copy selected entries manually.
    """
    from suggest_primitives import suggest_primitive_entries
    from primitive_types import PRIMITIVE_TYPES

    usage_path = Path(usage).resolve()
    if not usage_path.exists():
        typer.echo(f"ERROR: usage file not found: {usage_path}", err=True)
        raise typer.Exit(1)

    try:
        raw = json.loads(usage_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(f"ERROR: failed to read usage file: {e}", err=True)
        raise typer.Exit(1)

    out_dir = Path(tokens_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0

    for type_key in PRIMITIVE_TYPES:
        entries = suggest_primitive_entries(type_key, raw)
        if not entries:
            skipped += 1
            if not quiet:
                typer.echo(f"  skip  {type_key} (no data)")
            continue

        out_path = out_dir / f"{type_key}.suggested.json"
        out_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written += 1
        if not quiet:
            typer.echo(f"  wrote {type_key}.suggested.json ({len(entries)} entries)")

    typer.echo(f"\nDone. {written} suggestion file(s) written to {out_dir}, {skipped} type(s) had no data.")
    typer.echo("Review the .suggested.json files. Copy selected entries (without use_count) into the seed files manually.")
```

- [ ] **Step 4: Run tests to verify they pass**

```
.venv/bin/python -m pytest tests/test_plan_suggest_primitive_seeds.py -v
```

Expected: 5 PASSED

- [ ] **Step 5: Run the full test suite**

```
.venv/bin/python -m pytest tests/ -v
```

Expected: all existing tests PASS + all new tests PASS, zero regressions.

---

## Full workflow (post-implementation)

Once all tasks are implemented, the user runs:

```bash
# 1. Capture raw primitive usage from Figma (requires Figma file open in Scripter)
.venv/bin/python run.py read primitive-usage \
  -f <figma-file-url> \
  --out tokens/primitive_usage.json

# 2. Generate suggestion files (host-only, no Figma needed)
.venv/bin/python run.py plan suggest-primitive-seeds \
  --usage tokens/primitive_usage.json

# 3. Review suggestions (e.g. tokens/spacing.suggested.json)
# 4. Copy chosen entries (without use_count) into tokens/spacing.seed.json
# 5. Validate the seed
.venv/bin/python run.py plan validate-primitives spacing
```

---

## Risks

| Risk | Mitigation |
|---|---|
| Figma nodes may return `figma.mixed` (Symbol) for mixed corner radii | JS script checks `typeof === "number"` before collecting; mixed values are skipped |
| Large files may produce very long lists of raw values | All dedup/ranking happens host-side; JS only collects raw arrays |
| Font weight from `node.fontWeight` may not always be available | Guarded by `typeof fw === "number"` check |
| Text styles share fonts with nodes — duplicated values inflate use_count | Acceptable: use_count is advisory, not enforced |
| `letterSpacing.unit` may be `"PERCENT"` in some Figma files | Only `PIXELS` values are collected; percent values are silently skipped (user must convert manually) |
| `.suggested.json` file silently overwrites previous run | Expected behavior, documented in command output |
