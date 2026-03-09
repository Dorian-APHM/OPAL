#!/bin/bash
# Script to reload reference codebooks after a fresh deploy
# Usage: ./scripts/reload_codebooks.sh

set -e

BASE_URL="${OPAL_URL:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== OPAL Codebook Reload ==="
echo "Backend URL: $BASE_URL"
echo ""

# Wait for backend to be ready
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl -s --noproxy '*' "$BASE_URL/api/health" > /dev/null 2>&1; then
        echo "Backend is up!"
        break
    fi
    sleep 2
done

# Load CCAM EN (Athena scraped - English descriptions)
CCAM_EN="$PROJECT_DIR/ccam_athena.csv"
if [ -f "$CCAM_EN" ]; then
    echo ""
    echo "Loading CCAM_EN ($(wc -l < "$CCAM_EN") codes)..."
    curl -s --noproxy '*' -X POST "$BASE_URL/api/mapping/reference/upload" \
        -F "name=CCAM_EN" \
        -F "domain=Procedure" \
        -F "file=@$CCAM_EN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} codes loaded')" 2>/dev/null || echo "  FAILED"
else
    echo "SKIP: $CCAM_EN not found"
fi

# Load CCAM FR (Interhop - French descriptions)
CCAM_FR="$PROJECT_DIR/interhop-actes-ameli.csv"
if [ -f "$CCAM_FR" ]; then
    echo ""
    echo "Loading CCAM ($(wc -l < "$CCAM_FR") codes)..."
    curl -s --noproxy '*' -X POST "$BASE_URL/api/mapping/reference/upload" \
        -F "name=CCAM" \
        -F "domain=Procedure" \
        -F "file=@$CCAM_FR" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} codes loaded')" 2>/dev/null || echo "  FAILED"
else
    echo "SKIP: $CCAM_FR not found"
fi

# Load SapBERT pre-computed mappings (Procedure domain)
SAPBERT="$PROJECT_DIR/sapbert_results.csv"
if [ -f "$SAPBERT" ]; then
    echo ""
    echo "Loading SapBERT Procedure mappings ($(wc -l < "$SAPBERT") rows)..."
    curl -s --noproxy '*' -X POST "$BASE_URL/api/mapping/sapbert/upload" \
        -F "domain=Procedure" \
        -F "file=@$SAPBERT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} mappings loaded')" 2>/dev/null || echo "  FAILED"
else
    echo "SKIP: $SAPBERT not found"
fi

echo ""
echo "=== Done ==="
