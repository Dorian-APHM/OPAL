#!/bin/bash
# Script to configure Keycloak LDAP after a fresh deploy
# Usage: LDAP_BIND_PASSWORD=xxx ./scripts/setup_keycloak.sh
#
# This script:
# 1. Waits for Keycloak to be ready
# 2. Deletes the placeholder LDAP component (from realm JSON import)
# 3. Recreates it via API with the real bind credential
#
# The realm JSON imports roles, client, protocol mappers, and a placeholder
# LDAP config (with CHANGE_ME as bind credential). This script replaces it
# with a working config.

set -e

KC_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="opal"

# LDAP settings (APHM Active Directory)
LDAP_URL="${LDAP_URL:-ldap://ldap-rodc.aphm.ap-hm.fr:389}"
LDAP_BIND_DN="${LDAP_BIND_DN:-CN=REDACTED,OU=POOL,OU=USERS,OU=APHM,DC=aphm,DC=ap-hm,DC=fr}"
LDAP_USERS_DN="${LDAP_USERS_DN:-OU=USERS,OU=APHM,DC=aphm,DC=ap-hm,DC=fr}"

if [ -z "$LDAP_BIND_PASSWORD" ]; then
    echo "ERROR: LDAP_BIND_PASSWORD is required"
    echo "Usage: LDAP_BIND_PASSWORD=xxx ./scripts/setup_keycloak.sh"
    exit 1
fi

echo "=== OPAL Keycloak Setup ==="
echo "Keycloak URL: $KC_URL"
echo "LDAP URL: $LDAP_URL"
echo ""

# Wait for Keycloak to be ready
echo "Waiting for Keycloak..."
for i in $(seq 1 60); do
    if curl -s --noproxy '*' "$KC_URL/realms/master" > /dev/null 2>&1; then
        echo "Keycloak is up!"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Keycloak did not start in time"
        exit 1
    fi
    sleep 2
done

# Get admin token
get_token() {
    curl -s --noproxy '*' -X POST "$KC_URL/realms/master/protocol/openid-connect/token" \
        -d "client_id=admin-cli&username=admin&password=admin&grant_type=password" \
        | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
}

TOKEN=$(get_token)

# Get realm internal ID
REALM_ID=$(curl -s --noproxy '*' "$KC_URL/admin/realms/$REALM" \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Realm ID: $REALM_ID"

# Delete any existing LDAP components
echo ""
echo "Cleaning existing LDAP providers..."
EXISTING=$(curl -s --noproxy '*' \
    "$KC_URL/admin/realms/$REALM/components?type=org.keycloak.storage.UserStorageProvider" \
    -H "Authorization: Bearer $TOKEN")

echo "$EXISTING" | python3 -c "
import sys, json
comps = json.load(sys.stdin)
for c in comps:
    print(f'  Found: {c[\"name\"]} ({c[\"id\"]})')
" 2>/dev/null

# Delete each one
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

# Create LDAP component with real credentials
echo ""
echo "Creating LDAP provider..."
TOKEN=$(get_token)

HTTP_CODE=$(curl -s --noproxy '*' -X POST "$KC_URL/admin/realms/$REALM/components" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -w "%{http_code}" \
    -o /dev/null \
    -d "{
    \"name\": \"ldap-aphm\",
    \"providerId\": \"ldap\",
    \"providerType\": \"org.keycloak.storage.UserStorageProvider\",
    \"parentId\": \"$REALM_ID\",
    \"config\": {
        \"vendor\": [\"ad\"],
        \"connectionUrl\": [\"$LDAP_URL\"],
        \"bindDn\": [\"$LDAP_BIND_DN\"],
        \"bindCredential\": [\"$LDAP_BIND_PASSWORD\"],
        \"usersDn\": [\"$LDAP_USERS_DN\"],
        \"usernameLDAPAttribute\": [\"cn\"],
        \"rdnLDAPAttribute\": [\"cn\"],
        \"uuidLDAPAttribute\": [\"objectGUID\"],
        \"userObjectClasses\": [\"person, organizationalPerson, user\"],
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

# Test LDAP connection
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
    echo "  (This may be normal if not on APHM network)"
fi

echo ""
echo "=== Keycloak setup complete ==="
echo ""
echo "You can now:"
echo "  1. Login with admin/admin at the OPAL app"
echo "  2. LDAP users can login with their APHM credentials"
echo "  3. Use the OPAL Users page to manage access requests"
