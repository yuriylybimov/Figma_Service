// read_color_usage_detail.js
// Read-only scan: per-hex usage counts and sample locations across all pages.
// Returns: array of { hex, use_count, sample_nodes, sample_pages }.
// No writes to Figma.

function rgbToHex(r, g, b) {
  const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + toHex(r) + toHex(g) + toHex(b);
}

// colorMap: hex -> { use_count, nodeNames: Set<string>, pageNames: Set<string> }
const colorMap = {};

function recordColor(hex, nodeName, pageName) {
  if (!colorMap[hex]) {
    colorMap[hex] = { use_count: 0, nodeNames: [], pageNames: [] };
  }
  colorMap[hex].use_count++;
  if (colorMap[hex].nodeNames.length < 5) {
    colorMap[hex].nodeNames.push(nodeName);
  }
  if (!colorMap[hex].pageNames.includes(pageName)) {
    colorMap[hex].pageNames.push(pageName);
  }
}

function scanPaints(paints, nodeName, pageName) {
  if (!Array.isArray(paints)) return;
  for (const paint of paints) {
    if (paint.type !== "SOLID") continue;
    if (paint.visible === false) continue;
    const hex = rgbToHex(paint.color.r, paint.color.g, paint.color.b);
    recordColor(hex, nodeName, pageName);
  }
}

for (const page of figma.root.children) {
  const pageName = page.name;
  const nodes = page.findAll(() => true);
  for (const node of nodes) {
    const nodeName = node.name;
    if (node.fills) scanPaints(node.fills, nodeName, pageName);
    if (node.strokes) scanPaints(node.strokes, nodeName, pageName);
  }
}

const result = Object.entries(colorMap)
  .sort((a, b) => b[1].use_count - a[1].use_count)
  .map(([hex, data]) => ({
    hex,
    use_count: data.use_count,
    sample_nodes: data.nodeNames.slice(0, 5),
    sample_pages: data.pageNames,
  }));

return result;
