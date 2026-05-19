#!/bin/bash
# Bootstrap reference data for a fresh OPAL install.
#
# Loads:
#   - CCAM_FR codebook   (Procedure)  → keyword search via SourceValueCache + Mapping suggestions
#   - CIM10_FR codebook  (Condition)  → idem
#   - SapBERT mappings   (Procedure)  → auto-mapping suggestions
#
# Optionally rebuilds the SourceValueCache for a CDM so the FR labels are
# applied to the cache (otherwise Concept Explorer keyword search returns
# very few results).
#
# Usage:
#   ./scripts/reload_codebooks.sh                    # codebooks + SapBERT only
#   ./scripts/reload_codebooks.sh --cdm <cdm_name>   # also rebuild source-value-cache for that CDM
#
# Env:
#   OPAL_URL   default: http://localhost:8000
#   AUTH_TOKEN if set, sent as `Authorization: Bearer $AUTH_TOKEN` (needed when AUTH_ENABLED=true)

set -e

BASE_URL="${OPAL_URL:-http://localhost:8000}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

CDM_NAME=""
while [ $# -gt 0 ]; do
    case "$1" in
        --cdm) CDM_NAME="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

CURL_OPTS=(--noproxy '*' -s)
if [ -n "$AUTH_TOKEN" ]; then
    CURL_OPTS+=(-H "Authorization: Bearer $AUTH_TOKEN")
fi

echo "=== OPAL bootstrap ==="
echo "Backend: $BASE_URL"
[ -n "$CDM_NAME" ] && echo "Target CDM for cache rebuild: $CDM_NAME"
echo ""

# Wait for backend
echo "Waiting for backend..."
for i in $(seq 1 30); do
    if curl "${CURL_OPTS[@]}" "$BASE_URL/api/health" > /dev/null 2>&1; then
        echo "Backend is up."
        break
    fi
    sleep 2
done

upload_codebook() {
    local name="$1" domain="$2" file="$3"
    if [ ! -f "$file" ]; then
        echo "SKIP $name: $file not found"
        return
    fi
    echo "Loading $name ($(wc -l < "$file") rows from $(basename "$file"))..."
    curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/mapping/reference/upload" \
        -F "name=$name" \
        -F "domain=$domain" \
        -F "file=@$file" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} codes loaded')" \
      2>/dev/null || echo "  FAILED"
}

upload_codebook "CCAM_FR"  "Procedure" "$PROJECT_DIR/scripts/ccam_fr.csv"
upload_codebook "CIM10_FR" "Condition" "$PROJECT_DIR/scripts/cim10_fr.csv"

# SapBERT mappings (Procedure)
SAPBERT="$PROJECT_DIR/data/sapbert_results.csv"
if [ -f "$SAPBERT" ]; then
    echo ""
    echo "Loading SapBERT Procedure mappings ($(wc -l < "$SAPBERT") rows)..."
    curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/mapping/sapbert/upload" \
        -F "domain=Procedure" \
        -F "file=@$SAPBERT" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} mappings loaded')" \
      2>/dev/null || echo "  FAILED"
else
    echo "SKIP SapBERT: $SAPBERT not found"
fi

# Optional cache rebuild (per CDM)
if [ -n "$CDM_NAME" ]; then
    echo ""
    echo "Triggering SourceValueCache rebuild for CDM '$CDM_NAME'..."
    curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/concepts/source-value-cache/populate?cdm_name=$CDM_NAME" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Status: {d.get(\"status\",\"?\")}')" \
      2>/dev/null || echo "  FAILED"
    echo "  (poll progress: curl $BASE_URL/api/concepts/source-value-cache/status?cdm_name=$CDM_NAME)"
fi

echo ""
echo "=== Done ==="
