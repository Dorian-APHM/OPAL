#!/bin/bash
# Upload a reference codebook OR a SapBERT mapping file to OPAL.
#
# Exactly one of --referentiel / --mapping must be provided.
#
# Usage:
#   # Upload a reference codebook (CCAM_FR, CIM10_FR, custom...)
#   OPAL_USER=admin OPAL_PASSWORD='<your-password>' \
#   ./scripts/reload_codebooks.sh --referentiel /path/to/ccam_fr.csv --domaine Procedure [--nom CCAM_FR]
#
#   # Upload a SapBERT mapping file
#   OPAL_USER=admin OPAL_PASSWORD='<your-password>' \
#   ./scripts/reload_codebooks.sh --mapping /path/to/sapbert_results.csv --domaine Procedure
#
# Notes:
#   * --domaine is required (Procedure | Condition | Drug | ...).
#   * --nom is optional for --referentiel; defaults to the file basename
#     (e.g. ccam_fr.csv → CCAM_FR). Used to group entries — re-uploading
#     with the same --nom replaces previous rows.
#   * The CSV upload endpoint auto-detects delimiter (,/;) and column names.
#     Accepted code columns:        ccam | code_ccam | code_cim | cim | code_acte | code
#     Accepted description columns: description | libelle | label | nom | designation
#     Fallback: first two columns are treated as (code, description).
#
# Auth: by default the script fetches a Keycloak token using
# OPAL_USER / OPAL_PASSWORD via the `opal-cli` client (Direct Access Grants).
# You can also pre-fetch a token yourself and pass it via AUTH_TOKEN.
#
# Env:
#   OPAL_URL       default: http://localhost:8000
#   KEYCLOAK_URL   default: http://localhost:8080
#   KEYCLOAK_REALM default: opal
#   KEYCLOAK_CLIENT_ID default: opal-cli
#   OPAL_USER / OPAL_PASSWORD   Keycloak credentials for password grant
#   AUTH_TOKEN     pre-fetched bearer token (overrides OPAL_USER/OPAL_PASSWORD)

set -e

BASE_URL="${OPAL_URL:-http://localhost:8000}"
KC_URL="${KEYCLOAK_URL:-http://localhost:8080}"
KC_REALM="${KEYCLOAK_REALM:-opal}"
KC_CLIENT="${KEYCLOAK_CLIENT_ID:-opal-cli}"

MODE=""
FILE=""
DOMAIN=""
NAME=""

usage() {
    sed -n '2,/^set -e$/p' "$0" | sed 's|^# \?||'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --referentiel)
            [ -n "$MODE" ] && { echo "ERROR: --referentiel and --mapping are mutually exclusive" >&2; exit 1; }
            MODE="reference"; FILE="$2"; shift 2 ;;
        --mapping)
            [ -n "$MODE" ] && { echo "ERROR: --referentiel and --mapping are mutually exclusive" >&2; exit 1; }
            MODE="mapping"; FILE="$2"; shift 2 ;;
        --domaine|--domain) DOMAIN="$2"; shift 2 ;;
        --nom|--name)       NAME="$2";   shift 2 ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown arg: $1" >&2; usage 1 ;;
    esac
done

if [ -z "$MODE" ]; then
    echo "ERROR: one of --referentiel or --mapping is required" >&2
    usage 1
fi
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
    echo "ERROR: file not found: $FILE" >&2
    exit 1
fi
if [ -z "$DOMAIN" ]; then
    echo "ERROR: --domaine is required" >&2
    usage 1
fi

# Default --nom from basename (CCAM_FR for ccam_fr.csv) when uploading a reference.
if [ "$MODE" = "reference" ] && [ -z "$NAME" ]; then
    BASENAME=$(basename "$FILE")
    NAME=$(echo "${BASENAME%.*}" | tr '[:lower:]' '[:upper:]')
fi

# Auto-fetch a Keycloak token if AUTH_TOKEN is not set but OPAL_USER/OPAL_PASSWORD are.
if [ -z "$AUTH_TOKEN" ] && [ -n "$OPAL_USER" ] && [ -n "$OPAL_PASSWORD" ]; then
    echo "Fetching token from Keycloak ($KC_URL, realm=$KC_REALM, client=$KC_CLIENT)..."
    TOKEN_JSON=$(curl --noproxy '*' -s -X POST \
        "$KC_URL/realms/$KC_REALM/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=password" \
        -d "client_id=$KC_CLIENT" \
        --data-urlencode "username=$OPAL_USER" \
        --data-urlencode "password=$OPAL_PASSWORD") || TOKEN_JSON=""
    AUTH_TOKEN=$(printf '%s' "$TOKEN_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")
    if [ -z "$AUTH_TOKEN" ]; then
        echo "ERROR: failed to fetch token. Keycloak response:" >&2
        echo "$TOKEN_JSON" >&2
        exit 1
    fi
    echo "  OK: token fetched."
fi

CURL_OPTS=(--noproxy '*' -s)
[ -n "$AUTH_TOKEN" ] && CURL_OPTS+=(-H "Authorization: Bearer $AUTH_TOKEN")

# Wait for backend
echo "Waiting for backend at $BASE_URL..."
for _ in $(seq 1 30); do
    if curl "${CURL_OPTS[@]}" "$BASE_URL/api/health" > /dev/null 2>&1; then
        echo "Backend is up."
        break
    fi
    sleep 2
done

ROWS=$(wc -l < "$FILE")

if [ "$MODE" = "reference" ]; then
    echo "Uploading reference '$NAME' (domain=$DOMAIN) from $FILE ($ROWS rows)..."
    RESP=$(curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/mapping/reference/upload" \
        -F "name=$NAME" \
        -F "domain=$DOMAIN" \
        -F "file=@$FILE")
    echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\",\"?\")} codes loaded')" 2>/dev/null \
        || { echo "  FAILED: $RESP" >&2; exit 1; }
else
    echo "Uploading SapBERT mapping (domain=$DOMAIN) from $FILE ($ROWS rows)..."
    RESP=$(curl "${CURL_OPTS[@]}" -X POST "$BASE_URL/api/mapping/sapbert/upload" \
        -F "domain=$DOMAIN" \
        -F "file=@$FILE")
    echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  OK: {d.get(\"count\",\"?\")} mappings loaded')" 2>/dev/null \
        || { echo "  FAILED: $RESP" >&2; exit 1; }
fi
