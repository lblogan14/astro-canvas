#!/usr/bin/env bash
# Acceptance for the lab-server tier (design 12): `docker compose up` serves the app over
# HTTPS, two users log in, each gets their own workspace, and only the admin sees the Manager.
#
# Run from the repository root:
#     deploy/tests/compose.sh            # build, test, tear down
#     KEEP=1 deploy/tests/compose.sh     # leave the stack running to poke at it
#
# Everything is checked through Caddy's TLS endpoint, so the certificate, the proxy headers,
# the Secure cookie and the WebSocket upgrade are all part of what passes or fails here.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/compose.yaml"
HTTPS_PORT="${HTTPS_PORT:-8443}"
HTTP_PORT="${HTTP_PORT:-8080}"
BASE="https://localhost:${HTTPS_PORT}"
ADMIN_EMAIL="pi@example.org"
MEMBER_EMAIL="student@example.org"
PASSWORD="a good long phrase"
JAR_DIR="$(mktemp -d)"

export CANVAS_DOMAIN=localhost
export CANVAS_TLS=internal
export POSTGRES_PASSWORD="compose-test-$RANDOM"
export ADMIN_EMAILS="$ADMIN_EMAIL"
export HTTPS_PORT HTTP_PORT

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# Caddy's local CA is self-signed on purpose; -k is the point of the test, not a shortcut.
api() { curl -sk --max-time 30 "$@"; }

cleanup() {
  local status=$?
  if [ "${KEEP:-0}" != "1" ]; then
    echo "--- logs (app) ---" >&2
    compose logs --no-color --tail 60 app >&2 || true
    compose down -v --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$JAR_DIR"
  exit "$status"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

step() { echo "==> $*"; }

step "building and starting the stack"
compose up -d --build --wait --wait-timeout 600

step "waiting for HTTPS to answer"
for _ in $(seq 1 60); do
  if api -o /dev/null -w '%{http_code}' "$BASE/api/health" | grep -q '^200$'; then
    break
  fi
  sleep 2
done
health="$(api "$BASE/api/health")"
echo "    $health"
echo "$health" | grep -q '"status":"ok"' || fail "no healthy app behind TLS"

step "the certificate is served by Caddy, not by uvicorn"
api -o /dev/null -D - "$BASE/api/health" | grep -qi '^strict-transport-security' \
  || fail "no HSTS header: the request did not go through Caddy"

step "the server reports user accounts"
info="$(api "$BASE/api/auth/info")"
echo "    $info"
echo "$info" | grep -q '"mode":"users"' || fail "the app is not in users mode"

step "anonymous requests are refused"
code="$(api -o /dev/null -w '%{http_code}' "$BASE/api/workflows")"
[ "$code" = "401" ] || fail "GET /api/workflows returned $code, expected 401"

register() {
  api -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/register" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$PASSWORD\"}"
}

login() { # login <email> <jar>
  api -c "$2" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/login" \
    --data-urlencode "username=$1" --data-urlencode "password=$PASSWORD"
}

step "registering two accounts"
for email in "$ADMIN_EMAIL" "$MEMBER_EMAIL"; do
  code="$(register "$email")"
  case "$code" in
    201 | 400) echo "    $email -> $code" ;;
    *) fail "register $email returned $code" ;;
  esac
done

step "both log in and the cookie is Secure"
for pair in "admin:$ADMIN_EMAIL" "member:$MEMBER_EMAIL"; do
  who="${pair%%:*}"
  email="${pair#*:}"
  code="$(login "$email" "$JAR_DIR/$who.jar")"
  case "$code" in
    200 | 204) ;;
    *) fail "login $email returned $code" ;;
  esac
  grep -q 'astro_canvas_auth' "$JAR_DIR/$who.jar" || fail "no session cookie for $email"
  # curl writes TRUE in the "secure" column of its cookie jar.
  grep 'astro_canvas_auth' "$JAR_DIR/$who.jar" | grep -qi 'TRUE' \
    || fail "the session cookie for $email is not Secure"
done

step "each user sees only their own workspace"
admin_ws="$(api -b "$JAR_DIR/admin.jar" "$BASE/api/workspace")"
member_ws="$(api -b "$JAR_DIR/member.jar" "$BASE/api/workspace")"
admin_root="$(echo "$admin_ws" | sed -n 's/.*"root":"\([^"]*\)".*/\1/p')"
member_root="$(echo "$member_ws" | sed -n 's/.*"root":"\([^"]*\)".*/\1/p')"
echo "    admin  $admin_root"
echo "    member $member_root"
[ -n "$admin_root" ] && [ -n "$member_root" ] || fail "no workspace root reported"
[ "$admin_root" != "$member_root" ] || fail "both users share one workspace"
echo "$member_ws" | grep -q '"can_select":false' || fail "a user can repoint the workspace"

step "a workflow saved by one user is invisible to the other"
saved="$(api -b "$JAR_DIR/member.jar" -X POST "$BASE/api/workflows" \
  -H 'Content-Type: application/json' \
  -d '{"id":"wf-compose","name":"Member work","nodes":{},"edges":{}}')"
echo "$saved" | grep -q 'wf-compose' || fail "the member could not save a workflow"
code="$(api -b "$JAR_DIR/admin.jar" -o /dev/null -w '%{http_code}' "$BASE/api/workflows/wf-compose")"
[ "$code" = "404" ] || fail "the admin can read another user's workflow ($code)"

step "the manager is admin-only"
code="$(api -b "$JAR_DIR/member.jar" -o /dev/null -w '%{http_code}' "$BASE/api/manager/packs")"
[ "$code" = "403" ] || fail "a member reached /api/manager/packs ($code)"
packs="$(api -b "$JAR_DIR/admin.jar" "$BASE/api/manager/packs")"
echo "$packs" | grep -q '"name":"core"' || fail "the admin cannot list packs"

step "the accounts live in Postgres, not in a workspace file"
compose exec -T db psql -U canvas -d canvas -tAc 'select count(*) from users' | grep -qE '^[2-9]' \
  || fail "the users table is not in Postgres"

step "the packs loaded and uv is reachable inside the image"
compose exec -T app astro-canvas doctor | tee /dev/stderr | grep -q 'all checks passed' \
  || fail "astro-canvas doctor is not green in the image"

step "the app refuses a public bind without accounts"
if compose exec -T -e ASTRO_CANVAS_AUTH=token app astro-canvas serve 2>&1 | grep -q 'auth users'; then
  echo "    refused, as it should"
else
  fail "the guard did not refuse --host 0.0.0.0 with --auth token"
fi

echo
echo "OK: HTTPS, two isolated users, admin-only manager, Postgres accounts."
