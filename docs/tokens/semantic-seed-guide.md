# Semantic Seed Guide

`tokens/primitives-semantic.seed.json` maps semantic token names to primitive token names.

## Purpose

Primitives define raw values. Semantics give those values meaning in context.

```
spacing/space-8  →  spacing/component/padding/sm
```

Consumers reference semantic tokens. Primitives stay invisible to components.

## Naming convention

```
[type]/[scope]/[property]/[size-or-state]
```

| Segment | Examples |
|---------|---------|
| type | `spacing`, `radius`, `font-size`, `font-weight`, `line-height`, `letter-spacing`, `opacity`, `stroke-width` |
| scope | `component`, `layout`, `body`, `heading`, `label` |
| property | `padding`, `gap`, `border`, `focus-ring` |
| size-or-state | `sm`, `md`, `lg`, `disabled` |

Use only the segments you need. Don't add a size suffix unless multiple sizes exist for that token.

## Editing the file

Replace `null` values with a primitive name from the corresponding seed file.

```json
"letter-spacing/heading": null
```

becomes:

```json
"letter-spacing/heading": "letter-spacing/tracking-0"
```

Rules:
- The value must exactly match a `name` field in a primitive seed file.
- Type prefix of the semantic key must match type prefix of the primitive value.
- Remove entries that don't apply to your project before syncing.
- Don't leave `null` values in the file before running a sync.

## Available primitives

| Type | Primitive names |
|------|----------------|
| spacing | `spacing/space-4` … `spacing/space-64` |
| radius | `radius/radius-0`, `radius/radius-4`, `radius/radius-8`, `radius/radius-12`, `radius/radius-100`, `radius/radius-full` |
| font-size | `font-size/font-size-10` … `font-size/font-size-32` |
| font-weight | `font-weight/font-weight-regular`, `font-weight/font-weight-medium`, `font-weight/font-weight-semibold` |
| line-height | `line-height/line-height-16` … `line-height/line-height-36` |
| letter-spacing | `letter-spacing/tracking-0` |
| opacity | `opacity/opacity-0`, `opacity/opacity-5`, `opacity/opacity-10`, `opacity/opacity-30`, `opacity/opacity-50`, `opacity/opacity-70`, `opacity/opacity-100` |
| stroke-width | `stroke-width/stroke-1`, `stroke-width/stroke-1-5`, `stroke-width/stroke-2` |
