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

## Semantic Tokens

Semantic tokens are intent-named aliases pointing to primitives (e.g. `color/text/primary → color/gray/900`). They live one layer above primitives and may **only** alias primitives — never raw hex, never other semantics.

### Naming format

```
color/<role>/<state>
```

Strict enums (a name with any value outside these sets is invalid):

| Field | Allowed values |
|---|---|
| `role` | `text`, `surface`, `border`, `canvas`, `icon`, `accent` |
| `state` | `primary`, `secondary`, `disabled` |

Examples: `color/text/primary`, `color/surface/secondary`, `color/border/disabled`.

**Auto-suggestion scope.** `plan semantic-tokens-normalized` auto-generates suggestions only for `text/*`, `surface/*`, `border/*`, and `canvas/*`. The `icon` and `accent` roles are reserved — they are never auto-generated and must be provided explicitly via seed or override.

**Luminance-driven mapping.** Semantic suggestions are determined by computed luminance from the primitive hex value, not by scale name. `gray/400` can win over `gray/500` if its luminance is closer to the target. Do not assume scale numbers proxy luminance.

**Light theme only.** The semantic mapping system currently assumes a light theme (light = canvas, dark = text). Theme-aware or dark-mode mapping is not implemented.

### Files

| File | Role | Editable |
|---|---|---|
| `tokens/semantics.seed.json` | Hand-authored seed: flat `semantic_name → primitive_name` map | Yes (only semantic file you edit by hand) |
| `tokens/overrides.semantic.normalized.json` | Hand-authored overrides: same flat shape, applied on top of the seed | Yes |
| `tokens/semantics.normalized.json` | Pipeline output: identical flat shape, overrides resolved | **No** — re-run the command |

All three files are flat JSON objects of the form:

```json
{
  "color/text/primary":    "color/gray/900",
  "color/text/disabled":   "color/gray/700",
  "color/canvas/primary":  "color/gray/50"
}
```

Override precedence: an override entry replaces the seed entry for the same key. A missing override file is treated as an empty map.

### Pipeline

```
tokens/semantics.seed.json
tokens/overrides.semantic.normalized.json   ─┐
tokens/primitives.normalized.json            │
                                              ▼
                       plan semantic-tokens-normalized
                       (resolve overrides + validate inline; fail fast)
                                              ↓
                       tokens/semantics.normalized.json
```

Primitive normalize+validate must succeed before semantic normalize runs (semantics resolve aliases against the primitive output).

### Validation rules (run inline by `plan semantic-tokens-normalized`)

The command fails fast on the first violation, exits non-zero, and writes nothing.

1. Each key matches `color/<role>/<state>` with role ∈ role enum and state ∈ state enum.
2. Each value starts with `color/` and is **not** a `color/candidate/...` placeholder.
3. Each value exists as a `final_name` in `tokens/primitives.normalized.json`.
4. No value is a raw hex (e.g. `#1a2b3c`) — semantics may not store raw values.
5. No value is itself a semantic name from the resolved map (no semantic-to-semantic aliasing).
6. Names are unique (enforced by JSON object semantics; duplicate keys are a parse error).

### Context-Aware Semantic Suggestions

The system may generate semantic token suggestions informed by actual color usage
context from the Figma file. These suggestions are governed by strict guardrails.

#### Proposal-only

- Context-aware suggestions are **never written directly to `tokens/semantics.seed.json`**.
- They are written to a separate file: `tokens/semantics.contextual.json`.
- A human must review each suggestion and manually copy confirmed entries into
  `tokens/semantics.seed.json`.
- `plan semantic-tokens-normalized` remains the only command that writes
  `tokens/semantics.normalized.json`.

#### Required suggestion fields

Every suggestion in `tokens/semantics.contextual.json` must include:

| Field | Type | Description |
|---|---|---|
| `semantic_name` | string | e.g. `color/border/primary` |
| `primitive_name` | string | Alias target; must exist in `primitives.normalized.json` |
| `confidence` | `"high"` / `"medium"` / `"low"` | See confidence rules below |
| `reason` | string | Plain-language explanation of why this role was inferred |
| `usage_examples` | array | Up to 5 sample nodes from Figma with name, type, role, page |
| `warnings` | array | Non-empty when the same color plays multiple roles or signals conflict |

Suggestions without all six fields are invalid and must not be written.

#### Confidence rules

Confidence is **not** a single-signal score. It must be downgraded when any of
the following conditions apply:

- The suggestion is based on `dominant_role` alone with no supporting context
- The only node names are generic: `Frame`, `Group`, `Container`, `Rectangle`,
  `Layer`, or any unnamed node (`""`)
- The color appears in multiple distinct roles (e.g., both text and stroke)
- The usage count is below 10
- All sample nodes come from a single component or a single page

Generic node names may be included as evidence in `usage_examples`, but they
must not be the sole basis for `confidence: "high"`. High confidence requires
at least one of: a semantically named node (e.g. `left navigation`, `search bar`),
a meaningful component name, or an unambiguous fill/stroke/text split.

#### Multi-signal requirement

A suggestion's role inference must consider all available signals together:

- Fill / stroke / text_fill distribution
- Node type (`TEXT`, `FRAME`, `RECTANGLE`, etc.)
- Parent frame name
- Component name (if node is an INSTANCE)
- Usage frequency
- Existing style or variable binding (if available)

`dominant_role` alone is insufficient to assign a semantic role.

**Canvas vs. surface disambiguation** (when fill is dominant and luminance > 0.92):
- If any `parent_frame_name` contains `"dashboard"` or `"page"` → prefer `canvas/*`
- If any `component_name` contains `"card"` or `"modal"` → prefer `surface/*`
- Otherwise fall back to luminance: ≥ 0.97 → `canvas/*`, else `surface/*`

**Multi-role warning threshold:**
A warning is added only when the second-strongest role count is ≥ 30% of the
dominant role count. Incidental secondary uses below that threshold do not warn.

Example: dominant stroke = 100, fill = 35 (35%) → warn. Fill = 20 (20%) → no warn.

#### Alias constraints

All constraints from the main Semantic Tokens section apply:
- `primitive_name` must exist in `primitives.normalized.json`
- `primitive_name` must not be a raw hex or a semantic name
- `semantic_name` must match `color/<role>/<state>` with valid role and state enums

#### Files

| File | Role | Written by |
|---|---|---|
| `tokens/color_usage_context.json` | Per-color enriched usage data from Figma | `read color-usage-context` |
| `tokens/semantics.contextual.json` | Contextual suggestion proposals | `plan suggest-semantic-tokens-contextual` |

---

### Sync

Semantic sync is **out of scope for this step**. Only primitive sync (`sync primitive-colors-normalized`) writes to Figma today. When semantic sync lands, it must follow the rules in [Sync Safety Rules](#sync-safety-rules) — VariableAlias values only, no raw hex, primitives synced first, dry-run support.

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
| `tokens/semantics.seed.json` | Hand-authored semantic_name → primitive_name map | Manual |
| `tokens/overrides.semantic.normalized.json` | Hand-authored semantic_name → primitive_name override map | Manual |
| `tokens/semantics.normalized.json` | Final semantic aliases ready for sync | `plan semantic-tokens-normalized` |

All files are JSON, UTF-8, LF line endings, 2-space indent, trailing newline.
Files tagged "proposal" are read-only inputs to the next stage. Never hand-edit them; re-run the command instead.
`overrides.normalized.json` is the only file intended for human (or CLI) editing.
