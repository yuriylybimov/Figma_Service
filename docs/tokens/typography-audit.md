# Typography Audit
**Source:** `tokens/typography-audit.json`
**Date:** 2026-04-26
**Figma file:** Campaign Pulse

---

## Summary

| Metric | Value |
|--------|-------|
| Named text styles | **0** |
| Unique typography combinations | **34** |
| Total text nodes scanned | **754** |
| Font families | **1** (Urbanist) |
| Font weights in use | **3** (400, 500, 600) |
| Font sizes in use | **9** (10, 11, 12, 13, 14, 16, 20, 24, 32) |

**Critical finding:** The file has zero named text styles. All 754 text nodes carry ad-hoc typography properties. There is no style system in place — every combination is freeform.

---

## Top Typography Combinations (by usage)

Ranked by `usageCount`, Urbanist only, excluding null-family nodes.

| Rank | fontSize | fontWeight | lineHeight | letterSpacing | usageCount | Role guess |
|------|----------|------------|------------|---------------|------------|------------|
| 1 | 16 | 500 | 20 | 0 | 104 | body-md-medium |
| 2 | 14 | 500 | 16 | 0 | 85 | label-md-medium |
| 3 | 12 | 500 | 16 | 0 | 52 | label-sm-medium |
| 4 | 16 | 500 | 24 | 0 | 44 | body-md-medium-loose |
| 5 | 14 | 600 | 16 | 0 | 38 | label-md-semibold |
| 6 | 14 | 600 | 20 | 0 | 38 | label-md-semibold-loose |
| 7 | 14 | 400 | 20 | 0 | 37 | body-sm-regular |
| 8 | 16 | 400 | 24 | 0 | 33 | body-md-regular |
| 9 | 14 | 400 | 16 | 0 | 31 | label-sm-regular |
| 10 | 20 | 600 | 24 | 0 | 29 | heading-sm |
| 11 | 10 | 600 | 16 | 0 | 28 | caption-semibold |
| 12 | 12 | 400 | 16 | 0 | 26 | label-sm-regular |
| 13 | 14 | 500 | 20 | 0 | 25 | body-sm-medium |
| 14 | 10 | 500 | AUTO | 0 | 24 | caption-medium |
| 15 | 13 | 500 | 16 | 0 | 21 | — (off-scale) |
| 16 | 10 | 400 | AUTO | 0 | 20 | caption-regular |
| 17 | 14 | 500 | 24 | 0 | 20 | body-sm-medium-loose |
| 18 | 24 | 600 | 24 | 0% | 16 | heading-md |
| 19 | 24 | 600 | 28 | 0 | 11 | heading-md-loose |
| 20 | 16 | 500 | 20 | 0% | 10 | body-md-medium (duplicate of #1) |

---

## Existing Named Text Styles

**None.** `text_styles` array is empty.

All typography is inline — no style library is defined in this file. Consequence: changes must be made node-by-node; there is no single source of truth to update.

---

## Issues Found

### 1. No named text styles (critical)
Zero styles means zero design system enforcement. Every designer on this file sets properties manually. Drift is guaranteed at scale.

### 2. Same weight/size with multiple line-heights (fragmentation)
The same `fontSize + fontWeight` pair appears with 2–3 different `lineHeight` values. This produces multiple "styles" for what should be a single role:

| fontSize | fontWeight | lineHeights observed |
|----------|------------|----------------------|
| 16 | 500 | 20, 24 |
| 14 | 500 | 16, 20, 24 |
| 14 | 600 | 16, 20, 24 |
| 20 | 500 | 24, 32 |
| 24 | 600 | 24, 28 |
| 32 | 600 | 28, 36 |

Line-height should be part of the named style, not ad-hoc per node. A single text style role should own one canonical line-height.

### 3. Off-scale font sizes (13, 11)
- `fontSize: 13` — 21 uses, Medium 500. Not part of any standard scale (10/12/14/16/20/24/32). Likely a one-off or placeholder that drifted in.
- `fontSize: 11` — 2 uses, Regular 400, `lineHeight: 16.5` (fractional). Both values are non-standard.

Recommendation: remap 13 → 12 or 14; eliminate 11 entirely.

### 4. letterSpacing type inconsistency
Two serialization forms appear for zero letter-spacing:
- `0` (number) — majority of nodes
- `"0%"` (string percent) — appears on 2 combinations (fontSize 24 SemiBold lh=24; fontSize 16 Medium lh=20)

This indicates the `"0%"` nodes were set via the percentage input in Figma, not absolute. When building seeds, normalize all to `0` (absolute). The `"0%"` variant is equivalent but will need handling in any seed validator that type-checks `letterSpacing`.

### 5. lineHeight: "AUTO" on small sizes
`fontSize: 10` nodes use `"AUTO"` line-height (24 + 20 occurrences). AUTO line-height is font-renderer-dependent and cannot be stored as a numeric token. These nodes must be given an explicit line-height before they can be represented by a text style token. Recommended: `lineHeight: 16` for 10px text (1.6× ratio).

### 6. fontFamily: null nodes (12 occurrences)
Three combinations have `fontFamily: null` and `fontWeight: null` across 14 nodes (8 + 4 + 2). These are likely placeholder or empty text layers with mixed properties. They cannot be tokenized and should be audited and cleaned in Figma before style generation.

### 7. Duplicate combination rows (letterSpacing "0%" vs 0)
Rows 1 and 20 in the usage table are the same logical style (`16/500/20/0`) but appear as two separate combinations because `letterSpacing` is `0` vs `"0%"`. Combined usage would be 114, making it the single highest-use combination.

---

## Recommended Font Scale

Based on usage frequency (≥20 uses), the canonical primitive set is:

**font-size:** 10, 12, 14, 16, 20, 24, 32  
**font-weight:** 400, 500, 600  
**line-height:** 16, 20, 24, 28 (drop AUTO; resolve to 16 for 10px)  
**letter-spacing:** 0 (all; normalize "0%" → 0)  
**font-family:** Urbanist

Remove: fontSize 11, 13 (off-scale, low use).

---

## Recommended Next Step

**Generate `tokens/text-styles.seed.json`** with named text style combinations.

Before doing so:

1. Decide canonical line-height per role (one lineHeight per size/weight pair — see fragmentation table above). This is the only design decision required.
2. Fix `fontFamily: null` nodes in Figma (14 nodes).
3. Resolve `lineHeight: "AUTO"` nodes (assign explicit value, recommend 16 for size 10).
4. Drop off-scale sizes 11 and 13 from the seed (or remap them).

Once those decisions are made, `text-styles.seed.json` can be generated directly from the canonical combinations in this audit — no additional Figma reads needed.
