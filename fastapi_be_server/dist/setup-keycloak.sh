#!/bin/sh

# Keycloak 초기 설정 스크립트
echo "Starting Keycloak initialization..."

# Keycloak이 완전히 시작될 때까지 대기
echo "Waiting for Keycloak to be ready..."
until curl -f http://keycloak:8080/ >/dev/null 2>&1; do
    echo "Keycloak is not ready yet. Waiting..."
    sleep 10
done

echo "Keycloak is ready! Starting setup..."

# 이미 설정이 완료되었는지 확인
REALM_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://keycloak:8080/admin/realms/likenovel)

if [ "$REALM_CHECK" = "200" ]; then
    echo "Realm 'likenovel' already exists. Skipping setup."
    exit 0
fi

# Keycloak 관리자 토큰 획득
echo "Getting admin token..."
KC_ADMIN_USERNAME="${KC_ADMIN_USERNAME:-admin}"
KC_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:-}"

if [ -z "$KC_ADMIN_PASSWORD" ]; then
    echo "[setup-keycloak.sh] ERROR: KC_ADMIN_PASSWORD is missing" >&2
    exit 1
fi

TOKEN_RESPONSE=$(curl -X POST http://keycloak:8080/realms/master/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${KC_ADMIN_USERNAME}" \
  -d "password=${KC_ADMIN_PASSWORD}" \
  -d "grant_type=password" \
  -d "client_id=admin-cli")

echo "Token response: $TOKEN_RESPONSE"

ADMIN_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys, json; 
try:
    data = json.load(sys.stdin)
    print(data.get('access_token', ''))
except Exception as e:
    print('Error parsing JSON:', e)
    sys.exit(1)
")

if [ -z "$ADMIN_TOKEN" ] || [ "$ADMIN_TOKEN" = "None" ]; then
    echo "Failed to get admin token"
    echo "Response was: $TOKEN_RESPONSE"
    exit 1
fi

echo "Admin token obtained successfully"

# likenovel realm 생성
echo "Creating realm 'likenovel'..."
REALM_RESPONSE=$(curl -s -w "%{http_code}" -X POST http://keycloak:8080/admin/realms \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "realm": "likenovel",
    "enabled": true,
    "verifyEmail": false,
    "displayName": "LikeNovel",
    "displayNameHtml": "<div class=\"kc-logo-text\"><span>LikeNovel</span></div>"
  }')

if echo "$REALM_RESPONSE" | grep -q "201"; then
    echo "Realm 'likenovel' created successfully"
else
    echo "Failed to create realm 'likenovel'"
    exit 1
fi

# service 클라이언트 생성 (일반 로그인용)
echo "Creating client 'service'..."
KC_CLIENT_SECRET="${KC_CLIENT_SECRET:-}"
if [ -z "$KC_CLIENT_SECRET" ]; then
    echo "[setup-keycloak.sh] ERROR: KC_CLIENT_SECRET is missing" >&2
    exit 1
fi

SERVICE_RESPONSE=$(curl -s -w "%{http_code}" -X POST http://keycloak:8080/admin/realms/likenovel/clients \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "service",
    "enabled": true,
    "publicClient": false,
    "clientAuthenticatorType": "client-secret",
    "secret": "'"$KC_CLIENT_SECRET"'",
    "redirectUris": ["http://localhost:8800/*", "http://cloud.aiaracorp.com:8800/*", "https://api.likenovel.net/*"],
    "webOrigins": ["http://localhost:3000", "http://cloud.aiaracorp.com:3001", "http://cloud.aiaracorp.com:3002", "http://cloud.aiaracorp.com:8800", "https://likenovel.net", "https://www.likenovel.net"],
    "standardFlowEnabled": true,
    "directAccessGrantsEnabled": true,
    "serviceAccountsEnabled": true,
    "authorizationServicesEnabled": true
  }')

if echo "$SERVICE_RESPONSE" | grep -q "201"; then
    echo "Client 'service' created successfully"
else
    echo "Failed to create client 'service'"
    exit 1
fi

# service-keep 클라이언트 생성 (자동 로그인용)
echo "Creating client 'service-keep'..."
KC_CLIENT_KEEP_SIGNIN_SECRET="${KC_CLIENT_KEEP_SIGNIN_SECRET:-}"
if [ -z "$KC_CLIENT_KEEP_SIGNIN_SECRET" ]; then
    echo "[setup-keycloak.sh] ERROR: KC_CLIENT_KEEP_SIGNIN_SECRET is missing" >&2
    exit 1
fi

KEEP_RESPONSE=$(curl -s -w "%{http_code}" -X POST http://keycloak:8080/admin/realms/likenovel/clients \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "service-keep",
    "enabled": true,
    "publicClient": false,
    "clientAuthenticatorType": "client-secret",
    "secret": "'"$KC_CLIENT_KEEP_SIGNIN_SECRET"'",
    "redirectUris": ["http://localhost:8800/*", "http://cloud.aiaracorp.com:8800/*", "https://api.likenovel.net/*"],
    "webOrigins": ["http://localhost:3000", "http://cloud.aiaracorp.com:3001", "http://cloud.aiaracorp.com:3002", "http://cloud.aiaracorp.com:8800", "https://likenovel.net", "https://www.likenovel.net"],
    "standardFlowEnabled": true,
    "directAccessGrantsEnabled": true,
    "serviceAccountsEnabled": true,
    "authorizationServicesEnabled": true
  }')

if echo "$KEEP_RESPONSE" | grep -q "201"; then
    echo "Client 'service-keep' created successfully"
else
    echo "Failed to create client 'service-keep'"
    echo "Response: $KEEP_RESPONSE"
    exit 1
fi

# 기본 사용자 역할 생성
echo "Creating role 'user'..."
USER_ROLE_RESPONSE=$(curl -s -w "%{http_code}" -X POST http://keycloak:8080/admin/realms/likenovel/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "user",
    "description": "Default user role"
  }')

if echo "$USER_ROLE_RESPONSE" | grep -q "201"; then
    echo "Role 'user' created successfully"
else
    echo "Failed to create role 'user'"
    echo "Response: $USER_ROLE_RESPONSE"
    exit 1
fi

# admin 역할 생성
echo "Creating role 'admin'..."
ADMIN_ROLE_RESPONSE=$(curl -s -w "%{http_code}" -X POST http://keycloak:8080/admin/realms/likenovel/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "admin",
    "description": "Administrator role"
  }')

if echo "$ADMIN_ROLE_RESPONSE" | grep -q "201"; then
    echo "Role 'admin' created successfully"
else
    echo "Failed to create role 'admin'"
    echo "Response: $ADMIN_ROLE_RESPONSE"
    exit 1
fi

# likenovel realm의 admin 계정에 모든 realm-management 역할 부여
# 1. likenovel realm에 admin 계정 생성
KC_LIKENOVEL_ADMIN_PASSWORD="${KC_LIKENOVEL_ADMIN_PASSWORD:-$KC_ADMIN_PASSWORD}"
ADMIN_USER_RESPONSE=$(curl -s -w "%{http_code}" -X POST http://keycloak:8080/admin/realms/likenovel/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "enabled": true,
    "emailVerified": true,
    "credentials": [{"type": "password", "value": "'"$KC_LIKENOVEL_ADMIN_PASSWORD"'", "temporary": false}]
  }')

# 2. likenovel realm의 admin 계정 id 조회
ADMIN_USER_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/users?username=admin" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys, json; users=json.load(sys.stdin); print(users[0]['id'] if users else '')")

# 3. realm-management 클라이언트 id 조회
REALM_MGMT_CLIENT_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients?clientId=realm-management" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys, json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')")

# 4. realm-management의 모든 역할 조회
REALM_MGMT_ROLES=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients/$REALM_MGMT_CLIENT_ID/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

# 5. 모든 역할을 admin 계정에 부여
curl -s -X POST "http://keycloak:8080/admin/realms/likenovel/users/$ADMIN_USER_ID/role-mappings/clients/$REALM_MGMT_CLIENT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$REALM_MGMT_ROLES"

echo "Granted all realm-management roles to admin user in likenovel realm."

# service 클라이언트의 service account에 realm-management 역할 부여
SERVICE_CLIENT_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients?clientId=service" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys, json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')")
SERVICE_ACCOUNT_USER_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients/$SERVICE_CLIENT_ID/service-account-user" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys, json; user=json.load(sys.stdin); print(user['id'])")

# realm-management 클라이언트 id 조회 (이미 위에서 REALM_MGMT_CLIENT_ID로 있음)
# manage-users, view-users, query-users 역할만 추출
MANAGE_USERS_ROLE=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients/$REALM_MGMT_CLIENT_ID/roles/manage-users" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
VIEW_USERS_ROLE=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients/$REALM_MGMT_CLIENT_ID/roles/view-users" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
QUERY_USERS_ROLE=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients/$REALM_MGMT_CLIENT_ID/roles/query-users" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

ROLES_JSON="[$MANAGE_USERS_ROLE,$VIEW_USERS_ROLE,$QUERY_USERS_ROLE]"

curl -s -X POST "http://keycloak:8080/admin/realms/likenovel/users/$SERVICE_ACCOUNT_USER_ID/role-mappings/clients/$REALM_MGMT_CLIENT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$ROLES_JSON"

echo "Granted realm-management roles to service client service-account-user."

# service-keep 클라이언트의 service account에도 동일하게 적용
KEEP_CLIENT_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients?clientId=service-keep" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys, json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')")
KEEP_ACCOUNT_USER_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients/$KEEP_CLIENT_ID/service-account-user" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys, json; user=json.load(sys.stdin); print(user['id'])")

curl -s -X POST "http://keycloak:8080/admin/realms/likenovel/users/$KEEP_ACCOUNT_USER_ID/role-mappings/clients/$REALM_MGMT_CLIENT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$ROLES_JSON"

echo "Granted realm-management roles to service-keep client service-account-user."


# admin-cli 클라이언트 ID 조회
ADMIN_CLI_ID=$(curl -s -X GET "http://keycloak:8080/admin/realms/master/clients?clientId=admin-cli" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['id'])")

# admin-cli 클라이언트 수정
KC_ADMIN_CLI_SECRET="${KC_ADMIN_CLI_SECRET:-}"
if [ -z "$KC_ADMIN_CLI_SECRET" ]; then
  echo "[setup-keycloak.sh] WARN: KC_ADMIN_CLI_SECRET is missing; skip updating admin-cli client secret"
else
curl -s -X PUT "http://keycloak:8080/admin/realms/master/clients/$ADMIN_CLI_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "admin-cli",
    "secret": "'"$KC_ADMIN_CLI_SECRET"'",
    "publicClient": false,
    "serviceAccountsEnabled": true,
    "enabled": true
  }'

echo "Updated 'admin-cli' client to use client secret"
fi


# 모든 Required Action Provider 리스트 가져오기
REQUIRED_ACTIONS=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/authentication/required-actions" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

# 모든 항목에서 id가 있는 경우 비활성화
DISABLE_ACTION_IDS=$(echo "$REQUIRED_ACTIONS" | python3 -c "
import sys, json
actions = json.load(sys.stdin)
for a in actions:
    if a.get('id'):
        print(a['id'])
")

for ID in $DISABLE_ACTION_IDS; do
  curl -s -X PUT "http://keycloak:8080/admin/realms/likenovel/authentication/required-actions/$ID" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"enabled": false}'
  echo "✅ Disabled required action ID: $ID"
done


echo "Disabling ALL required actions in realm 'likenovel' and overriding all clients with 'direct grant no otp' flow..."

# 모든 Required Action 비활성화
REQUIRED_ACTIONS=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/authentication/required-actions" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

echo "$REQUIRED_ACTIONS" | python3 -c "
import sys, json
actions = json.load(sys.stdin)
for a in actions:
    print(a['alias'])
" | while read -r ALIAS; do
  curl -s -X PUT "http://keycloak:8080/admin/realms/likenovel/authentication/required-actions/${ALIAS}" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"alias\": \"${ALIAS}\", \"enabled\": false}"
  echo "✅ Disabled required action: $ALIAS"
done

# # 모든 클라이언트에 direct grant flow 오버라이드
# CLIENTS=$(curl -s -X GET "http://keycloak:8080/admin/realms/likenovel/clients" \
#   -H "Authorization: Bearer $ADMIN_TOKEN")

# echo "$CLIENTS" | python3 -c "
# import sys, json
# for client in json.load(sys.stdin):
#     print(f'{client[\"id\"]}')
# " | while read CLIENT_ID; do
#   curl -s -X PUT "http://keycloak:8080/admin/realms/likenovel/clients/$CLIENT_ID" \
#     -H "Authorization: Bearer $ADMIN_TOKEN" \
#     -H "Content-Type: application/json" \
#     -d '{
#       "authenticationFlowBindingOverrides": {
#         "direct_grant": "direct grant no otp"
#       }
#     }'
#   echo "✅ Overridden client $CLIENT_ID with 'direct grant no otp'"
# done

echo "🎉 모든 Required Action 비활성화 및 Direct Grant Flow 오버라이드 완료"

echo "Keycloak setup completed successfully!"
echo "You can now access:"
echo "- Keycloak Admin Console: http://localhost:8080"
echo "- API Server: http://localhost:8800" 