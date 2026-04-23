// sync_primitive_colors.js
// Reads tokens embedded at injection time (see run.py exec --code-file).
// Caller passes tokens via __TOKENS__ substitution (JSON string).
// Supports dry-run via __DRY_RUN__ substitution ("true" | "false").
//
// Returns: { collection, mode, created, updated, skipped, variables }

const TOKENS = __TOKENS__;
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

// Flatten { color: { grey: { "100": { value, type } } } }
// into [{ name: "color/grey/100", value: "#..." }, ...]
function flattenColorTokens(tree, prefix) {
  const result = [];
  for (const [key, node] of Object.entries(tree)) {
    const path = prefix ? prefix + "/" + key : key;
    if (node && typeof node === "object" && "value" in node) {
      if (node.type === "color") result.push({ name: path, value: node.value });
    } else if (node && typeof node === "object") {
      result.push(...flattenColorTokens(node, path));
    }
  }
  return result;
}

// --- main ---

const colorTokens = flattenColorTokens(TOKENS.color || {}, "color");

// Find or create the primitives collection
let col = figma.variables
  .getLocalVariableCollections()
  .find((c) => c.name === COLLECTION_NAME);

if (!col) {
  if (DRY_RUN) {
    col = { id: "dry-run-id", name: COLLECTION_NAME, modes: [{ modeId: "dry-run-mode", name: "Mode 1" }], defaultModeId: "dry-run-mode", variableIds: [] };
  } else {
    col = figma.variables.createVariableCollection(COLLECTION_NAME);
  }
}

const modeId = col.defaultModeId || col.modes[0].modeId;

// Build a lookup of existing variables by name
const existing = {};
if (!DRY_RUN) {
  for (const vid of col.variableIds) {
    const v = figma.variables.getVariableById(vid);
    if (v) existing[v.name] = v;
  }
}

const log = [];
let created = 0, updated = 0, skipped = 0;

for (const token of colorTokens) {
  const rgb = hexToRgb(token.value);

  if (DRY_RUN) {
    log.push({ action: "dry-run", name: token.name, value: token.value });
    created++; // treat all as would-create in dry-run
    continue;
  }

  const current = existing[token.name];

  if (!current) {
    const v = figma.variables.createVariable(token.name, col.id, "COLOR");
    v.setValueForMode(modeId, rgb);
    log.push({ action: "created", name: token.name, value: token.value });
    created++;
  } else {
    const currentVal = current.valuesByMode[modeId];
    if (currentVal && rgbEqual(currentVal, rgb)) {
      log.push({ action: "skipped", name: token.name });
      skipped++;
    } else {
      current.setValueForMode(modeId, rgb);
      log.push({ action: "updated", name: token.name, value: token.value });
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
  total: colorTokens.length,
  log,
};
