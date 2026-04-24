// sync_primitive_colors_normalized.js
// Receives normalized color entries via __NORMALIZED__ substitution.
// Each entry: { hex, candidate_name, final_name, ... }
//
// Per entry:
//   1. If color/candidate/<hex> exists  → rename to final_name (no-op if already named)
//   2. Else if final_name already exists → skip (idempotent)
//   3. Else                              → create final_name with the hex value
//
// No variables are deleted.
// Dry-run logs intent without touching Figma.
// Running twice produces identical results (no duplicates, no extra renames).
//
// Returns: { collection, mode, dry_run, renamed, created, skipped, total, log }

const NORMALIZED = __NORMALIZED__;
const DRY_RUN = __DRY_RUN__;
const COLLECTION_NAME = "primitives";

// --- helpers ---

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return {
    r: parseInt(h.slice(0, 2), 16) / 255,
    g: parseInt(h.slice(2, 4), 16) / 255,
    b: parseInt(h.slice(4, 6), 16) / 255,
    a: 1,
  };
}

// --- main ---

let col = figma.variables
  .getLocalVariableCollections()
  .find((c) => c.name === COLLECTION_NAME);

if (!col) {
  if (DRY_RUN) {
    col = {
      id: "dry-run-id",
      name: COLLECTION_NAME,
      modes: [{ modeId: "dry-run-mode", name: "Mode 1" }],
      defaultModeId: "dry-run-mode",
      variableIds: [],
    };
  } else {
    col = figma.variables.createVariableCollection(COLLECTION_NAME);
  }
}

const modeId = col.defaultModeId || col.modes[0].modeId;

// Build name→variable lookup (only needed for real runs)
const byName = {};
if (!DRY_RUN) {
  for (const vid of col.variableIds) {
    const v = figma.variables.getVariableById(vid);
    if (v) byName[v.name] = v;
  }
}

const log = [];
let renamed = 0, created = 0, skipped = 0;

for (const entry of NORMALIZED) {
  const { hex, candidate_name, final_name } = entry;
  const rgb = hexToRgb(hex);

  if (DRY_RUN) {
    const hasCandidateNote = `(would check for ${candidate_name})`;
    log.push({ action: "would-rename-or-create", candidate_name, final_name, hex, note: hasCandidateNote });
    created++; // counted as intended writes in dry-run
    continue;
  }

  // Case 1: candidate variable exists → rename it to final_name
  const candidate = byName[candidate_name];
  if (candidate) {
    if (candidate.name === final_name) {
      // Already renamed — idempotent
      log.push({ action: "skipped", reason: "already-named", name: final_name });
      skipped++;
    } else {
      candidate.name = final_name;
      // Update index so later entries can see the rename
      delete byName[candidate_name];
      byName[final_name] = candidate;
      log.push({ action: "renamed", from: candidate_name, to: final_name });
      renamed++;
    }
    continue;
  }

  // Case 2: final_name already exists → skip (idempotent second run)
  if (byName[final_name]) {
    log.push({ action: "skipped", reason: "final-exists", name: final_name });
    skipped++;
    continue;
  }

  // Case 3: create final_name with the hex value
  const v = figma.variables.createVariable(final_name, col.id, "COLOR");
  v.setValueForMode(modeId, rgb);
  byName[final_name] = v;
  log.push({ action: "created", name: final_name, value: hex });
  created++;
}

return {
  collection: COLLECTION_NAME,
  mode: modeId,
  dry_run: DRY_RUN,
  renamed,
  created,
  skipped,
  total: NORMALIZED.length,
  log,
};
