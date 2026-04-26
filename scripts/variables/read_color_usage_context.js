// read_color_usage_context.js
// Read-only scan: per-hex enriched usage context for semantic token suggestions.
// Captures fill/stroke/text_fill distribution, node type, parent frame name,
// component name, and up to 5 sample nodes per hex.
// Output shape: array of ColorUsageContext (see tokens/color_usage_context.json).
// No writes to Figma.

function rgbToHex(r, g, b) {
  const toHex = (v) => Math.round(v * 255).toString(16).padStart(2, "0");
  return "#" + toHex(r) + toHex(g) + toHex(b);
}

// colorMap: hex -> ColorEntry
const colorMap = {};

function getOrCreate(hex) {
  if (!colorMap[hex]) {
    colorMap[hex] = {
      hex,
      use_count: 0,
      fill_count: 0,
      stroke_count: 0,
      text_count: 0,
      dominant_role: null,
      sample_nodes: [],
    };
  }
  return colorMap[hex];
}

function addSample(entry, sample) {
  if (entry.sample_nodes.length < 5) {
    entry.sample_nodes.push(sample);
  }
}

function parentFrameName(node) {
  let p = node.parent;
  while (p) {
    if (p.type === "FRAME" || p.type === "COMPONENT" || p.type === "COMPONENT_SET") {
      return p.name || "";
    }
    p = p.parent;
  }
  return "";
}

function componentName(node) {
  if (node.type === "INSTANCE" && node.mainComponent) {
    return node.mainComponent.name || "";
  }
  let p = node.parent;
  while (p) {
    if (p.type === "COMPONENT" || p.type === "COMPONENT_SET") {
      return p.name || "";
    }
    p = p.parent;
  }
  return "";
}

for (const page of figma.root.children) {
  const pageName = page.name;
  const nodes = page.findAll(() => true);

  for (const node of nodes) {
    const nodeName = node.name;
    const nodeType = node.type;
    const pfName = parentFrameName(node);
    const cName = componentName(node);

    const makeSample = (role) => ({
      name: nodeName,
      type: nodeType,
      role,
      page: pageName,
      parent_frame_name: pfName,
      component_name: cName,
    });

    // Fills
    if (Array.isArray(node.fills)) {
      for (const paint of node.fills) {
        if (paint.type !== "SOLID" || paint.visible === false) continue;
        const hex = rgbToHex(paint.color.r, paint.color.g, paint.color.b);
        const entry = getOrCreate(hex);
        entry.use_count++;

        if (nodeType === "TEXT") {
          entry.text_count++;
          addSample(entry, makeSample("text_fill"));
        } else {
          entry.fill_count++;
          addSample(entry, makeSample("fill"));
        }
      }
    }

    // Strokes
    if (Array.isArray(node.strokes)) {
      for (const paint of node.strokes) {
        if (paint.type !== "SOLID" || paint.visible === false) continue;
        const hex = rgbToHex(paint.color.r, paint.color.g, paint.color.b);
        const entry = getOrCreate(hex);
        entry.use_count++;
        entry.stroke_count++;
        addSample(entry, makeSample("stroke"));
      }
    }
  }
}

// Compute dominant_role per hex
for (const entry of Object.values(colorMap)) {
  const counts = {
    fill: entry.fill_count,
    stroke: entry.stroke_count,
    text_fill: entry.text_count,
  };
  entry.dominant_role = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
}

const result = Object.values(colorMap).sort((a, b) => b.use_count - a.use_count);

return result;
