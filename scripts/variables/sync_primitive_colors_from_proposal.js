// sync_primitive_colors_from_proposal.js
// Reads new_candidate colors injected via __CANDIDATES__ substitution.
// Names are temporary (color/candidate/<hex>) and will be renamed later.
// Supports dry-run via __DRY_RUN__ substitution ("true" | "false").
//
// Returns: { collection, mode, dry_run, created, updated, skipped, total, log }

const CANDIDATES = __CANDIDATES__;
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

function rgbEqual(a, b) {
  return (
    Math.abs(a.r - b.r) < 0.001 &&
    Math.abs(a.g - b.g) < 0.001 &&
    Math.abs(a.b - b.b) < 0.001 &&
    Math.abs(a.a - b.a) < 0.001
  );
}

// --- main ---

// Find or create the primitives collection
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

// Build lookup of existing variables by name
const existing = {};
if (!DRY_RUN) {
  for (const vid of col.variableIds) {
    const v = figma.variables.getVariableById(vid);
    if (v) existing[v.name] = v;
  }
}

const log = [];
let created = 0, updated = 0, skipped = 0;

for (const candidate of CANDIDATES) {
  // Temporary name — will be renamed by the user after review
  const name = "color/candidate/" + candidate.hex.replace("#", "");
  const rgb = hexToRgb(candidate.hex);

  if (DRY_RUN) {
    log.push({ action: "would-create", name, value: candidate.hex });
    created++;
    continue;
  }

  const current = existing[name];

  if (!current) {
    const v = figma.variables.createVariable(name, col.id, "COLOR");
    v.setValueForMode(modeId, rgb);
    log.push({ action: "created", name, value: candidate.hex });
    created++;
  } else {
    const currentVal = current.valuesByMode[modeId];
    if (currentVal && rgbEqual(currentVal, rgb)) {
      log.push({ action: "skipped", name });
      skipped++;
    } else {
      current.setValueForMode(modeId, rgb);
      log.push({ action: "updated", name, value: candidate.hex });
      updated++;
    }
  }
}

return {
  collection: COLLECTION_NAME,
  mode: modeId,
  dry_run: DRY_RUN,
  created,
  updated,
  skipped,
  total: CANDIDATES.length,
  log,
};
