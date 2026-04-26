// sync_primitive_tokens.js
// Creates or updates primitive (non-color) token variables in Figma.
//
// Receives injected values via template substitution:
//   __ENTRIES__    — JSON array of { name: string, value: number|string }
//   __FIGMA_TYPE__ — "FLOAT" or "STRING"
//   __TYPE_KEY__   — primitive type key (e.g. "font-size", "spacing")
//   __DRY_RUN__    — true | false
//
// Behaviour per entry:
//   1. If a variable with that name already exists → skip (idempotent).
//   2. Otherwise → create it with the correct type and set its value.
//
// All writes target the "primitives" collection (created if absent).
// No variables are deleted.
// Running twice produces no duplicates.
//
// Returns: { collection, mode, dry_run, created, skipped, errored, total, log }

const ENTRIES    = __ENTRIES__;
const FIGMA_TYPE = __FIGMA_TYPE__;
const TYPE_KEY   = __TYPE_KEY__;
const DRY_RUN    = __DRY_RUN__;

// Typography types get a top-level "Font" group in Figma.
// Figma treats "/" as a group separator, so "Font/font-size/font-size-14"
// renders as: Font → font-size → font-size-14.
const FONT_TYPES = new Set([
  "font-family",
  "font-size",
  "font-weight",
  "line-height",
  "letter-spacing",
]);

function figmaName(seedName) {
  return FONT_TYPES.has(TYPE_KEY) ? "Font/" + seedName : seedName;
}

const COLLECTION_NAME = "primitives";

// --- locate or create collection ---

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

// Build name → variable lookup (real runs only — dry-run skips Figma reads)
const byName = {};
if (!DRY_RUN) {
  for (const vid of col.variableIds) {
    const v = figma.variables.getVariableById(vid);
    if (v) byName[v.name] = v;
  }
}

const log = [];
let created = 0, skipped = 0, errored = 0;

for (const entry of ENTRIES) {
  const { name: seedName, value } = entry;
  const name = figmaName(seedName);

  if (DRY_RUN) {
    log.push({ action: "would-create", name, seed_name: seedName, value, figma_type: FIGMA_TYPE });
    created++;
    continue;
  }

  // Idempotent: skip if the variable already exists.
  if (byName[name]) {
    log.push({ action: "skipped", reason: "already-exists", name });
    skipped++;
    continue;
  }

  try {
    const v = figma.variables.createVariable(name, col.id, FIGMA_TYPE);
    v.setValueForMode(modeId, value);
    byName[name] = v;
    log.push({ action: "created", name, seed_name: seedName, value, figma_type: FIGMA_TYPE });
    created++;
  } catch (e) {
    log.push({ action: "error", name, error: String(e.message) });
    errored++;
  }
}

return {
  collection: COLLECTION_NAME,
  mode: modeId,
  dry_run: DRY_RUN,
  figma_type: FIGMA_TYPE,
  created,
  skipped,
  errored,
  total: ENTRIES.length,
  log,
};
