# Figma Variables Architecture

## Token Layers

```
primitives/     Raw values: hex colors, px numbers, ms durations
  └── semantic/     Aliases → primitive keys
        └── component/   Aliases → semantic keys
```

## Naming Conventions

| Layer | Pattern | Example |
|---|---|---|
| Primitive | `{category}/{scale}` | `color/grey/100`, `size/4`, `radius/sm` |
| Semantic | `{category}/{role}/{state}` | `color/surface/default`, `color/text/disabled` |
| Component | `{component}/{slot}/{state}` | `button/bg/default`, `input/border/focus` |

Rules:
- Lowercase, slash-separated, no spaces
- State suffix always last: `default`, `hover`, `focus`, `disabled`, `active`
- Scale always numeric for primitives (`/100`, `/200`)
- No cross-layer jumps: component → semantic only, semantic → primitive only

## Matching & Mapping

| Source | Target | Rule |
|---|---|---|
| Primitive key | Semantic alias | Exact match required |
| Semantic key | Component alias | Exact match required |
| Missing key | — | UNRESOLVED — block write |
| Ambiguous match | — | AMBIGUOUS — require manual override |

## Confidence Rules

| Score | Action |
|---|---|
| 1.0 | Auto-apply |
| 0.8–0.99 | Log warning, apply |
| 0.5–0.79 | Require `--force` |
| < 0.5 | Block; surface candidates |

## State Files

```
state/
  collections.json          block 1
  primitives_registry.json  block 1
  validation_report.json    block 2
  semantics_registry.json   block 3
  style_bindings.json       block 4
  ux_review_report.json     block 5
  dry_run_report.json       block 5 (standalone)
```
