// sync_semantic_tokens.js
// Receives semantic token entries via __SEMANTICS__ substitution.
// Each entry: { semantic_name, primitive_name }
//
// Safety: all primitive references are pre-checked before any write.
// If any primitive is missing in Figma, returns ok:false and writes nothing.
//
// Per entry (real run only):
//   1. If semantic_name already exists with correct alias → skip (idempotent)
//   2. If semantic_name already exists with wrong alias   → update alias
//   3. Else                                               → create variable, set VariableAlias
//
// Primitive lookup assumes unique variable names across all local collections.
// No variables are deleted.
// Dry-run logs intent without touching Figma.
// Running twice produces identical results.
//
// Returns: { ok, collection, mode, dry_run, created, updated, skipped, errored,
//            missing_primitives, total, log }

const SEMANTICS = __SEMANTICS__;
const DRY_RUN = __DRY_RUN__;
const COLLECTION_NAME = "semantics";

// --- helpers ---

// Scan all local collections for a variable by name.
// Names are assumed unique across collections; first match wins.
function getPrimitiveByName(name) {
  for (const col of figma.variables.getLocalVariableCollections()) {
    for (const vid of col.variableIds) {
      const v = figma.variables.getVariableById(vid);
      if (v && v.name === name) return v;
    }
  }
  return null;
}

// --- dry-run path (no Figma API calls beyond reading collections) ---

if (DRY_RUN) {
  const log = [];
  let created = 0;
  for (const { semantic_name, primitive_name } of SEMANTICS) {
    log.push({ action: "would-create-alias", semantic_name, primitive_name });
    created++;
  }
  return {
    ok: true,
    collection: COLLECTION_NAME,
    mode: "dry-run-mode",
    dry_run: true,
    created,
    updated: 0,
    skipped: 0,
    errored: 0,
    missing_primitives: [],
    total: SEMANTICS.length,
    log,
  };
}

// --- real run ---

// Pre-check: resolve all primitive references before touching anything.
// Abort with ok:false if any are missing — zero writes occur.
const missing = [];
for (const { primitive_name } of SEMANTICS) {
  if (!getPrimitiveByName(primitive_name)) missing.push(primitive_name);
}
if (missing.length > 0) {
  return {
    ok: false,
    collection: COLLECTION_NAME,
    mode: null,
    dry_run: false,
    created: 0,
    updated: 0,
    skipped: 0,
    errored: missing.length,
    missing_primitives: missing,
    total: SEMANTICS.length,
    log: [],
  };
}

// Get or create the semantics collection.
let col = figma.variables
  .getLocalVariableCollections()
  .find((c) => c.name === COLLECTION_NAME);
if (!col) {
  col = figma.variables.createVariableCollection(COLLECTION_NAME);
}
const modeId = col.defaultModeId || col.modes[0].modeId;

// Build name→variable lookup for the semantics collection.
const byName = {};
for (const vid of col.variableIds) {
  const v = figma.variables.getVariableById(vid);
  if (v) byName[v.name] = v;
}

const log = [];
let created = 0, updated = 0, skipped = 0;

for (const { semantic_name, primitive_name } of SEMANTICS) {
  const primitiveVar = getPrimitiveByName(primitive_name); // guaranteed non-null after pre-check

  const existing = byName[semantic_name];
  if (existing) {
    // Check whether the current alias already points to the right primitive.
    const currentValue = existing.valuesByMode[modeId];
    const alreadyCorrect =
      currentValue &&
      currentValue.type === "VARIABLE_ALIAS" &&
      currentValue.id === primitiveVar.id;

    if (alreadyCorrect) {
      log.push({ action: "skipped", reason: "alias-correct", semantic_name, primitive_name });
      skipped++;
    } else {
      existing.setValueForMode(modeId, figma.variables.createVariableAlias(primitiveVar));
      log.push({ action: "updated", semantic_name, primitive_name });
      updated++;
    }
    continue;
  }

  // Create new semantic variable and set alias.
  const v = figma.variables.createVariable(semantic_name, col.id, "COLOR");
  v.setValueForMode(modeId, figma.variables.createVariableAlias(primitiveVar));
  byName[semantic_name] = v;
  log.push({ action: "created", semantic_name, primitive_name });
  created++;
}

return {
  ok: true,
  collection: COLLECTION_NAME,
  mode: modeId,
  dry_run: false,
  created,
  updated,
  skipped,
  errored: 0,
  missing_primitives: [],
  total: SEMANTICS.length,
  log,
};
