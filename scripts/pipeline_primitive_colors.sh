#!/usr/bin/env bash
set -euo pipefail

PYTHON=".venv/bin/python"
RUN="$PYTHON run.py"
TOKENS="tokens"
DRY_RUN_ONLY=true
FRESH=false

step() { echo ""; echo "── Step $1: $2 [$(date +%H:%M:%S)] ──"; }

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
  echo "  --fresh        Write outputs to tokens/<timestamp>/ instead of tokens/"
  echo "  -h, --help     Show this help message"
  exit 0
}

if [[ -f ".env" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "$key" ]] && continue
    export "$key=$value"
  done < .env
fi

FILE_FLAG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f) FILE_FLAG="-f $2"; shift 2 ;;
    --fresh) FRESH=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

[[ -x "$PYTHON" ]] || { echo "ERROR: $PYTHON not found or not executable. Run from project root after: python -m venv .venv && pip install -e ."; exit 1; }
[[ -f "run.py"  ]] || { echo "ERROR: run.py not found. Must run from Figma_Service project root."; exit 1; }
[[ -n "$FILE_FLAG" || -n "${FIGMA_FILE_URL:-}" ]] \
  || { echo "ERROR: No Figma URL. Pass -f URL or set FIGMA_FILE_URL in .env"; exit 1; }

if [[ "$FRESH" == "true" ]]; then
  TOKENS="tokens/$(date +%Y%m%d_%H%M%S)"
  mkdir -p "$TOKENS"
  [[ -f "tokens/overrides.normalized.json" ]] \
    && cp "tokens/overrides.normalized.json" "$TOKENS/overrides.normalized.json" \
    || echo '{}' > "$TOKENS/overrides.normalized.json"
  [[ -f "tokens/overrides.merge.json" ]] \
    && cp "tokens/overrides.merge.json" "$TOKENS/overrides.merge.json" \
    || echo '{}' > "$TOKENS/overrides.merge.json"
else
  mkdir -p "$TOKENS"
  [[ -f "$TOKENS/overrides.normalized.json" ]] || echo '{}' > "$TOKENS/overrides.normalized.json"
  [[ -f "$TOKENS/overrides.merge.json"      ]] || echo '{}' > "$TOKENS/overrides.merge.json"
fi

step 1 "read color-usage-summary"
$RUN read color-usage-summary $FILE_FLAG --out "$TOKENS/color_usage_summary.json"

step 2 "plan primitive-colors-from-project"
$RUN plan primitive-colors-from-project \
  --usage "$TOKENS/color_usage_summary.json" \
  --out   "$TOKENS/primitives.proposed.json"

step 3 "plan primitive-colors-normalized"
$RUN plan primitive-colors-normalized \
  --proposed  "$TOKENS/primitives.proposed.json" \
  --overrides "$TOKENS/overrides.normalized.json" \
  --merge     "$TOKENS/overrides.merge.json" \
  --out       "$TOKENS/primitives.normalized.json"

step 4 "plan validate-normalized"
$RUN plan validate-normalized \
  --normalized "$TOKENS/primitives.normalized.json"

step 5 "sync dry-run"
[[ "$DRY_RUN_ONLY" == "true" ]] || { echo "ERROR: DRY_RUN_ONLY safety check failed. Aborting."; exit 1; }
$RUN sync primitive-colors-normalized $FILE_FLAG \
  --normalized "$TOKENS/primitives.normalized.json" \
  --dry-run \
  --verbose

echo ""
echo "══════════════════════════════════════════════"
echo "  Pipeline complete (dry-run — no Figma writes)"
echo "══════════════════════════════════════════════"
echo "  Artifacts: $TOKENS/"
echo "    color_usage_summary.json"
echo "    primitives.proposed.json"
echo "    primitives.normalized.json"
echo ""
echo "  To apply changes to Figma, run manually:"
echo "    $RUN sync primitive-colors-normalized \\"
echo "      --normalized $TOKENS/primitives.normalized.json"
echo "══════════════════════════════════════════════"
