# Canonical Typography Roles
**Phase:** 4.6
**Date:** 2026-04-26
**Input:** `tokens/typography-audit.json`
**Status:** Defined — not yet written to seed

---

## Canonical System (8 roles)

All roles use **Urbanist**, `letterSpacing: 0`.

| Token name | fontSize | fontWeight | lineHeight | ratio | Primary use |
|------------|----------|------------|------------|-------|-------------|
| `heading/lg` | 32 | 600 | 36 | 1.125 | Page titles, hero headings |
| `heading/md` | 24 | 600 | 28 | 1.167 | Section headings |
| `heading/sm` | 20 | 600 | 24 | 1.200 | Card headings, modal titles |
| `body/lg` | 16 | 500 | 20 | 1.250 | Primary body text, UI labels |
| `body/sm` | 14 | 400 | 20 | 1.429 | Secondary body, descriptions |
| `label/lg` | 14 | 600 | 16 | 1.143 | Emphasis labels, button text |
| `label/sm` | 12 | 500 | 16 | 1.333 | Metadata, tags, helper text |
| `label/xs` | 10 | 600 | 16 | 1.600 | Badges, captions, overlines |

---

## Mapping: Raw Combinations → Canonical Roles

Each raw combination is assigned to a canonical role or marked as an outlier/variant.
`nodes` = raw `usageCount` from audit. Combined node totals per role shown in the summary below.

### heading/lg — 32 / 600 / 36

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 32 / 600 / 28 | 0 | 4 | → heading/lg (lh normalized 28→36) |
| 32 / 600 / 36 | 0 | 4 | → heading/lg (exact match) |

**Total mapped nodes: 8**
**Decision:** Two lineHeight values (28, 36) tied at 4 nodes each. Chose 36 (1.125× ratio) — tighter lh=28 at 32px produces nearly no breathing room and is atypical for display text.

---

### heading/md — 24 / 600 / 28

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 24 / 600 / 24 | "0%" | 16 | → heading/md (lh normalized 24→28, ls normalized) |
| 24 / 600 / 28 | 0 | 11 | → heading/md (exact match) |

**Total mapped nodes: 27**
**Decision:** lh=24 at 24px = 1.0 ratio (no breathing room); lh=28 (1.167×) is the typographically correct choice. The lh=24 nodes are visually tight and should be updated.

---

### heading/sm — 20 / 600 / 24

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 20 / 600 / 24 | 0 | 29 | → heading/sm (exact match) |
| 20 / 500 / 32 | 0 | 6 | → heading/sm (weight and lh normalized; 500→600) |
| 20 / 500 / 24 | 0 | 3 | → heading/sm (weight normalized; 500→600) |
| 20 / null / 24 | 0 | 2 | → heading/sm (null family — needs Figma fix first) |

**Total mapped nodes: 40**
**Decision:** 20px is exclusively heading territory in this file. The 9 nodes at weight 500 are inconsistencies — same size, wrong weight. Normalize to 600 on Figma cleanup.

---

### body/lg — 16 / 500 / 20

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 16 / 500 / 20 | 0 | 104 | → body/lg (exact match) |
| 16 / 500 / 20 | "0%" | 10 | → body/lg (ls normalized) |
| 16 / 500 / 24 | 0 | 44 | → body/lg (lh normalized 24→20) |
| 16 / 600 / 24 | 0 | 9 | → body/lg (weight normalized 600→500, lh→20) |
| 16 / 600 / 20 | 0 | 6 | → body/lg (weight normalized 600→500) |
| 16 / 400 / 28 | 0 | 5 | → body/sm-variant (see below) |

**Total mapped nodes: 178** (excl. the 16/400/28 outlier)
**Decision:** 16px is the dominant body size; 500 is the dominant weight (173 nodes vs 14 at other weights). lh=20 is the majority line-height. The 44 nodes at lh=24 use a looser rhythm that is valid for prose — flagged as a known variant but mapped to the canonical value for token purposes.

---

### body/sm — 14 / 400 / 20

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 14 / 400 / 20 | 0 | 37 | → body/sm (exact match) |
| 14 / 500 / 20 | 0 | 25 | → body/sm (weight normalized 500→400) |
| 14 / 400 / 16 | 0 | 31 | → label/lg (see label/lg mapping — tighter lh = label context) |
| 14 / 400 / 24 | 0 | 1 | → body/sm (lh normalized) |
| 14 / 500 / 24 | 0 | 20 | → body/sm (weight+lh normalized) |
| 14 / null / 20 | 0 | 8 | → body/sm (null family — needs Figma fix) |

**Total mapped nodes: 91** (excl. the lh=16 rows which go to label/lg)
**Decision:** 14px Regular/20 is the dominant secondary body pattern. The 14/500 nodes are a weight inconsistency — same role, wrong weight. The lh=16 sub-group (14/400/16 and 14/600/16) reads as label context, not body, and is separated into label/lg.

---

### label/lg — 14 / 600 / 16

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 14 / 600 / 16 | 0 | 38 | → label/lg (exact match) |
| 14 / 400 / 16 | 0 | 31 | → label/lg (weight normalized 400→600) |
| 14 / 600 / 20 | 0 | 38 | → label/lg (lh normalized 20→16) |
| 14 / 600 / 24 | 0 | 6 | → label/lg (lh normalized) |
| 14 / 600 / 16 | 0.6 | 2 | → label/lg (ls normalized; likely a tracked label) |
| 14 / 500 / 16 | 0 | 85 | → label/lg (weight normalized 500→600) |

**Total mapped nodes: 200**
**Decision:** 14px with lh=16 is clearly label/UI territory — tight leading is only appropriate when text is single-line UI elements. The 14/500/16 block (85 nodes, the #2 most-used raw combination) gets normalized from 500 to 600. This is the most impactful normalization in the entire file.

---

### label/sm — 12 / 500 / 16

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 12 / 500 / 16 | 0 | 52 | → label/sm (exact match) |
| 12 / 400 / 16 | 0 | 26 | → label/sm (weight normalized 400→500) |
| 12 / null / 16 | 0 | 4 | → label/sm (null family — needs Figma fix) |

**Total mapped nodes: 82**
**Decision:** 12px is exclusively small-label territory. Both weights present (400, 500) collapse to 500 — Regular at 12px is weak on most screens; Medium is the better default.

---

### label/xs — 10 / 600 / 16

| Raw (fs/fw/lh) | letterSpacing | nodes | Action |
|----------------|---------------|-------|--------|
| 10 / 600 / 16 | 0 | 28 | → label/xs (exact match) |
| 10 / 500 / AUTO | 0 | 24 | → label/xs (weight+lh normalized; AUTO→16) |
| 10 / 400 / AUTO | 0 | 20 | → label/xs (weight+lh normalized; AUTO→16) |

**Total mapped nodes: 72**
**Decision:** AUTO line-height cannot be tokenized; 16px lh is the only explicit value present at this size and produces a clean 1.6× ratio. All 10px nodes collapse to 600/16 — at 10px, weight 400 is barely legible on most screens; 600 is the correct accessible default.

---

## Excluded / Outlier Combinations

These combinations are not assigned to any canonical role.

| Raw (fs/fw/lh) | nodes | Reason |
|----------------|-------|--------|
| 13 / 500 / 16 | 21 | Off-scale size — not in the intended type scale. Remap to `label/sm` (12/500/16) or `label/lg` (14/600/16) in Figma |
| 11 / 400 / 16.5 | 2 | Off-scale size + fractional lineHeight. Delete or remap to `label/sm` |
| 16 / 400 / 28 | 5 | Loose body variant — no canonical role; remap to `body/sm` (14/400/20) or `body/lg` (16/500/20) |

**Total excluded nodes: 28 of 754 (3.7%)**

---

## Coverage Summary

| Role | Canonical values (fs/fw/lh) | Mapped nodes | % of 754 |
|------|-----------------------------|--------------|----------|
| heading/lg | 32 / 600 / 36 | 8 | 1.1% |
| heading/md | 24 / 600 / 28 | 27 | 3.6% |
| heading/sm | 20 / 600 / 24 | 40 | 5.3% |
| body/lg | 16 / 500 / 20 | 178 | 23.6% |
| body/sm | 14 / 400 / 20 | 91 | 12.1% |
| label/lg | 14 / 600 / 16 | 200 | 26.5% |
| label/sm | 12 / 500 / 16 | 82 | 10.9% |
| label/xs | 10 / 600 / 16 | 72 | 9.5% |
| null-family nodes | — | 16 | 2.1% |
| outliers | — | 28 | 3.7% |
| **Covered by 8 roles** | | **698** | **92.6%** |

---

## Unresolved Decisions

### 1. body/lg loose variant (lh=24)
44 nodes use `16/500/24` — a looser rhythm valid for longer prose. The canonical role normalizes these to lh=20. If the design intentionally uses lh=24 for paragraph text (vs lh=20 for UI strings), a `body/lg-loose` role could be added as a 9th role.

**Options:**
- A) Normalize all to `body/lg` (lh=20) — simpler, fewer tokens
- B) Add `body/lg-loose` (16/500/24) — more expressive, more tokens

### 2. 13px nodes (21 uses)
fontSize 13 has significant usage (21 nodes) but sits between standard scale steps. Origin is unclear — was this intentional sizing or a copy-paste from another component?

**Options:**
- A) Remap all to `label/sm` (12/500/16) — closer in size
- B) Remap all to `label/lg` (14/600/16) — closer in purpose (UI labels at medium weight)
- C) Preserve as `label/md` (13/500/16) — adds a 9th role, keeps current sizes

### 3. label/lg weight normalization (500→600)
The single largest normalization is 85 nodes of `14/500/16` mapped to `label/lg` (14/600/16). This changes visible weight on those nodes. The 500→600 step is subtle in Urbanist but not invisible.

**Options:**
- A) Accept 600 as canonical — weight consistency across all labels
- B) Keep `label/lg-medium` (14/500/16) as a separate 9th role — preserves current appearance

---

## Next Step

Once the 3 unresolved decisions above are confirmed, generate `tokens/text-styles.seed.json` with exactly these 8 (or up to 9) entries — one per canonical role.

No Figma reads required. No changes to primitive seeds required.
