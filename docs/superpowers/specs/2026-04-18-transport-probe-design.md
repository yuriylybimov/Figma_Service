# Transport Probe — Design

**Date:** 2026-04-18
**Status:** Approved (awaiting implementation plan)
**Scope:** Diagnostic only. No transport redesign, no pagination implementation, no product features.

## Problem

Live smoke showed `local-styles-summary` failing with `chunk_incomplete (2/4 chunks missing)`. Payload size cannot be the cause — at `CHUNK_B64_BYTES=2048`, 4 chunks carry ≈6 KB, well under the `EXEC_CAP_BYTES=65536` ceiling. Losing 50% of 4 chunks points to the `figma.notify()` → MutationObserver channel dropping toasts, not a size budget problem.

Before choosing a pagination page size for Phase 1.5, we need evidence: **at what (chunk count × inter-chunk delay) does the current channel become reliable?**

## Goal

Produce a measured **reliable envelope** for the existing chunked-toast transport so pagination defaults can be picked on data, not guesswork.

**Out of scope:**
- Changing the emission channel (toast → title/DOM/etc.)
- Implementing pagination in any command
- `sync_primitive_colors` or any write feature
- Refactors to `run.py`, `protocol.py`, or `host_io.py`

## Design

### Code changes (minimal, production-safe)

1. **[wrapper.js:196](../../../wrapper.js#L196)** — replace the hardcoded `setTimeout(r, 0)` with a substitution marker:
   ```js
   await new Promise((r) => setTimeout(r, __INTER_CHUNK_DELAY__));
   ```
2. **[transport.py:122](../../../transport.py#L122) `_wrap_exec`** — accept `inter_chunk_delay_ms: int = 0`, substitute the marker.
3. **[transport.py:205](../../../transport.py#L205) `_bridge_exec`** — accept `inter_chunk_delay_ms: int = 0` kwarg, thread through to `_wrap_exec`.

Default **`0`** preserves current production behavior byte-for-byte. Existing `_dispatch_read` callers in [run.py](../../../run.py) do not change.

### New probe

**Location:** `tools/transport_probe.py` — standalone script. Not registered in the typer CLI. Invoked as `python tools/transport_probe.py [args]`.

**Why standalone:** diagnostic infrastructure, not product surface. Keeps `run.py` clean.

**Session reuse:** the probe opens a single Playwright context + Scripter frame once, then loops all sweep cells against that one session. Expected sweep wall-clock drops from ~25 min (browser-per-run) to ~2–3 min.

**To enable session reuse**, extract the session setup from `_bridge_exec` into a small helper that yields `(page, frame)` and a `run_once(user_js, rid, inline_cap, delay_ms) -> (outcome, detail)` callable. `_bridge_exec` itself stays wired the same way on top of this helper — no behavior change for production callers.

### Test payload

Deterministic, incompressible, JSON-safe:
```js
return "x".repeat(__BYTES__);
```

Host computes expected chunk count from the requested `bytes` (UTF-8 length = base64 length × 3/4 → ceil((bytes × 4 / 3) / CHUNK_B64_BYTES)), and confirms against the `BEGIN` header `chunks` field received from the wrapper.

### Sweep matrix (starting point)

| Dimension     | Values                           |
|---------------|----------------------------------|
| `bytes`       | 1_000, 4_000, 16_000, 32_000, 65_000 |
| `delay_ms`    | 0, 25, 100, 250, 500             |
| `runs` / cell | 3                                |

**Total:** 75 runs. Matrix is tunable via CLI flags so we can narrow after the first pass.

### CSV output

One row per run, appended to `probe-results.csv`:

| Column             | Notes |
|--------------------|-------|
| `ts`               | ISO-8601 UTC |
| `bytes`            | Requested payload size |
| `chunks_expected`  | From `BEGIN` header |
| `delay_ms`         | Inter-chunk delay for this run |
| `run_idx`          | 0-based index within the cell |
| `outcome`          | `ok` / `chunk_incomplete` / `chunk_corrupt` / `timeout` |
| `chunks_delivered` | Parsed from error `detail` on failure, or `=chunks_expected` on `ok` |
| `missing_indexes`  | Comma-separated, or empty on `ok` |
| `elapsed_ms`       | Time from run start to outcome |
| `error_detail`     | Full `detail` string on failure, empty on `ok` |

`missing_indexes` is the load-bearing column — loss clustering at the tail (old toasts auto-dismissed), at the head (observer-install race), or random (rate limiting) each implies a different mitigation.

### Analysis & deliverable

**Primary deliverable:** `docs/superpowers/specs/2026-04-18-transport-ceiling-findings.md` — one page, containing:

1. **Sweep table** — per-cell success rate (runs_ok / runs_total) as a grid.
2. **Reliable envelope** — the largest `(chunks_expected, delay_ms)` cell where all 3 runs succeeded, and the nearest failing cell. State the ceiling as e.g. *"≤ N chunks at ≥ D ms is reliable; above that expect drops."*
3. **Loss pattern** — does `missing_indexes` cluster at the tail / head / middle, or scatter randomly? Quote a representative failure row.
4. **Recommendation** — a concrete Phase-1.5 pagination page-size in bytes, with a safety margin below the observed ceiling. One paragraph.
5. **Scope caveat** — explicit note that this ceiling is a property of `figma.notify()` + MutationObserver, and that a channel swap (e.g. DOM mutation via hidden node, `document.title` rotation) would lift it. Not proposed here.

**Raw data:** `probe-results.csv` committed alongside the memo.

## Non-goals (restated for the implementer)

- Do not change [protocol.py](../../../protocol.py) or add error kinds.
- Do not refactor `_dispatch_read` or any user-facing command.
- Do not implement pagination in `local-styles-summary` (next spec).
- Do not add a `probe` subcommand to `run.py` — script lives in `tools/` only.
- Do not commit `probe-results.csv` with noisy / ad-hoc data; commit the final sweep that backs the memo.

## Open questions for the implementation plan

1. Should the probe auto-clean the observer / collector between runs, or install once and let the wrapper's own cleanup path handle it? (Current `_bridge_exec` installs per call; for session reuse we'll need one install + per-run rid rotation.)
2. Page-size CLI flag — default bytes-sweep string, or require it explicitly? (Lean: default provided, overrideable.)
3. Do we hold the sweep matrix in the script or accept it as CLI args? (Lean: CLI args with defaults; keeps the script re-runnable after findings.)

These are plan-level decisions, not design changes.
