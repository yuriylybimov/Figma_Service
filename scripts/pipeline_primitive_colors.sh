#!/usr/bin/env bash
set -euo pipefail

PYTHON=".venv/bin/python"
RUN="$PYTHON run.py"
TOKENS="tokens"

usage() {
  echo "Usage: bash scripts/pipeline_primitive_colors.sh [-f FIGMA_URL]"
  echo ""
  echo "Runs the full primitive color pipeline (dry-run sync only):"
  echo "  1. read color-usage-summary"
  echo "  2. plan primitive-colors-from-project"
  echo "  3. plan primitive-colors-normalized"
  echo "  4. plan validate-normalized"
  echo "  5. sync primitive-colors-normalized --dry-run --verbose"
  echo ""
  echo "Options:"
  echo "  -f FIGMA_URL   Figma file URL (overrides FIGMA_FILE_URL env var)"
  echo "  -h, --help     Show this help message"
  exit 0
}

FILE_FLAG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) FILE_FLAG="-f $2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

mkdir -p "$TOKENS"
[[ -f "$TOKENS/overrides.normalized.json" ]] || echo '{}' > "$TOKENS/overrides.normalized.json"
[[ -f "$TOKENS/overrides.merge.json"      ]] || echo '{}' > "$TOKENS/overrides.merge.json"

echo "=== Step 1: read color-usage-summary ==="
$RUN read color-usage-summary $FILE_FLAG --out "$TOKENS/color_usage_summary.json"

echo ""
echo "=== Step 2: plan primitive-colors-from-project ==="
$RUN plan primitive-colors-from-project \
  --usage "$TOKENS/color_usage_summary.json" \
  --out   "$TOKENS/primitives.proposed.json"

echo ""
echo "=== Step 3: plan primitive-colors-normalized ==="
$RUN plan primitive-colors-normalized \
  --proposed  "$TOKENS/primitives.proposed.json" \
  --overrides "$TOKENS/overrides.normalized.json" \
  --merge     "$TOKENS/overrides.merge.json" \
  --out       "$TOKENS/primitives.normalized.json"

echo ""
echo "=== Step 4: plan validate-normalized ==="
$RUN plan validate-normalized \
  --normalized "$TOKENS/primitives.normalized.json"

echo ""
echo "=== Step 5: sync dry-run ==="
$RUN sync primitive-colors-normalized $FILE_FLAG \
  --normalized "$TOKENS/primitives.normalized.json" \
  --dry-run \
  --verbose
