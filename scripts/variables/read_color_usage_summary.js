// read_color_usage_summary.js
// Read-only scan: solid fills/strokes across all pages, paint styles, primitive variables.
// Returns usage data for host-side analysis. No writes to Figma.

function rgbToHex(r, g, b) {
  const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + toHex(r) + toHex(g) + toHex(b);
}

// colorMap: hex -> { fill_count, stroke_count, examples: [{page, node}] }
const colorMap = {};
let scannedNodes = 0;

function recordColor(hex, kind, pageName, nodeName) {
  if (!colorMap[hex]) {
    colorMap[hex] = { fill_count: 0, stroke_count: 0, examples: [] };
  }
  if (kind === "fill") colorMap[hex].fill_count++;
  else colorMap[hex].stroke_count++;
  if (colorMap[hex].examples.length < 3) {
    colorMap[hex].examples.push({ page: pageName, node: nodeName });
  }
}

function scanPaints(paints, kind, pageName, nodeName) {
  if (!Array.isArray(paints)) return;
  for (const paint of paints) {
    if (paint.type !== "SOLID") continue;
    if (paint.visible === false) continue;
    const hex = rgbToHex(paint.color.r, paint.color.g, paint.color.b);
    recordColor(hex, kind, pageName, nodeName);
  }
}

for (const page of figma.root.children) {
  const nodes = page.findAll(() => true);
  for (const node of nodes) {
    scannedNodes++;
    const pageName = page.name;
    const nodeName = node.name;
    if (node.fills) scanPaints(node.fills, "fill", pageName, nodeName);
    if (node.strokes) scanPaints(node.strokes, "stroke", pageName, nodeName);
  }
}

const nodeColors = Object.entries(colorMap).map(([hex, data]) => ({
  hex,
  fill_count: data.fill_count,
  stroke_count: data.stroke_count,
  examples: data.examples,
}));

// Paint styles
const paintStyles = [];
for (const style of figma.getLocalPaintStyles()) {
  const solid = (style.paints || []).find((p) => p.type === "SOLID");
  if (!solid) continue;
  paintStyles.push({
    name: style.name,
    hex: rgbToHex(solid.color.r, solid.color.g, solid.color.b),
    style_id: style.id,
  });
}

// Primitive variables — reference only, not counted as usage
const primitiveVariables = [];
const primCol = figma.variables
  .getLocalVariableCollections()
  .find((c) => c.name === "primitives");
if (primCol) {
  const modeId = primCol.defaultModeId || primCol.modes[0].modeId;
  for (const vid of primCol.variableIds) {
    const v = figma.variables.getVariableById(vid);
    if (!v || v.resolvedType !== "COLOR") continue;
    const val = v.valuesByMode[modeId];
    if (!val || typeof val.r !== "number") continue;
    primitiveVariables.push({
      name: v.name,
      hex: rgbToHex(val.r, val.g, val.b),
    });
  }
}

return {
  scanned_pages: figma.root.children.length,
  scanned_nodes: scannedNodes,
  totals: {
    unique_node_colors: nodeColors.length,
    paint_style_colors: paintStyles.length,
    primitive_variable_colors: primitiveVariables.length,
  },
  node_colors: nodeColors,
  paint_styles: paintStyles,
  primitive_variables: primitiveVariables,
};
