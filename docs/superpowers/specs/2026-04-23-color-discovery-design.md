# Color Discovery Design

**Date:** 2026-04-23  
**Status:** Approved  
**Scope:** Block 1 — read_color_usage_summary + plan_primitive_colors_from_project  
**Goal:** Discover what colors are actually used in a Figma project and propose a primitive palette. No Figma writes at this stage.

---

## Context

`sync_primitive_colors` already seeds Figma color variables from `tokens/primitives.json`. Before expanding sync to new tokens, we need a discovery phase: scan the live Figma file, find all colors in actual use, compare against existing primitives, and propose candidates.

Long-term target flow: **Figma project → analyze → propose primitives → validate → sync.**  
This spec covers the first two steps only: analyze and propose.

---

## Two Commands

### Command 1: `read color-usage-summary`

**Type:** `read_*` — read-only, produces an intermediate file  
**Figma round-trip:** Yes (JS via Scripter bridge)  
**Output:** JSON file at path given by `--out`

### Command 2: `plan primitive-colors-from-project`

**Type:** `plan_*` — host-side only, no Figma round-trip  
**CLI:** `python run.py plan primitive-colors-from-project`  
**Input:** JSON file produced by command 1  
**Output:** Console summary + `tokens/primitives.proposed.json`

---

## Files Added / Modified

| Path | Role |
|------|------|
| `scripts/variables/read_color_usage_summary.js` | Figma Plugin API scan script (new) |
| `read_handlers.py` | `read color-usage-summary` bridge handler (new command) |
| `plan_handlers.py` | `plan primitive-colors-from-project` host-side planner (new file) |
| `run.py` | Mount `plan_app` as `plan` sub-app (one line) |

No new JS for the plan step.

---

## Command 1 — `read color-usage-summary`

### CLI contract

```
python run.py read color-usage-summary --out <path> [--timeout N] [--mount-timeout N] [-f <url>] [--quiet]
```

`--out` is **required** (payload reliably exceeds inline cap for real files).  
All other flags match existing `read_*` commands exactly.

### JS script: `read_color_usage_summary.js`

Runs inside the Figma Plugin API sandbox. Read-only — no variable or style writes.

**Scan sources (in priority order):**

1. **Node fills/strokes** (main signal) — `figma.root.findAll()` across all pages. For each node: inspect `fills` and `strokes` arrays. Keep only `type === "SOLID"` paints where `visible !== false`. Record hex + fill_count + stroke_count + up to 3 examples.
2. **Paint styles** (formalized signal) — `figma.getLocalPaintStyles()`. For each style: extract first SOLID paint only; skip styles with no solid paint silently.
3. **Primitive variables** (reference context only) — `figma.variables.getLocalVariableCollections()`, find "primitives" collection, read all `COLOR` variables. Not counted as usage — returned as a lookup reference.

**Hex normalization (locked):** All RGB floats (0–1) converted to `#rrggbb` lowercase. Alpha ignored (solid fills only, a=1 always). Conversion: `channel * 255`, round, zero-pad to 2 hex digits.

**Exclusions (locked for v1):** No gradients, no image paints, no effect colors, no opacity-variant merging, no hidden nodes (visible=false fills skipped).

**Examples per color:** Up to 3, first-seen during walk. Each example: `{ page: string, node: string }` — names only, no ids or geometry.

**`unique_node_colors` definition:** Count of distinct hex values seen across node fills and strokes. Paint styles and primitive variables are NOT counted here.

### JS return shape

```json
{
  "scanned_pages": 2,
  "scanned_nodes": 847,
  "totals": {
    "unique_node_colors": 12,
    "paint_style_colors": 5,
    "primitive_variable_colors": 21
  },
  "node_colors": [
    {
      "hex": "#3b82f6",
      "fill_count": 18,
      "stroke_count": 5,
      "examples": [
        { "page": "Components", "node": "Button/Primary" },
        { "page": "Components", "node": "Badge/Info" },
        { "page": "Onboarding", "node": "Hero/Background" }
      ]
    }
  ],
  "paint_styles": [
    { "name": "brand/primary", "hex": "#3b82f6", "style_id": "S:abc123" }
  ],
  "primitive_variables": [
    { "name": "color/blue/500", "hex": "#3b82f6" }
  ]
}
```

### Python handler

Registered in `read_handlers.py` as `@read_app.command("color-usage-summary")`.  
Follows the existing `_dispatch_read()` pattern exactly — reads JS from `scripts/variables/read_color_usage_summary.js`, no template substitution needed (no injected tokens), dispatches with `--out` required.

---

## Command 2 — `plan primitive-colors-from-project`

### CLI contract

```
python run.py plan primitive-colors-from-project --usage <path> [--out <proposal_path>]
```

`--usage` is **required** — path to the JSON file written by `read color-usage-summary`.  
`--out` is **optional** — defaults to `tokens/primitives.proposed.json` relative to the project root (same directory as `primitives.json`). Never writes to `primitives.json`.

Lives in new `plan_handlers.py`, registered as `@plan_app.command("primitive-colors-from-project")`.  
`plan_app` is a `typer.Typer` mounted in `run.py` as `app.add_typer(plan_app, name="plan")`.  
Does NOT call `_dispatch_read()` or `_dispatch_sync()` — runs entirely host-side.

### Processing steps

1. **Load & validate usage file** — check top-level keys (`node_colors`, `paint_styles`, `primitive_variables`). Fail fast with a clear `typer.BadParameter` if file missing or malformed.
2. **Build primitive lookup** — `dict[hex → name]` from `primitive_variables`. Hex normalization: lowercase (already normalized by JS).
3. **Build paint style lookup** — `dict[hex → name]` from `paint_styles`.
4. **Duplicate handling (locked):** If a hex maps to more than one primitive name or style name, first-seen wins. Print a warning line to console. Set `"duplicate_warning": true` on that entry in the proposal.
5. **Classify each node color:**
   - hex in primitive lookup → `status: "matched"`, record `primitive_name`
   - hex in paint style lookup (and not matched) → `status: "paint_style"`, record `paint_style_name`
   - otherwise → `status: "new_candidate"`
6. **Sort (locked):** Status group order: `matched` → `paint_style` → `new_candidate`. Within group: total usage (`fill_count + stroke_count`) DESC. Tie-break: hex ASC.
7. **Print console summary.**
8. **Write proposal file.** If file already exists: overwrite with a warning line to console (no prompt, no abort).

### Console output format

```
Color Usage Summary
  Scanned: 847 nodes across 2 pages
  Unique colors: 12
  Matched to primitives: 4
  From paint styles: 3
  New candidates: 5

Top colors by usage:
  #ffffff  ×104  → color/base/white (matched)
  #3b82f6   ×23  → brand/primary (paint_style)
  #ef4444   ×11  → NEW CANDIDATE
  ...

Proposal written to: tokens/primitives.proposed.json
```

### Proposal file shape

Written to `tokens/primitives.proposed.json`. Never touches `primitives.json`.

```json
{
  "generated_at": "2026-04-23T10:00:00Z",
  "source_usage_file": "/absolute/path/to/usage.json",
  "scanned_pages": 2,
  "scanned_nodes": 847,
  "summary": {
    "unique_node_colors": 12,
    "matched_to_primitives": 4,
    "from_paint_styles": 3,
    "new_candidates": 5
  },
  "colors": [
    {
      "hex": "#ffffff",
      "fill_count": 104,
      "stroke_count": 0,
      "status": "matched",
      "primitive_name": "color/base/white",
      "paint_style_name": null,
      "duplicate_warning": false,
      "examples": [
        { "page": "Components", "node": "Frame 1" }
      ]
    },
    {
      "hex": "#3b82f6",
      "fill_count": 18,
      "stroke_count": 5,
      "status": "paint_style",
      "primitive_name": null,
      "paint_style_name": "brand/primary",
      "duplicate_warning": false,
      "examples": [
        { "page": "Components", "node": "Button/Primary" }
      ]
    },
    {
      "hex": "#ef4444",
      "fill_count": 11,
      "stroke_count": 0,
      "status": "new_candidate",
      "primitive_name": null,
      "paint_style_name": null,
      "duplicate_warning": false,
      "examples": [
        { "page": "Onboarding", "node": "Error/Banner" }
      ]
    }
  ]
}
```

---

## What This Does NOT Do

- No writes to Figma (no variables created, no styles modified)
- No writes to `tokens/primitives.json`
- No sync, no dry-run sync
- No gradient, effect, image paint, or opacity-variant analysis
- No semantic token proposal
- No automatic naming of new candidates (naming is a human decision)

---

## Verification

```bash
# Step 1: scan
python run.py read color-usage-summary --out /tmp/usage.json

# Step 2: plan
python run.py plan primitive-colors-from-project --usage /tmp/usage.json

# Verify:
# - /tmp/usage.json exists and matches the JS return shape above
# - tokens/primitives.proposed.json exists and is NOT primitives.json
# - Console prints summary with correct counts
# - matched entries have primitive_name populated
# - new_candidate entries have both name fields null
# - sort order: matched first, then paint_style, then new_candidate
# - within group: higher usage first, hex ASC on tie
```
