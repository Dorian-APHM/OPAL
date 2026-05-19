#!/bin/bash
# =============================================================================
# OPAL — Keycloak LDAP federation setup (EXAMPLE)
# =============================================================================
#
# Configures the `ldap-<site>` user federation provider in the `opal` realm,
# via Keycloak's Admin REST API. Idempotent: deletes any existing LDAP
# provider before recreating it, so you can rerun this script to rotate a
# bind credential or change settings.
#
# -----------------------------------------------------------------------------
# How to use
# -----------------------------------------------------------------------------
#
# 1. Copy this file (do NOT edit the example):
#
#       cp scripts/setup_keycloak.example.sh scripts/setup_keycloak.sh
#       chmod +x scripts/setup_keycloak.sh
#
# 2. Edit `scripts/setup_keycloak.sh` and replace every `CHANGEME_*` default
#    with values for your LDAP/AD directory. Ask your directory team for:
#       - LDAP/AD URL (host + port, ldap:// or ldaps://)
#       - Bind DN — preferably a dedicated read-only service account
#       - Users base DN (the OU containing user entries)
#
# 3. Run it, passing the bind password via env var (never hardcode secrets):
#
#       LDAP_BIND_PASSWORD='your_bind_password' ./scripts/setup_keycloak.sh
#
# 4. To rotate the bind password later, just rerun step 3 with the new value.
#    The existing provider is deleted and recreated cleanly.
#
# -----------------------------------------------------------------------------
# Prerequisites
# -----------------------------------------------------------------------------
#
#   - Keycloak container (`opal-keycloak`) running and reachable at $KC_URL
#   - The `opal` realm exists (auto-imported from keycloak/opal-realm.json)
#   - $KEYCLOAK_ADMIN_PASSWORD env var set (same value as in your .env)
#
# -----------------------------------------------------------------------------
# Security notes
# -----------------------------------------------------------------------------
#
#   - Never commit your real `setup_keycloak.sh` — it's git-ignored.
#   - Never pass the bind password as a CLI argument (visible in `ps`/history).
#   - Prefer a dedicated read-only service account over a personal account:
#     if your personal password expires, federation breaks for everyone.
#   - For production, use ldaps:// (port 636) and set `startTls` accordingly,
#     and consider importing your CA into Keycloak's truststore.
#
# =============================================================================

set -e

KC_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="${KEYCLOAK_REALM:-opal}"
ADMIN_USER="${KEYCLOAK_ADMIN:-admin}"

# LDAP / Active Directory settings — REPLACE THESE
LDAP_PROVIDER_NAME="${LDAP_PROVIDER_NAME:-ldap-corp}"
LDAP_URL="${LDAP_URL:-ldap://CHANGEME_ldap.example.com:389}"
LDAP_BIND_DN="${LDAP_BIND_DN:-CN=CHANGEME_svc-keycloak,OU=Services,DC=example,DC=com}"
LDAP_USERS_DN="${LDAP_USERS_DN:-OU=Users,DC=example,DC=com}"
LDAP_VENDOR="${LDAP_VENDOR:-ad}"             # ad | rhds | edir | tivoli | other
LDAP_USERNAME_ATTR="${LDAP_USERNAME_ATTR:-cn}"
LDAP_UUID_ATTR="${LDAP_UUID_ATTR:-objectGUID}"
LDAP_USER_OBJECT_CLASSES="${LDAP_USER_OBJECT_CLASSES:-person, organizationalPerson, user}"

# Required secrets
if [ -z "$LDAP_BIND_PASSWORD" ]; then
    echo "ERROR: LDAP_BIND_PASSWORD is required"
    echo "Usage: LDAP_BIND_PASSWORD=xxx ./scripts/setup_keycloak.sh"
    exit 1
fi
if [ -z "$KEYCLOAK_ADMIN_PASSWORD" ]; then
    echo "ERROR: KEYCLOAK_ADMIN_PASSWORD is required (the Keycloak master admin password)"
    echo "Tip: export it from your .env, e.g.  set -a && source .env && set +a"
    exit 1
fi

# Refuse to run with unedited placeholders
case "$LDAP_URL$LDAP_BIND_DN$LDAP_USERS_DN" in
    *CHANGEME*)
        echo "ERROR: LDAP_URL / LDAP_BIND_DN / LDAP_USERS_DN still contain placeholders."
        echo "Edit this script (or export the env vars) with real values before running."
        exit 1
        ;;
esac

echo "=== OPAL Keycloak LDAP setup ==="
echo "Keycloak URL : $KC_URL"
echo "Realm        : $REALM"
echo "Provider     : $LDAP_PROVIDER_NAME"
echo "LDAP URL     : $LDAP_URL"
echo "Bind DN      : $LDAP_BIND_DN"
echo "Users DN     : $LDAP_USERS_DN"
echo ""

# Wait for Keycloak
echo "Waiting for Keycloak..."
for i in $(seq 1 60); do
    if curl -s --noproxy '*' "$KC_URL/realms/master" > /dev/null 2>&1; then
        echo "Keycloak is up."
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Keycloak did not become reachable at $KC_URL"
        exit 1
    fi
    sleep 2
done

get_token() {
    curl -s --noproxy '*' -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
        --data-urlencode "client_id=admin-cli" \
        --data-urlencode "username=$ADMIN_USER" \
        --data-urlencode "password=$KEYCLOAK_ADMIN_PASSWORD" \
        --data-urlencode "grant_type=password" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}

TOKEN=$(get_token)
if [ -z "$TOKEN" ]; then
    echo "ERROR: could not obtain admin token (check KEYCLOAK_ADMIN_PASSWORD)"
    exit 1
fi

REALM_ID=$(curl -s --noproxy '*' "$KC_URL/admin/realms/$REALM" \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Realm internal ID: $REALM_ID"

# Delete any existing UserStorageProvider components in this realm
echo ""
echo "Cleaning existing LDAP providers..."
EXISTING=$(curl -s --noproxy '*' \
    "$KC_URL/admin/realms/$REALM/components?type=org.keycloak.storage.UserStorageProvider" \
    -H "Authorization: Bearer $TOKEN")

echo "$EXISTING" | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    print(f'  Found: {c[\"name\"]} ({c[\"id\"]})')
" 2>/dev/null

echo "$EXISTING" | python3 -c "
import sys, json
for c in json.load(sys.stdin):
    print(c['id'])
" 2>/dev/null | while read -r comp_id; do
    if [ -n "$comp_id" ]; then
        curl -s --noproxy '*' -X DELETE "$KC_URL/admin/realms/$REALM/components/$comp_id" \
            -H "Authorization: Bearer $(get_token)"
        echo "  Deleted: $comp_id"
    fi
done

# Create the LDAP federation
echo ""
echo "Creating LDAP provider '$LDAP_PROVIDER_NAME'..."
TOKEN=$(get_token)

HTTP_CODE=$(curl -s --noproxy '*' -X POST "$KC_URL/admin/realms/$REALM/components" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -w "%{http_code}" \
    -o /dev/null \
    -d "{
    \"name\": \"$LDAP_PROVIDER_NAME\",
    \"providerId\": \"ldap\",
    \"providerType\": \"org.keycloak.storage.UserStorageProvider\",
    \"parentId\": \"$REALM_ID\",
    \"config\": {
        \"vendor\": [\"$LDAP_VENDOR\"],
        \"connectionUrl\": [\"$LDAP_URL\"],
        \"bindDn\": [\"$LDAP_BIND_DN\"],
        \"bindCredential\": [\"$LDAP_BIND_PASSWORD\"],
        \"usersDn\": [\"$LDAP_USERS_DN\"],
        \"usernameLDAPAttribute\": [\"$LDAP_USERNAME_ATTR\"],
        \"rdnLDAPAttribute\": [\"$LDAP_USERNAME_ATTR\"],
        \"uuidLDAPAttribute\": [\"$LDAP_UUID_ATTR\"],
        \"userObjectClasses\": [\"$LDAP_USER_OBJECT_CLASSES\"],
        \"editMode\": [\"READ_ONLY\"],
        \"authType\": [\"simple\"],
        \"searchScope\": [\"2\"],
        \"importEnabled\": [\"true\"],
        \"syncRegistrations\": [\"false\"],
        \"fullSyncPeriod\": [\"-1\"],
        \"changedSyncPeriod\": [\"-1\"],
        \"pagination\": [\"false\"],
        \"connectionPooling\": [\"false\"],
        \"startTls\": [\"false\"],
        \"enabled\": [\"true\"],
        \"trustEmail\": [\"false\"],
        \"validatePasswordPolicy\": [\"false\"],
        \"useKerberosForPasswordAuthentication\": [\"false\"],
        \"allowKerberosAuthentication\": [\"false\"],
        \"usePasswordModifyExtendedOp\": [\"false\"],
        \"useTruststoreSpi\": [\"always\"],
        \"cachePolicy\": [\"DEFAULT\"],
        \"priority\": [\"0\"]
    }
}")

if [ "$HTTP_CODE" = "201" ]; then
    echo "  OK: LDAP provider created"
else
    echo "  FAILED: HTTP $HTTP_CODE"
    exit 1
fi

# Test connection
echo ""
echo "Testing LDAP connection..."
TOKEN=$(get_token)
TEST_CODE=$(curl -s --noproxy '*' -X POST "$KC_URL/admin/realms/$REALM/testLDAPConnection" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -w "%{http_code}" \
    -o /dev/null \
    -d "{
    \"action\": \"testConnection\",
    \"connectionUrl\": \"$LDAP_URL\",
    \"bindDn\": \"$LDAP_BIND_DN\",
    \"bindCredential\": \"$LDAP_BIND_PASSWORD\",
    \"authType\": \"simple\",
    \"useTruststoreSpi\": \"always\",
    \"startTls\": \"false\"
}")

if [ "$TEST_CODE" = "204" ]; then
    echo "  OK: LDAP connection successful"
else
    echo "  WARNING: LDAP connection test returned HTTP $TEST_CODE"
    echo "  (This may be normal if you are not on the LDAP network — check Keycloak logs.)"
fi

echo ""
echo "=== Done ==="
echo "Next steps:"
echo "  1. Open Keycloak admin console → realm '$REALM' → User federation"
echo "     and verify '$LDAP_PROVIDER_NAME' is listed."
echo "  2. Optionally trigger a full sync from the UI, or via API:"
echo "       POST $KC_URL/admin/realms/$REALM/user-storage/<provider-id>/sync?action=triggerFullSync"
echo "  3. Test login at the OPAL app with a directory user."
