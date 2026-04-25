# Design: `plan suggest-semantic-tokens` (MVP)

**Date:** 2026-04-25
**Status:** Approved for implementation
**Scope:** Suggestion-only command — never writes `semantics.seed.json`

---

## Problem

The `plan semantic-tokens-normalized` command validates and normalizes a hand-authored seed file. It gives no assistance in writing that seed. On a new palette the user must manually inspect `primitives.normalized.json` and guess which primitive fits which semantic role. This is error-prone and slow.

A suggestion command reads the existing primitives and proposes a starting mapping — one the user reviews and selectively copies into the seed. Manual control is preserved; the command is read-only assistance.

---

## Constraints

- Never writes `semantics.seed.json` — seed remains the only hand-edited semantic file.
- Never writes `semantics.normalized.json`.
- `--out` writes only `tokens/semantics.suggested.json` (a separate, read-only-by-convention file).
- No Figma sync. No component layer. No auto-apply flag.
- Output must be useful on palettes as small as 2–3 primitives.

---

## Role & State Enums

These replace the existing `SEMANTIC_ROLES` and `SEMANTIC_STATES` frozensets in `plan_colors.py`.

### Roles

| Role | Meaning |
|------|---------|
| `text` | Foreground text, labels |
| `icon` | Icon fill (manual seed only — no heuristic) |
| `border` | Strokes, dividers |
| `surface` | Cards, panels, inputs |
| `canvas` | App / page base background |
| `accent` | Highlighted BG / selected state (suggested only if saturated primitive exists) |

Deferred (not in enum yet): `overlay`, `brand`.

### States

| State | Use |
|-------|-----|
| `primary` | Core value for the role |
| `secondary` | Softer variant |
| `disabled` | Non-interactive |

Deferred (not in enum yet): `hover`, `active`, `focus`, `muted`.

```python
SEMANTIC_ROLES = frozenset({
    "text", "icon", "border", "surface", "canvas", "accent",
})
SEMANTIC_STATES = frozenset({
    "primary", "secondary", "disabled",
})
```

---

## Heuristic Rules

Primitives are sorted lightest → darkest by luminance derived from hex. Rules are applied to that sorted list. A primitive may appear in multiple suggestions; the user resolves conflicts manually.

| # | Input condition | Assigns | Reason label |
|---|----------------|---------|-------------|
| 1 | Darkest primitive | `color/text/primary` | `darkest primitive` |
| 2 | Second-darkest (if distinct from #1) | `color/text/secondary` | `dark scale entry` |
| 3 | Slightly lighter than `text/primary` (next step up, not mid-scale) | `color/text/disabled` | `lighter than primary → disabled` |
| 4 | Mid-scale primitive | `color/border/primary` | `mid-scale entry` |
| 5 | Second-lightest (distinct from lightest) | `color/surface/primary` | `near-lightest entry` |
| 6 | Lightest primitive | `color/canvas/primary` | `lightest primitive` |
| 7 | Saturated primitive (S > 40%) | `color/accent/primary` | `saturated — accent candidate` |

### Canvas vs. Surface disambiguation

- `canvas/primary` always takes the **lightest** primitive.
- `surface/primary` takes the **next lightest** — only if it is a **distinct primitive** from canvas.
- If the palette has only one light primitive (e.g. only `gray/100`), `surface/primary` is skipped with a note. Both roles are never assigned to the same primitive on palettes with ≥ 2 primitives.

### Disabled rule

`text/disabled` is assigned to the primitive **one step lighter than `text/primary`** in the sorted list (i.e. the second-darkest), not the mid-scale value. Rationale: disabled text is a de-emphasized variant of body text, not a border-range value. On a 3-color palette this means `text/secondary` and `text/disabled` may land on the same primitive — both suggestions are emitted and the user decides.

### Icon role

No heuristic emits `icon/*`. The role exists in the enum for manual seed use. The suggestion command never suggests it — icon color is design-specific and not derivable from lightness alone.

### Accent role

Only suggested when a clearly saturated primitive (S > 40%) is present. On gray-only palettes the role is omitted entirely from output with a one-line note.

### Small palette behavior

| Palette size | Behavior |
|-------------|----------|
| 1 primitive | Only rules 1 and 6 fire (same primitive for both) |
| 2 primitives | Rules 1, 4, 6 fire; canvas/surface disambiguated only if distinct |
| 3 primitives | All rules fire where candidates are distinct; skips noted explicitly |
| 4+ primitives | Full suggestion set possible |

Every skipped rule prints a one-line note in stdout. No silent omissions.

---

## Input / Output Files

| Direction | File | Notes |
|-----------|------|-------|
| Input (required) | `tokens/primitives.normalized.json` | Errors clearly if missing |
| Input (optional) | `tokens/semantics.seed.json` | When present, covered names are marked `[covered]` in stdout and excluded from `--out` file |
| Output (optional) | `tokens/semantics.suggested.json` | Written only with `--out` flag. Same flat `semantic_name → primitive_name` shape as seed. Read-only by convention. |

---

## CLI Interface

```
plan suggest-semantic-tokens [OPTIONS]

Options:
  --primitives PATH   Path to primitives.normalized.json
                      [default: tokens/primitives.normalized.json]
  --seed PATH         Path to semantics.seed.json (optional coverage check)
                      [default: tokens/semantics.seed.json]
  --out PATH          Write suggestions to this file (optional)
                      [default: none — stdout only]
```

No `--accept`, `--apply`, or any flag that writes seed.

---

## Output Format

### Stdout (always)

```
Semantic token suggestions  (3 primitives → 5 suggestions)

  semantic name          primitive        reason                      covered?
  ──────────────────────────────────────────────────────────────────────────────
  color/text/primary     color/gray/900   darkest primitive           [covered]
  color/text/disabled    color/gray/500   lighter than primary → disabled
  color/border/primary   color/gray/500   mid-scale entry
  color/surface/primary  color/gray/100   near-lightest entry
  color/canvas/primary   color/gray/100   lightest primitive

5 suggestions  (1 already covered in seed)
Note: no saturated primitives — color/accent skipped.
Note: only 3 primitives — color/text/secondary skipped (needs distinct dark entry).
To write: plan suggest-semantic-tokens --out tokens/semantics.suggested.json
```

### `semantics.suggested.json` (with `--out`)

Flat `semantic_name → primitive_name` map. Same shape as seed. Covered entries excluded. Sorted by key. Atomic write, trailing newline.

```json
{
  "color/border/primary":  "color/gray/500",
  "color/canvas/primary":  "color/gray/100",
  "color/surface/primary": "color/gray/100",
  "color/text/disabled":   "color/gray/500"
}
```

When two rules produce the same semantic name, the lower rule number wins in `--out`. Both appear in stdout.

---

## Migration Prerequisite

The existing `semantics.seed.json` uses `default` as the state for all 5 entries. Once `SEMANTIC_STATES` is updated to remove `default`, the normalize command will hard-fail on the current seed. Before any code change lands, the seed must be updated: all `default` states renamed to `primary`. This is a 5-line file edit and must be the **first step** in the implementation plan.

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| `default` → `primary` rename breaks existing `semantics.seed.json` | Medium | Named as mandatory first step in impl plan; normalize guards with clear error |
| Small palette maps multiple roles to same primitive | Low | Expected and correct; user adds primitives or overrides manually |
| `surface` and `canvas` both assigned to `gray/100` on 3-color palette | Low | Canvas/surface rule explicitly prevents this when ≥ 2 distinct light primitives exist; skip note printed otherwise |
| `text/secondary` and `text/disabled` land on same primitive | Low | Both emitted; user decides which to keep |
| `icon` role missing from suggestions confuses users | Low | Stdout footer explains: "icon/* requires manual seed entry" |
| `semantics.suggested.json` mistaken for seed | Low | File named distinctly; doc marks it read-only; normalize never reads it |
| Scope creep into auto-applying suggestions | Medium | No `--accept` flag; seed is never written by this command under any path |

---

## Out of Scope (This Step)

- `overlay`, `brand` roles
- `hover`, `active`, `focus`, `muted` states
- Saturation heuristics beyond the single accent rule
- Conflict resolution UI beyond "first rule wins in `--out`"
- Pipeline script integration
- Figma sync of semantic tokens
