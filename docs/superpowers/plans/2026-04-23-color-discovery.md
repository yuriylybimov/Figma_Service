# Color Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two commands — `read color-usage-summary` (scans Figma for solid-fill colors via the Scripter bridge) and `plan primitive-colors-from-project` (host-side analysis that produces `tokens/primitives.proposed.json`) — with no writes to Figma at any stage.

**Architecture:** JS script runs inside the Figma Plugin API sandbox via the existing Playwright+Scripter bridge, returns raw usage JSON written to disk. A second, fully host-side command reads that file, classifies colors against existing primitives and paint styles, prints a summary, and writes a proposal file. A new `plan_handlers.py` holds the plan sub-app, mounted in `run.py` alongside `read_app` and `sync_app`.

**Tech Stack:** Python 3.11+, Typer, Figma Plugin API (JS sandbox), existing `_dispatch_read()` bridge, pytest.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `scripts/variables/read_color_usage_summary.js` | JS scan: node fills/strokes, paint styles, primitive variables reference |
| Modify | `read_handlers.py` | Add `read color-usage-summary` command |
| Create | `plan_handlers.py` | `plan_app` + `plan primitive-colors-from-project` command |
| Modify | `run.py` | Mount `plan_app` as `plan` sub-app |
| Create | `tests/test_plan_handlers.py` | Unit tests for host-side classification, sorting, proposal writing |

---

## Task 1: JS scan script — node fills/strokes

**Files:**
- Create: `scripts/variables/read_color_usage_summary.js`

- [ ] **Step 1: Create the JS file with hex helper and node walk**

```javascript
// read_color_usage_summary.js
// Read-only scan: solid fills/strokes across all pages, paint styles, primitive variables.
// Returns usage data for host-side analysis. No writes to Figma.

function rgbToHex(r, g, b) {
  const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + toHex(r) + toHex(g) + toHex(b);
}

// colorMap: hex -> { fill_count, stroke_count, examples: [{page, node}] }
const colorMap = {};
let scannedNodes = 0;

function recordColor(hex, kind, pageName, nodeName) {
  if (!colorMap[hex]) {
    colorMap[hex] = { fill_count: 0, stroke_count: 0, examples: [] };
  }
  if (kind === "fill") colorMap[hex].fill_count++;
  else colorMap[hex].stroke_count++;
  if (colorMap[hex].examples.length < 3) {
    colorMap[hex].examples.push({ page: pageName, node: nodeName });
  }
}

function scanPaints(paints, kind, pageName, nodeName) {
  if (!Array.isArray(paints)) return;
  for (const paint of paints) {
    if (paint.type !== "SOLID") continue;
    if (paint.visible === false) continue;
    const hex = rgbToHex(paint.color.r, paint.color.g, paint.color.b);
    recordColor(hex, kind, pageName, nodeName);
  }
}

for (const page of figma.root.children) {
  const nodes = page.findAll(() => true);
  for (const node of nodes) {
    scannedNodes++;
    const pageName = page.name;
    const nodeName = node.name;
    if (node.fills) scanPaints(node.fills, "fill", pageName, nodeName);
    if (node.strokes) scanPaints(node.strokes, "stroke", pageName, nodeName);
  }
}

const nodeColors = Object.entries(colorMap).map(([hex, data]) => ({
  hex,
  fill_count: data.fill_count,
  stroke_count: data.stroke_count,
  examples: data.examples,
}));
```

- [ ] **Step 2: Add paint styles scan**

Append to the same file after the `nodeColors` declaration:

```javascript
// Paint styles
const paintStyles = [];
for (const style of figma.getLocalPaintStyles()) {
  const solid = (style.paints || []).find((p) => p.type === "SOLID");
  if (!solid) continue;
  paintStyles.push({
    name: style.name,
    hex: rgbToHex(solid.color.r, solid.color.g, solid.color.b),
    style_id: style.id,
  });
}
```

- [ ] **Step 3: Add primitive variables reference scan**

Append after `paintStyles`:

```javascript
// Primitive variables — reference only, not counted as usage
const primitiveVariables = [];
const primCol = figma.variables
  .getLocalVariableCollections()
  .find((c) => c.name === "primitives");
if (primCol) {
  const modeId = primCol.defaultModeId || primCol.modes[0].modeId;
  for (const vid of primCol.variableIds) {
    const v = figma.variables.getVariableById(vid);
    if (!v || v.resolvedType !== "COLOR") continue;
    const val = v.valuesByMode[modeId];
    if (!val || typeof val.r !== "number") continue;
    primitiveVariables.push({
      name: v.name,
      hex: rgbToHex(val.r, val.g, val.b),
    });
  }
}
```

- [ ] **Step 4: Add totals and return statement**

Append after `primitiveVariables`:

```javascript
return {
  scanned_pages: figma.root.children.length,
  scanned_nodes: scannedNodes,
  totals: {
    unique_node_colors: nodeColors.length,
    paint_style_colors: paintStyles.length,
    primitive_variable_colors: primitiveVariables.length,
  },
  node_colors: nodeColors,
  paint_styles: paintStyles,
  primitive_variables: primitiveVariables,
};
```

- [ ] **Step 5: Commit**

```bash
git add scripts/variables/read_color_usage_summary.js
git commit -m "feat(read): add read_color_usage_summary JS scan script"
```

---

## Task 2: Python handler — `read color-usage-summary`

**Files:**
- Modify: `read_handlers.py`

The existing `_dispatch_read()` in `read_handlers.py` handles all bridge orchestration. This command reads the JS from disk and dispatches it — no template substitution needed (no `__PLACEHOLDER__` tokens in this script).

- [ ] **Step 1: Add the JS path constant and command to `read_handlers.py`**

Open `read_handlers.py`. After the `_SCRIPT_DIR` equivalent (there is none yet in read_handlers — add it at the top of the design-system read layer, after the existing `_LOCAL_STYLES_KINDS` block, before the end of file):

```python
_SCRIPT_DIR = Path(__file__).parent / "scripts" / "variables"


@read_app.command("color-usage-summary")
def read_color_usage_summary(
    out: str = typer.Option(..., "--out", help="Write usage JSON to this path (required — payload may be large)."),
    timeout: float = typer.Option(30.0, "--timeout"),
    mount_timeout: float = typer.Option(30.0, "--mount-timeout"),
    file_url: str | None = typer.Option(None, "-f", "--file"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Scan Figma file for solid-fill colors; write raw usage JSON to --out."""
    script_path = _SCRIPT_DIR / "read_color_usage_summary.js"
    if not script_path.exists():
        raise typer.BadParameter(f"Script not found: {script_path}")
    user_js = script_path.read_text(encoding="utf-8")
    _dispatch_read(user_js, out=out, timeout=timeout,
                   mount_timeout=mount_timeout, file_url=file_url, quiet=quiet)
```

Note: default timeout is 30s (not 10s) because `findAll()` on large files can be slow.

- [ ] **Step 2: Commit**

```bash
git add read_handlers.py
git commit -m "feat(read): add color-usage-summary command"
```

---

## Task 3: `plan_handlers.py` skeleton + `run.py` mount

**Files:**
- Create: `plan_handlers.py`
- Modify: `run.py`

- [ ] **Step 1: Create `plan_handlers.py` with the Typer app**

```python
"""Host-side planning commands — the `plan` sub-app.

All commands run entirely on the host. No Figma round-trips.
"""

from pathlib import Path

import typer

plan_app = typer.Typer(no_args_is_help=True, help="Host-side planning and proposal commands.")

_TOKENS_DIR = Path(__file__).parent / "tokens"
```

- [ ] **Step 2: Mount `plan_app` in `run.py`**

In `run.py`, find the two existing import + mount lines:

```python
from read_handlers import read_app
from sync_handlers import sync_app
```

Add the import:

```python
from read_handlers import read_app
from sync_handlers import sync_app
from plan_handlers import plan_app
```

Then find:

```python
app.add_typer(read_app, name="read")
app.add_typer(sync_app, name="sync")
```

Add:

```python
app.add_typer(read_app, name="read")
app.add_typer(sync_app, name="sync")
app.add_typer(plan_app, name="plan")
```

- [ ] **Step 3: Verify the sub-app is visible**

```bash
python run.py plan --help
```

Expected output includes:
```
Usage: run.py plan [OPTIONS] COMMAND [ARGS]...
Host-side planning and proposal commands.
```

- [ ] **Step 4: Commit**

```bash
git add plan_handlers.py run.py
git commit -m "feat(plan): scaffold plan_app and mount in run.py"
```

---

## Task 4: Tests for host-side classification logic

Write tests before the implementation so failures are meaningful.

**Files:**
- Create: `tests/test_plan_handlers.py`

The functions under test will be `_build_lookup`, `_classify_colors`, and `_sort_colors` — small pure functions extracted from the command handler. They take plain dicts and return plain dicts/lists. No Typer, no file I/O in the unit tests.

- [ ] **Step 1: Write the test file**

```python
"""Unit tests for plan_handlers host-side logic."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import plan_handlers as ph


# --- _build_lookup ---

def test_build_lookup_basic():
    items = [{"hex": "#ffffff", "name": "color/base/white"}]
    result = ph._build_lookup(items, key="hex", value="name")
    assert result == {"#ffffff": "color/base/white"}


def test_build_lookup_first_seen_wins_on_duplicate():
    items = [
        {"hex": "#3b82f6", "name": "color/blue/500"},
        {"hex": "#3b82f6", "name": "color/blue/500-alt"},
    ]
    warnings = []
    result = ph._build_lookup(items, key="hex", value="name", warn=warnings.append)
    assert result == {"#3b82f6": "color/blue/500"}
    assert len(warnings) == 1
    assert "#3b82f6" in warnings[0]


# --- _classify_colors ---

def _make_color(hex_, fill=1, stroke=0, examples=None):
    return {
        "hex": hex_,
        "fill_count": fill,
        "stroke_count": stroke,
        "examples": examples or [{"page": "P", "node": "N"}],
    }


def test_classify_matched():
    colors = [_make_color("#ffffff")]
    prim = {"#ffffff": "color/base/white"}
    result = ph._classify_colors(colors, prim_lookup=prim, style_lookup={})
    assert result[0]["status"] == "matched"
    assert result[0]["primitive_name"] == "color/base/white"
    assert result[0]["paint_style_name"] is None
    assert result[0]["duplicate_warning"] is False


def test_classify_paint_style():
    colors = [_make_color("#3b82f6")]
    style = {"#3b82f6": "brand/primary"}
    result = ph._classify_colors(colors, prim_lookup={}, style_lookup=style)
    assert result[0]["status"] == "paint_style"
    assert result[0]["paint_style_name"] == "brand/primary"
    assert result[0]["primitive_name"] is None


def test_classify_new_candidate():
    colors = [_make_color("#ef4444")]
    result = ph._classify_colors(colors, prim_lookup={}, style_lookup={})
    assert result[0]["status"] == "new_candidate"
    assert result[0]["primitive_name"] is None
    assert result[0]["paint_style_name"] is None


def test_classify_primitive_wins_over_style():
    colors = [_make_color("#ffffff")]
    prim = {"#ffffff": "color/base/white"}
    style = {"#ffffff": "some/style"}
    result = ph._classify_colors(colors, prim_lookup=prim, style_lookup=style)
    assert result[0]["status"] == "matched"


def test_classify_preserves_duplicate_warning():
    colors = [_make_color("#ffffff")]
    colors[0]["_dup_prim"] = True
    prim = {"#ffffff": "color/base/white"}
    result = ph._classify_colors(colors, prim_lookup=prim, style_lookup={}, dup_prim_hexes={"#ffffff"})
    assert result[0]["duplicate_warning"] is True


# --- _sort_colors ---

def _make_classified(hex_, status, fill=1, stroke=0):
    return {
        "hex": hex_,
        "fill_count": fill,
        "stroke_count": stroke,
        "status": status,
        "primitive_name": None,
        "paint_style_name": None,
        "duplicate_warning": False,
        "examples": [],
    }


def test_sort_status_group_order():
    colors = [
        _make_classified("#aaaaaa", "new_candidate", fill=50),
        _make_classified("#bbbbbb", "paint_style", fill=30),
        _make_classified("#cccccc", "matched", fill=10),
    ]
    result = ph._sort_colors(colors)
    assert [c["status"] for c in result] == ["matched", "paint_style", "new_candidate"]


def test_sort_usage_desc_within_group():
    colors = [
        _make_classified("#aaaaaa", "new_candidate", fill=5, stroke=0),
        _make_classified("#bbbbbb", "new_candidate", fill=20, stroke=0),
    ]
    result = ph._sort_colors(colors)
    assert result[0]["hex"] == "#bbbbbb"


def test_sort_hex_asc_tiebreak():
    colors = [
        _make_classified("#zzzzzz", "new_candidate", fill=10),
        _make_classified("#aaaaaa", "new_candidate", fill=10),
    ]
    result = ph._sort_colors(colors)
    assert result[0]["hex"] == "#aaaaaa"
```

- [ ] **Step 2: Run tests — expect import errors (functions not defined yet)**

```bash
cd /Users/yuriiliubymov/Documents/claude/Figma_Service
python -m pytest tests/test_plan_handlers.py -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError: module 'plan_handlers' has no attribute '_build_lookup'`

- [ ] **Step 3: Commit the test file**

```bash
git add tests/test_plan_handlers.py
git commit -m "test(plan): add failing tests for classification and sorting helpers"
```

---

## Task 5: Implement helper functions in `plan_handlers.py`

**Files:**
- Modify: `plan_handlers.py`

- [ ] **Step 1: Add `_build_lookup`**

```python
def _build_lookup(
    items: list[dict],
    *,
    key: str,
    value: str,
    warn=None,
) -> dict[str, str]:
    """Build hex→name dict; first-seen wins; call warn(msg) on duplicates."""
    result: dict[str, str] = {}
    for item in items:
        k = item[key]
        v = item[value]
        if k in result:
            if warn:
                warn(f"WARNING: duplicate hex {k!r} — keeping {result[k]!r}, ignoring {v!r}")
        else:
            result[k] = v
    return result
```

- [ ] **Step 2: Add `_classify_colors`**

```python
_STATUS_ORDER = {"matched": 0, "paint_style": 1, "new_candidate": 2}


def _classify_colors(
    node_colors: list[dict],
    *,
    prim_lookup: dict[str, str],
    style_lookup: dict[str, str],
    dup_prim_hexes: set[str] | None = None,
    dup_style_hexes: set[str] | None = None,
) -> list[dict]:
    dup_prim_hexes = dup_prim_hexes or set()
    dup_style_hexes = dup_style_hexes or set()
    result = []
    for color in node_colors:
        hex_ = color["hex"]
        if hex_ in prim_lookup:
            status = "matched"
            primitive_name = prim_lookup[hex_]
            paint_style_name = None
            dup = hex_ in dup_prim_hexes
        elif hex_ in style_lookup:
            status = "paint_style"
            primitive_name = None
            paint_style_name = style_lookup[hex_]
            dup = hex_ in dup_style_hexes
        else:
            status = "new_candidate"
            primitive_name = None
            paint_style_name = None
            dup = False
        result.append({
            "hex": hex_,
            "fill_count": color["fill_count"],
            "stroke_count": color["stroke_count"],
            "status": status,
            "primitive_name": primitive_name,
            "paint_style_name": paint_style_name,
            "duplicate_warning": dup,
            "examples": color["examples"],
        })
    return result
```

- [ ] **Step 3: Add `_sort_colors`**

```python
def _sort_colors(colors: list[dict]) -> list[dict]:
    return sorted(
        colors,
        key=lambda c: (
            _STATUS_ORDER[c["status"]],
            -(c["fill_count"] + c["stroke_count"]),
            c["hex"],
        ),
    )
```

- [ ] **Step 4: Run tests — expect all to pass**

```bash
python -m pytest tests/test_plan_handlers.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add plan_handlers.py
git commit -m "feat(plan): implement _build_lookup, _classify_colors, _sort_colors"
```

---

## Task 6: Implement `plan primitive-colors-from-project` command

**Files:**
- Modify: `plan_handlers.py`

- [ ] **Step 1: Add imports at the top of `plan_handlers.py`**

```python
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer

plan_app = typer.Typer(no_args_is_help=True, help="Host-side planning and proposal commands.")

_TOKENS_DIR = Path(__file__).parent / "tokens"
```

- [ ] **Step 2: Add the command**

```python
@plan_app.command("primitive-colors-from-project")
def plan_primitive_colors_from_project(
    usage: str = typer.Option(..., "--usage", help="Path to usage JSON written by `read color-usage-summary`."),
    out: str = typer.Option(
        str(_TOKENS_DIR / "primitives.proposed.json"),
        "--out",
        help="Output path for proposal (default: tokens/primitives.proposed.json).",
    ),
) -> None:
    """Classify colors from usage scan and write a primitive color proposal."""
    usage_path = Path(usage).resolve()
    if not usage_path.exists():
        raise typer.BadParameter(f"Usage file not found: {usage_path}")

    try:
        data = json.loads(usage_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise typer.BadParameter(f"Failed to read usage file: {e}")

    for key in ("node_colors", "paint_styles", "primitive_variables"):
        if key not in data:
            raise typer.BadParameter(f"Usage file missing required key: {key!r}")

    warnings: list[str] = []

    # Build lookups — track duplicate hexes for duplicate_warning flag
    prim_seen: dict[str, str] = {}
    dup_prim: set[str] = set()
    for item in data["primitive_variables"]:
        h = item["hex"]
        if h in prim_seen:
            msg = f"WARNING: duplicate hex {h!r} in primitive_variables — keeping {prim_seen[h]!r}, ignoring {item['name']!r}"
            warnings.append(msg)
            typer.echo(msg)
            dup_prim.add(h)
        else:
            prim_seen[h] = item["name"]

    style_seen: dict[str, str] = {}
    dup_style: set[str] = set()
    for item in data["paint_styles"]:
        h = item["hex"]
        if h in style_seen:
            msg = f"WARNING: duplicate hex {h!r} in paint_styles — keeping {style_seen[h]!r}, ignoring {item['name']!r}"
            warnings.append(msg)
            typer.echo(msg)
            dup_style.add(h)
        else:
            style_seen[h] = item["name"]

    classified = _classify_colors(
        data["node_colors"],
        prim_lookup=prim_seen,
        style_lookup=style_seen,
        dup_prim_hexes=dup_prim,
        dup_style_hexes=dup_style,
    )
    sorted_colors = _sort_colors(classified)

    matched = sum(1 for c in sorted_colors if c["status"] == "matched")
    paint_style_count = sum(1 for c in sorted_colors if c["status"] == "paint_style")
    new_candidates = sum(1 for c in sorted_colors if c["status"] == "new_candidate")
    unique = len(sorted_colors)

    # Console summary
    scanned_nodes = data.get("scanned_nodes", "?")
    scanned_pages = data.get("scanned_pages", "?")
    typer.echo(f"\nColor Usage Summary")
    typer.echo(f"  Scanned: {scanned_nodes} nodes across {scanned_pages} pages")
    typer.echo(f"  Unique colors: {unique}")
    typer.echo(f"  Matched to primitives: {matched}")
    typer.echo(f"  From paint styles: {paint_style_count}")
    typer.echo(f"  New candidates: {new_candidates}")
    typer.echo(f"\nTop colors by usage:")
    for c in sorted_colors[:10]:
        total = c["fill_count"] + c["stroke_count"]
        if c["status"] == "matched":
            label = f"→ {c['primitive_name']} (matched)"
        elif c["status"] == "paint_style":
            label = f"→ {c['paint_style_name']} (paint_style)"
        else:
            label = "→ NEW CANDIDATE"
        typer.echo(f"  {c['hex']}  ×{total:<5} {label}")

    # Write proposal
    out_path = Path(out).resolve()
    if out_path.exists():
        typer.echo(f"\nWARNING: overwriting existing proposal: {out_path}")

    proposal = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_usage_file": str(usage_path),
        "scanned_pages": scanned_pages,
        "scanned_nodes": scanned_nodes,
        "summary": {
            "unique_node_colors": unique,
            "matched_to_primitives": matched,
            "from_paint_styles": paint_style_count,
            "new_candidates": new_candidates,
        },
        "colors": sorted_colors,
    }

    out_path.write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"\nProposal written to: {out_path}")
```

- [ ] **Step 2: Verify the command appears in help**

```bash
python run.py plan --help
```

Expected:
```
Commands:
  primitive-colors-from-project  Classify colors from usage scan and write...
```

- [ ] **Step 3: Commit**

```bash
git add plan_handlers.py
git commit -m "feat(plan): implement primitive-colors-from-project command"
```

---

## Task 7: Integration test for `plan primitive-colors-from-project`

**Files:**
- Modify: `tests/test_plan_handlers.py`

Tests the full command via Typer's `CliRunner`, using a synthetic usage file. No Figma connection needed.

- [ ] **Step 1: Add integration tests**

```python
import json
from pathlib import Path
from typer.testing import CliRunner
from plan_handlers import plan_app

runner = CliRunner()

_USAGE = {
    "scanned_pages": 2,
    "scanned_nodes": 100,
    "totals": {"unique_node_colors": 3, "paint_style_colors": 1, "primitive_variable_colors": 1},
    "node_colors": [
        {"hex": "#ffffff", "fill_count": 50, "stroke_count": 0, "examples": [{"page": "P", "node": "N"}]},
        {"hex": "#3b82f6", "fill_count": 10, "stroke_count": 2, "examples": [{"page": "P", "node": "N2"}]},
        {"hex": "#ef4444", "fill_count": 5, "stroke_count": 0, "examples": [{"page": "P", "node": "N3"}]},
    ],
    "paint_styles": [{"name": "brand/primary", "hex": "#3b82f6", "style_id": "S:1"}],
    "primitive_variables": [{"name": "color/base/white", "hex": "#ffffff"}],
}


def test_command_writes_proposal(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"

    result = runner.invoke(plan_app, [
        "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    assert result.exit_code == 0, result.output
    assert out_file.exists()
    proposal = json.loads(out_file.read_text())
    assert proposal["summary"]["unique_node_colors"] == 3
    assert proposal["summary"]["matched_to_primitives"] == 1
    assert proposal["summary"]["from_paint_styles"] == 1
    assert proposal["summary"]["new_candidates"] == 1


def test_command_sort_order_in_proposal(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"

    runner.invoke(plan_app, [
        "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    proposal = json.loads(out_file.read_text())
    statuses = [c["status"] for c in proposal["colors"]]
    assert statuses == ["matched", "paint_style", "new_candidate"]


def test_command_does_not_touch_primitives_json(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    primitives = tmp_path / "primitives.json"
    primitives.write_text('{"color":{}}', encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"

    runner.invoke(plan_app, [
        "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    assert primitives.read_text() == '{"color":{}}'


def test_command_missing_usage_file(tmp_path):
    result = runner.invoke(plan_app, [
        "primitive-colors-from-project",
        "--usage", str(tmp_path / "nonexistent.json"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_command_malformed_usage_file(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text('{"bad": true}', encoding="utf-8")
    result = runner.invoke(plan_app, [
        "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_command_warns_on_overwrite(tmp_path):
    usage_file = tmp_path / "usage.json"
    usage_file.write_text(json.dumps(_USAGE), encoding="utf-8")
    out_file = tmp_path / "primitives.proposed.json"
    out_file.write_text("old content", encoding="utf-8")

    result = runner.invoke(plan_app, [
        "primitive-colors-from-project",
        "--usage", str(usage_file),
        "--out", str(out_file),
    ])

    assert "WARNING: overwriting" in result.output
    proposal = json.loads(out_file.read_text())
    assert "summary" in proposal
```

- [ ] **Step 2: Run all tests**

```bash
python -m pytest tests/test_plan_handlers.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Run full test suite to check for regressions**

```bash
python -m pytest tests/ -v
```

Expected: all existing tests continue to pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_plan_handlers.py
git commit -m "test(plan): add integration tests for primitive-colors-from-project"
```

---

## Verification Checklist

Run after all tasks complete:

```bash
# Full test suite
python -m pytest tests/ -v

# Help smoke tests
python run.py read --help          # color-usage-summary appears
python run.py plan --help          # primitive-colors-from-project appears

# End-to-end (requires live Figma file + FIGMA_FILE_URL set):
python run.py read color-usage-summary --out /tmp/usage.json
python run.py plan primitive-colors-from-project --usage /tmp/usage.json

# Manual checks on /tmp/usage.json:
#   - scanned_pages, scanned_nodes present
#   - node_colors entries have hex, fill_count, stroke_count, examples (≤3)
#   - paint_styles entries have name, hex, style_id
#   - primitive_variables entries have name, hex
#
# Manual checks on tokens/primitives.proposed.json:
#   - file exists; tokens/primitives.json unchanged
#   - colors sorted: matched → paint_style → new_candidate
#   - within group: higher usage first, hex ASC on tie
#   - matched entries have primitive_name populated, paint_style_name null
#   - new_candidate entries have both name fields null
#   - generated_at and source_usage_file fields present
```
