// read_typography_audit.js
// Read-only typography audit: local text styles + text node usage across all pages.
// No writes to Figma.

const textStyles = [];
const typographyUsage = [];

// ---- Helpers ----------------------------------------------------------------

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

function extractTypoProps(source) {
  const fontName = source.fontName;
  const family = (fontName && typeof fontName.family === "string") ? fontName.family : null;
  const style  = (fontName && typeof fontName.style === "string")  ? fontName.style  : null;

  const rawFontSize = source.fontSize;
  const fontSizeVal = (typeof rawFontSize === "number") ? rawFontSize : null;

  const fontWeightVal = style ? parseFontWeight(style) : null;

  const lh = source.lineHeight;
  let lineHeightVal = null;
  if (lh) {
    if (lh.unit === "PIXELS" && typeof lh.value === "number") lineHeightVal = lh.value;
    else if (lh.unit === "PERCENT" && typeof lh.value === "number") lineHeightVal = lh.value + "%";
    else if (lh.unit === "AUTO") lineHeightVal = "AUTO";
  }

  const ls = source.letterSpacing;
  let letterSpacingVal = null;
  if (ls) {
    if (ls.unit === "PIXELS" && typeof ls.value === "number") letterSpacingVal = ls.value;
    else if (ls.unit === "PERCENT" && typeof ls.value === "number") letterSpacingVal = ls.value + "%";
  }

  return {
    fontFamily: family,
    fontStyle: style,
    fontSize: fontSizeVal,
    fontWeight: fontWeightVal,
    lineHeight: lineHeightVal,
    letterSpacing: letterSpacingVal,
  };
}

// ---- 1. Local text styles ---------------------------------------------------

for (const style of figma.getLocalTextStyles()) {
  const props = extractTypoProps(style);
  textStyles.push({
    id: style.id,
    name: style.name,
    key: style.key,
    description: style.description || "",
    ...props,
  });
}

// ---- 2. Text node usage across all pages -----------------------------------

// Combination key → usage count
const combinationMap = {};

let scannedNodes = 0;

for (const page of figma.root.children) {
  const nodes = page.findAll(n => n.type === "TEXT");
  for (const node of nodes) {
    scannedNodes++;
    const props = extractTypoProps(node);
    const key = [
      props.fontFamily   || "",
      props.fontStyle    || "",
      props.fontSize     !== null ? String(props.fontSize) : "",
      props.fontWeight   !== null ? String(props.fontWeight) : "",
      props.lineHeight   !== null ? String(props.lineHeight) : "",
      props.letterSpacing !== null ? String(props.letterSpacing) : "",
    ].join("|");

    if (combinationMap[key] === undefined) {
      combinationMap[key] = { ...props, usageCount: 0 };
    }
    combinationMap[key].usageCount++;
  }
}

// Flatten map to array, sorted by usageCount desc
for (const entry of Object.values(combinationMap)) {
  typographyUsage.push(entry);
}
typographyUsage.sort((a, b) => b.usageCount - a.usageCount);

// ---- Result ----------------------------------------------------------------

return {
  text_styles: textStyles,
  typography_usage: typographyUsage,
  summary: {
    text_style_count: textStyles.length,
    unique_typography_combinations: typographyUsage.length,
    scanned_text_nodes: scannedNodes,
  },
};
