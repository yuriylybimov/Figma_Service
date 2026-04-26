// read_primitive_usage.js
// Read-only scan: raw primitive (non-color) values across all pages.
// No writes to Figma.

const spacing   = [];
const radius    = [];
const strokeWidth = [];
const fontSize  = [];
const fontWeight = [];
const fontFamily = [];
const lineHeight = [];
const letterSpacing = [];
const opacity   = [];

let scannedNodes = 0;

function parseFontWeight(style) {
  const s = style.toLowerCase();
  if (s.includes("thin"))        return 100;
  if (s.includes("extralight") || s.includes("extra light") || s.includes("ultralight")) return 200;
  if (s.includes("light"))       return 300;
  if (s.includes("medium"))      return 500;
  if (s.includes("semibold") || s.includes("semi bold") || s.includes("demibold")) return 600;
  if (s.includes("extrabold") || s.includes("extra bold") || s.includes("ultrabold")) return 800;
  if (s.includes("black") || s.includes("heavy")) return 900;
  if (s.includes("bold"))        return 700;
  if (s.includes("regular") || s.includes("normal") || s.includes("roman")) return 400;
  return null;
}

// Spacing range constants — must match SPACING_MIN / SPACING_MAX in suggest_primitives.py.
const SPACING_MIN = 4;
const SPACING_MAX = 128;

function recordSpacing(node) {
  // Auto Layout guard: only collect spacing from nodes with active Auto Layout.
  // layoutMode "NONE" means the node uses manual positioning — its padding
  // properties are not reliable design-system spacing values.
  if (node.layoutMode === "NONE" || !node.layoutMode) return;

  for (const prop of ["paddingLeft", "paddingRight", "paddingTop", "paddingBottom", "itemSpacing"]) {
    const v = node[prop];
    if (typeof v === "number" && v >= SPACING_MIN && v <= SPACING_MAX) spacing.push(v);
  }
}

function recordRadius(node) {
  const cr = node.cornerRadius;
  if (typeof cr === "number") {
    radius.push(cr);
    return;
  }
  // Mixed corners — collect each individually
  for (const prop of ["topLeftRadius", "topRightRadius", "bottomLeftRadius", "bottomRightRadius"]) {
    const v = node[prop];
    if (typeof v === "number") radius.push(v);
  }
}

function recordText(node) {
  const fs = node.fontSize;
  if (typeof fs === "number") fontSize.push(fs);

  const ff2 = node.fontName;
  if (ff2 && typeof ff2 === "object" && typeof ff2.style === "string") {
    const fw = parseFontWeight(ff2.style);
    if (fw !== null) fontWeight.push(fw);
  }

  const ff = node.fontName;
  if (ff && typeof ff === "object" && typeof ff.family === "string") {
    fontFamily.push(ff.family);
  }

  const lh = node.lineHeight;
  if (lh && lh.unit === "PIXELS" && typeof lh.value === "number") {
    lineHeight.push(lh.value);
  }

  const ls = node.letterSpacing;
  if (ls && ls.unit === "PIXELS" && typeof ls.value === "number") {
    letterSpacing.push(ls.value);
  }
}

for (const page of figma.root.children) {
  const nodes = page.findAll(() => true);
  for (const node of nodes) {
    scannedNodes++;

    if (typeof node.opacity === "number" && node.opacity < 1) {
      opacity.push(node.opacity);
    }

    if (Array.isArray(node.strokes) && node.strokes.length > 0) {
      const sw = node.strokeWeight;
      if (typeof sw === "number" && sw > 0) strokeWidth.push(sw);
    }

    const t = node.type;
    if (t === "FRAME" || t === "COMPONENT" || t === "COMPONENT_SET" || t === "INSTANCE") {
      recordSpacing(node);
      recordRadius(node);
    }

    if (t === "RECTANGLE" || t === "ELLIPSE" || t === "POLYGON" || t === "STAR" || t === "VECTOR") {
      recordRadius(node);
    }

    if (t === "TEXT") {
      recordText(node);
    }
  }
}

// Collect from text styles (deduplicated by style name)
for (const style of figma.getLocalTextStyles()) {
  const fs = style.fontSize;
  if (typeof fs === "number") fontSize.push(fs);

  const ff2 = style.fontName;
  if (ff2 && typeof ff2.style === "string") {
    const fw = parseFontWeight(ff2.style);
    if (fw !== null) fontWeight.push(fw);
  }

  const ff = style.fontName;
  if (ff && typeof ff.family === "string") fontFamily.push(ff.family);

  const lh = style.lineHeight;
  if (lh && lh.unit === "PIXELS" && typeof lh.value === "number") lineHeight.push(lh.value);

  const ls = style.letterSpacing;
  if (ls && ls.unit === "PIXELS" && typeof ls.value === "number") letterSpacing.push(ls.value);
}

return {
  scanned_pages: figma.root.children.length,
  scanned_nodes: scannedNodes,
  spacing,
  radius,
  stroke_width: strokeWidth,
  font_size: fontSize,
  font_weight: fontWeight,
  font_family: fontFamily,
  line_height: lineHeight,
  letter_spacing: letterSpacing,
  opacity,
};
