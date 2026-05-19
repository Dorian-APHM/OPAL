#!/bin/bash
# Bootstrap reference data for an OPAL install.
#
# Loads codebooks + SapBERT mappings into OPAL, then optionally rebuilds the
# SourceValueCache for a CDM so the FR labels are applied to the cache
# (otherwise Concept Explorer keyword search returns very few results).
#
# Reference files are NOT shipped with OPAL — you provide them. The CSV
# upload endpoint auto-detects delimiter (,/;) and column names. Accepted:
#   code column:        ccam | code_ccam | code_cim | cim | code_acte | code
#   description column: description | libelle | label | nom | designation
# If no header matches, the first two columns are used (code, description).
#
# Usage:
#   ./scripts/reload_codebooks.sh \
#     --ccam-fr  /path/to/ccam_fr.csv \
#     --cim10-fr /path/to/cim10_fr.csv \
#     --sapbert  /path/to/sapbert_results.csv \
#     --cdm      <cdm_name>
#
# All arguments are optional — missing files are skipped. Without --cdm,
# the SourceValueCache rebuild step is skipped.
#
# Env:
#   OPAL_URL    default: http://localhost:8000
#   AUTH_TOKEN  if set, sent as `Authorization: Bearer $AUTH_TOKEN` (when
#               AUTH_ENABLED=true in the backend)

set -e

BASE_URL="${OPAL_URL:-http://localhost:8000}"
CCAM_FR_FILE=""
CIM10_FR_FILE=""
SAPBERT_FILE=""
CDM_NAME=""

while [ $# -gt 0 ]; do
    case "$1" in
        --ccam-fr)  CCAM_FR_FILE="$2";  shift 2 ;;
        --cim10-fr) CIM10_FR_FILE="$2"; shift 2 ;;
        --sapbert)  SAPBERT_FILE="$2";  shift 2 ;;
        --cdm)      CDM_NAME="$2";      shift 2 ;;
        -h|--help)
            sed -n '2,/^set -e$/p' "$0" | sed 's|^# \?||'
            exit 0
            ;;
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
    if [ -z "$file" ]; then
        return
    fi
    if [ ! -f "$file" ]; then
        echo "SKIP $name: file not found ($file)"
        return
    fi
    echo "Loading $name from $file ($(wc -l < "$file") rows)..."
    curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/mapping/reference/upload" \
        -F "name=$name" \
        -F "domain=$domain" \
        -F "file=@$file" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} codes loaded')" \
      2>/dev/null || echo "  FAILED"
}

upload_codebook "CCAM_FR"  "Procedure" "$CCAM_FR_FILE"
upload_codebook "CIM10_FR" "Condition" "$CIM10_FR_FILE"

# SapBERT (Procedure)
if [ -n "$SAPBERT_FILE" ]; then
    if [ -f "$SAPBERT_FILE" ]; then
        echo ""
        echo "Loading SapBERT Procedure mappings from $SAPBERT_FILE ($(wc -l < "$SAPBERT_FILE") rows)..."
        curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/mapping/sapbert/upload" \
            -F "domain=Procedure" \
            -F "file=@$SAPBERT_FILE" \
          | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\", \"?\")} mappings loaded')" \
          2>/dev/null || echo "  FAILED"
    else
        echo "SKIP SapBERT: file not found ($SAPBERT_FILE)"
    fi
fi

# Optional cache rebuild
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
