# Heavy-payload validation — 2026-04-19

Goal: confirm that the remaining read commands hold up on real-world Figma files after payload-bounding work on `local-styles-summary` / `components-summary` and the transport refactor onto `console.log`.

## Environment
- Host: macOS, Python 3.10, Playwright + Firefox profile at `./profile/`
- Transport: `console.log` sentinels collected via `page.on("console")` ([transport.py:175](../../transport.py#L175))
- Caps: inline 500 B, file-mode 64 KiB (65,536 B)

## File 1 — `.env` FIGMA_FILE_URL ("Campaign Pulse")

Shape:
- 6 pages; heaviest = "styles" (53 top-level children)
- 3 variable collections (Primitives 42 / Semantic 34 / Component 37), all single-mode

| Command | Flags | Status | Bytes | Elapsed (ms) | Notes |
|---|---|---|---|---|---|
| `read ping` | inline | ok | result 48 B inline | 1 | baseline alive |
| `read document-summary` | `--out` | ok | 734 | 13058 | full 6-page list |
| `read selection-info` | inline (empty) | ok | `[]` | 1 | empty-selection path |
| `read variable-collections-summary` | `--out` | ok | 882 | 13070 | 3 collections, summary form |
| `read page-nodes-summary --page-id 12:4455` | inline | **error** | — | 75 | `payload_too_large` 6243 B > 500 B cap. **Principled** — inline is meant for tiny results; falls back to file mode. |
| `read page-nodes-summary --page-id 12:4455` | `--out` | ok | 10097 | 12873 | 53 children → ~190 B/child. A ~340-child page would flirt with 64 KiB. |
| `read variable-collection-detail VariableCollectionId:67:1933` | `--out` | ok | 15365 | 13074 | Primitives, 42 vars × 1 mode |
| `read variable-collection-detail VariableCollectionId:67:2010` | `--out` | ok | 11883 | 12737 | Component, 37 vars × 1 mode |

Transport: zero `chunk_incomplete` / `chunk_corrupt` / `timeout` / `scripter_unreachable` across all runs. Console-log sentinel collection looks solid on this file.

## File 2 — heavier URL (TBD)

Awaiting second URL from user. Will extend this section with a matching table once re-run.

## Interim findings

1. **Transport is healthy.** No delivery-layer failures on any of the 8 baseline runs. No need to scope Phase B.5.
2. **`page-nodes-summary` payload growth is roughly linear in child count** (~190 B per direct child on this file). With the existing 64 KiB cap that allows ~340 children; pages beyond that would need pagination. Not a blocker today; flagged for future if observed on the second file.
3. **`variable-collection-detail` scales with `variables × modes`.** Primitives at 42×1 ≈ 15 KiB → a collection with 3 modes at the same variable count would still fit (~45 KiB), but a 3-mode collection with 80+ variables would exceed the cap. Collection slicing (`--offset`/`--limit`) is a reasonable Phase B.5 follow-up *only if* the second file surfaces it.
4. **Inline 500 B cap behaves correctly** — error is `payload_too_large` with a clear `bytes=<n> cap=500` detail; not a transport failure.
5. **Elapsed time is dominated by browser warm-up**, not payload size. Every successful file-mode run clocks ~13 s regardless of payload (734 B vs 15 KiB). That's Scripter mount + navigation, not transport.

## Next step

Ask user for second heavier Figma URL. Re-run identical matrix. Update table. Then decide on Phase B.

- File 2 was skipped by decision
- Phase A is considered complete based on File 1
