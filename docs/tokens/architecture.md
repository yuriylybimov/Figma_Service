# Token Architecture

This file is the authoritative specification for the Figma design token system.
All code, commands, and token files must conform to these rules.
If a rule here conflicts with anything else, this file wins.

---

## Token Layers

The system uses three strictly ordered layers. Each layer may only reference the layer directly below it.

```
primitives  →  semantic  →  component
```

| Layer | Contains | Values | May alias |
|---|---|---|---|
| **Primitive** | Raw color values | Hex strings | Nothing — raw only |
| **Semantic** | Intent-named tokens | — | Primitives only |
| **Component** | Component-scoped tokens | — | Semantic only |

**Violations:**
- A semantic token that stores a raw hex (not an alias) is invalid.
- A component token that aliases a primitive directly is invalid.
- No layer may alias itself or a higher layer.

---

## Naming Rules

### General format

```
color/<group>/<scale>
```

All token names must:
- Start with `color/`
- Use lowercase letters, digits, and `/` only
- Never end with `/`
- Never use `color/candidate/` as a final name (candidate names are temporary placeholders only)

### Fixed colors

These two hexes have fixed, immutable names. They are **not** part of any scale group.

| Hex | Name |
|---|---|
| `#ffffff` | `color/white` |
| `#000000` | `color/black` |

These names must not be auto-generated, overridden, or reassigned. White and black are excluded from gray-scale classification.

### Primitive auto-naming

Auto-names are assigned deterministically based on HSL classification:

**Step 1 — classify group**

Saturation threshold for gray: `< 0.12` (HSL saturation, 0–1 scale).

| Hue range (0–1) | Group |
|---|---|
| 0.00 – 0.05 | `red` |
| 0.05 – 0.11 | `orange` |
| 0.11 – 0.20 | `yellow` |
| 0.20 – 0.46 | `green` |
| 0.46 – 0.52 | `cyan` |
| 0.52 – 0.69 | `blue` |
| 0.69 – 0.79 | `violet` |
| 0.79 – 0.86 | `purple` |
| 0.86 – 0.95 | `pink` |
| 0.95 – 1.00 | `red` (hue wrap-around) |
| saturation < 0.12 | `gray` (regardless of hue) |

**Step 2 — assign scale**

Scale slots: `100 200 300 400 500 600 700 800 900`

- Lighter colors get lower scale numbers.
- With fewer than 9 colors in a group, slots are distributed evenly across the 9-point range.
- A single color in a group gets scale `500`.
- Scale assignment is stable: same input always produces same output.

**Resulting name:** `color/<group>/<scale>` — e.g. `color/gray/300`, `color/blue/500`.

### Candidate names (temporary)

During discovery, colors not yet matched to a primitive are assigned a placeholder:

```
color/candidate/<hex-without-hash>
```

Example: `color/candidate/1a2b3c`

Candidate names must never appear in a final sync. They are resolved to `final_name` before any write to Figma.

---

## Color Classification (Discovery)

When scanning a Figma file, each hex is classified into one of three statuses:

| Status | Condition | Action |
|---|---|---|
| `matched` | Hex exists in current primitive variables | Use existing primitive name |
| `paint_style` | Hex exists in paint styles but not primitives | Use paint style name |
| `new_candidate` | Hex not found in either | Assign candidate name; queue for normalization |

Sort order for proposals: `matched` → `paint_style` → `new_candidate`, then by descending use count, then hex.

Duplicate hexes within a source (primitive_variables or paint_styles) emit a warning; first-seen wins.

---

## Pipeline

```
read color-usage-summary
        ↓
plan primitive-colors-from-project   → tokens/primitives.proposed.json
        ↓
read color-usage-detail              → usage_detail.json
        ↓
plan cleanup-candidates              → tokens/primitives.cleanup.json
        ↓
plan deduplicate-primitives          → tokens/primitives.dedup.json
        ↓
[human review + override set]
        ↓
plan primitive-colors-normalized     → tokens/primitives.normalized.json
        ↓
plan validate-normalized             (exits non-zero on any error)
        ↓
sync primitive-colors                → Figma
```

No step may be skipped. Sync must not run if validate-normalized exits non-zero.

---

## Cleanup Rules

### Low-use filter (`plan cleanup-candidates`)

- Default threshold: `use_count < 3` → tagged `review_low_use`
- `use_count >= threshold` → tagged `keep`
- Threshold is a CLI flag (`--threshold`), not a hardcoded constant.
- Output is a **proposal only** — never auto-applied.
- Tag `review_low_use` means "human should review", not "must remove".

### Near-duplicate detection (`plan deduplicate-primitives`)

- Distance metric: weighted HSL delta — lightness ×0.5, saturation ×0.3, hue ×0.2 (hue is circular).
- Default threshold: `0.01` (on a 0–1 scale).
- Grouping algorithm: single-linkage (union-find).
- Canonical hex per group: highest `use_count`; tie-broken by hex string (lexicographic max).
- `recommendation: "keep"` — singleton group, no action needed.
- `recommendation: "merge"` — human should pick canonical and set override.
- Output is a **proposal only** — never auto-applied. Never modifies Figma.

---

## Override Rules

Overrides are stored in `tokens/overrides.normalized.json` as a flat `hex → final_name` map:

```json
{
  "#1a2b3c": "color/brand/navy",
  "#ffffff": "color/white"
}
```

### Validation rules for `final_name`

- Must start with `color/`
- Must **not** start with `color/candidate/`
- Must be unique across all entries (no two hexes map to the same final_name)
- Hex key must match `#[0-9a-fA-F]{6}` exactly

### Override precedence

- An override always wins over an auto-generated name.
- Auto-names are re-generated on every normalize run; overrides are stable.
- A missing override file is treated as an empty override map (not an error).
- Overrides are written atomically (temp file + rename). Partial writes are not possible.
- The file is always written sorted by hex key for stable diffs.

### Override commands

| Command | Effect |
|---|---|
| `override set <hex> <final_name>` | Upsert. Validates both inputs before writing. |
| `override list` | Print current map; "No overrides set." if empty. |

---

## Validation Rules (`plan validate-normalized`)

Required fields on each normalized entry: `hex`, `candidate_name`, `auto_name`, `final_name`.

Errors that cause non-zero exit:
1. Any required field is missing.
2. `hex` does not match `#[0-9a-fA-F]{6}`.
3. `final_name` does not start with `color/`.
4. `final_name` starts with `color/candidate/`.
5. `final_name` is duplicated across entries.

Validation must run and pass before any sync command is allowed to proceed.

---

## Sync Safety Rules

1. **Validate first.** `validate_runtime_context` runs before every sync and aborts on failure.
2. **Never delete.** Existing Figma variables are never deleted during sync. Only create and rename.
3. **Dry-run required.** Every sync command must support `--dry-run`. Dry-run logs `created / updated / skipped` without writing to Figma.
4. **Idempotent.** Running sync twice with the same input must produce the same result.
5. **No raw hex in semantic layer.** Semantic token sync must use Figma VariableAlias values, not raw hex. If the aliased primitive does not exist in Figma at sync time, the command must fail with a clear error.
6. **Sync order.** Primitives must be synced before semantics. Semantics must be synced before components.
7. **No auto-apply.** Cleanup and dedup proposals are never applied automatically. A human must review and confirm via `override set` before normalize and sync run.

---

## Token Files

| File | Role | Written by |
|---|---|---|
| `tokens/primitives.json` | Source-of-truth primitive variables (existing Figma state) | Manual / Figma export |
| `tokens/primitives.proposed.json` | Discovery output — all colors found in file | `plan primitive-colors-from-project` |
| `tokens/primitives.cleanup.json` | Low-use filter proposal | `plan cleanup-candidates` |
| `tokens/primitives.dedup.json` | Near-duplicate grouping proposal | `plan deduplicate-primitives` |
| `tokens/primitives.normalized.json` | Final names ready for sync | `plan primitive-colors-normalized` |
| `tokens/overrides.normalized.json` | Human-managed hex → final_name map | `override set` |

All files are JSON, UTF-8, LF line endings, 2-space indent, trailing newline.
Files tagged "proposal" are read-only inputs to the next stage. Never hand-edit them; re-run the command instead.
`overrides.normalized.json` is the only file intended for human (or CLI) editing.
