#!/usr/bin/env bash
# Foundryx EMS blue/green orchestration. Run on the server from the repo root
# (the dir holding docker-compose.yml + .env + .active_color).
#
# Single public domain (no extra DNS): Caddy fronts everything, auto-TLS.
#   UI  -> https://${APP_DOMAIN}/            -> reverse_proxy active frontend port
#   API -> https://${APP_DOMAIN}${BACKEND_PATH}/* -> strip prefix -> active backend port
# Frontend + backend share one host (api calls are same-origin); the backend
# lives under ${BACKEND_PATH} (default /be) which Caddy's handle_path strips, so
# the backend still sees root paths (/auth/login, /public/avatars/...). The
# backend's own absolute URLs are correct because PUBLIC_BASE_URL carries the
# prefix. The swap = rewrite the Caddy fragment to the new color's ports + reload.
#
# Container loopback ports alternate per color. This platform shares the host
# with the dreamz EMS stack (which owns 8000/8010/3001/3011), so foundryx-shared-
# service uses a DISTINCT range:
#   blue:  backend 127.0.0.1:8200 | frontend 127.0.0.1:3200
#   green: backend 127.0.0.1:8210 | frontend 127.0.0.1:3210
#
# Required env: IMAGE_TAG (git SHA, set by CI), APP_DOMAIN, TLS_EMAIL.
# Active color in .active_color (defaults to blue on first run).
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root containing docker-compose.yml
: "${IMAGE_TAG:?must be set to the git SHA pushed by CI}"
: "${APP_DOMAIN:?must be set (the single domain, e.g. icp-demo.foundryx.my)}"
: "${TLS_EMAIL:?must be set (Caddy ACME email)}"
BACKEND_PATH="${BACKEND_PATH:-/be}"   # path prefix the backend is served under
export IMAGE_TAG

# REDIS_PASSWORD: ONE reader used by the pre-flight check below and by the Redis
# authentication steps. Environment first (as compose resolves it), else the last
# REDIS_PASSWORD= line of .env. It is only ever read as text, never evaluated, and
# never printed. Prints nothing when unset.
read_redis_password() {
  local v="${REDIS_PASSWORD:-}"
  if [ -z "$v" ] && [ -f .env ]; then
    v=$(grep -E '^REDIS_PASSWORD=' .env | tail -n 1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/" || true)
  fi
  printf '%s' "$v"
}

# Pre-flight, before the first docker compose call: the value is embedded in
# REDIS_URL, so it must be present, at least 32 characters, and URL-safe
# ([A-Za-z0-9_-]). A bad value would otherwise fail after the swap, or leak part
# of itself into a log. The value is never echoed.
REDIS_PW=$(read_redis_password)
if [ -z "$REDIS_PW" ]; then
  echo "::error::REDIS_PASSWORD is not set in the environment or .env - aborting before any container is touched" >&2
  exit 1
fi
if [ "${#REDIS_PW}" -lt 32 ]; then
  echo "::error::REDIS_PASSWORD is shorter than 32 characters - use: openssl rand -hex 32 (aborting before any container is touched)" >&2
  exit 1
fi
if ! [[ "$REDIS_PW" =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "::error::REDIS_PASSWORD contains characters outside [A-Za-z0-9_-] (it is embedded in a URL) - use: openssl rand -hex 32 (aborting before any container is touched)" >&2
  exit 1
fi
REDIS_WAIT_TICKS="${REDIS_WAIT_TICKS:-15}"   # 15 * 2s = 30s for redis to load its AOF and answer

# `docker compose exec ... redis-cli ping`, bounded by `timeout` when the host
# has it. Authenticated ping, password via REDISCLI_AUTH (never a command-line
# argument). Always exits 0; the caller inspects the reply.
_exec_timeout=()
if command -v timeout >/dev/null 2>&1; then _exec_timeout=(timeout 15); fi
redis_ping() {
  REDISCLI_AUTH="$REDIS_PW" ${_exec_timeout[@]+"${_exec_timeout[@]}"} docker compose exec -T -e REDISCLI_AUTH redis redis-cli ping </dev/null 2>&1 || true
}

# Caddy: the script rewrites CADDY_SITE_FILE (a self-contained fragment with both
# site blocks pointing at the active color) then reloads CADDY_CONFIG. The main
# Caddyfile must `import` the fragment (see DEPLOY.md). If foundryx is the ONLY site,
# set CADDY_SITE_FILE=CADDY_CONFIG=/etc/caddy/Caddyfile.
CADDY_SITE_FILE="${CADDY_SITE_FILE:-/etc/caddy/foundryx.caddy}"
CADDY_CONFIG="${CADDY_CONFIG:-/etc/caddy/Caddyfile}"
DRAIN_SECONDS="${DRAIN_SECONDS:-30}"
# Health budget for the NEW colour = sorento-crm's 4 minutes (issue #89). The
# API container runs bootstrap_db (core + module migrations + seed) before
# gunicorn; start.sh retries it BOOTSTRAP_ATTEMPTS times under a lock_timeout,
# then exits non-zero. Past this budget, or on the first crash of the new
# colour, the deploy aborts with a NAMED error and the old colour keeps serving.
HEALTH_WAIT_TICKS="${HEALTH_WAIT_TICKS:-120}"   # 120 * 2s = 4 min max
WORKER_WAIT_TICKS="${WORKER_WAIT_TICKS:-45}"    # 45 * 2s = 90s for each celery container to prove it started
TICK_SECONDS=2

ACTIVE=$(cat .active_color 2>/dev/null || echo blue)
if [ "$ACTIVE" = "blue" ]; then
  NEW=green; OLD=blue
  NEW_BE_PORT=8210; NEW_FE_PORT=3210
else
  NEW=blue;  OLD=green
  NEW_BE_PORT=8200; NEW_FE_PORT=3200
fi

echo "==> Active=${ACTIVE} New=${NEW} IMAGE_TAG=${IMAGE_TAG}"

# SKIP_MIGRATIONS=1 is the ONLY bypass of the container-start bootstrap (and it
# does not bypass the module schema drift guard: an API or worker whose module
# schema is BEHIND its code still refuses to start). Say so loudly when set.
if [ "${SKIP_MIGRATIONS:-0}" = "1" ] || grep -qE '^SKIP_MIGRATIONS=1' .env 2>/dev/null; then
  echo "::warning::SKIP_MIGRATIONS=1 - the ${NEW} API will NOT run bootstrap_db. It still refuses to start if a module schema is behind its code (ModuleSchemaDrift)."
fi

# Named abort for a NEW colour that never became healthy: dump its logs, STOP it
# (a crash-looping container would otherwise re-run bootstrap, and its blocked
# DDL, against the live database on every restart), never touch Caddy.
abort_new_color() {
  local svc="$1" reason="$2"
  echo "::error::DEPLOY ABORTED (${svc}_${NEW} ${reason}). Swap NOT performed - ${OLD} keeps serving. Module migration lock timeout? See DEPLOY.md 'Module migration lock timeout'." >&2
  docker compose logs --tail=200 "${svc}_${NEW}" || true
  docker compose --profile "${NEW}" stop "backend_${NEW}" "frontend_${NEW}" || true
  exit 1
}

# 1. Pull new images for the incoming color + the shared backend image (workers).
echo "==> Pulling images"
docker compose --profile "${NEW}" pull "backend_${NEW}" "frontend_${NEW}"
docker compose pull worker_workflow worker_jobs worker_omni beat

# 1b. Ensure shared infra is up (db/redis/pgbackups are profile-less, NOT
#     blue/green). The color is started with --no-deps below, so its depends_on
#     does NOT auto-start these - without this the API container waits on `db`
#     forever ("db not ready"). Idempotent: already-running = no-op.
#
#     A change to the compose NETWORK definition (the pinned ipam subnet for the
#     Sorento SQL relay, 2026-09-04) makes compose recreate
#     foundryx_ss_network, which is impossible while the live color, the
#     workers or a stale orphan still hold endpoints on it: `up -d` STOPS
#     db/redis/pgbackups first, then dies on "has active endpoints", and the
#     retry finds redis "not connected to the network" - production left
#     without its database (run 34011403918, 2026-09-06). So: try the normal
#     no-op path; if it fails with the network-recreate signature, take the
#     whole stack down ONCE (every profile, orphans included, so nothing holds
#     the old network), then bring infra up on the recreated network and
#     continue the normal blue/green flow. A brief full outage, only on the
#     deploy that changes the network; later deploys never enter this branch.
#     Any other failure still aborts here, before a color is touched.
#
#     Redis is started with --no-recreate: a running redis is left exactly as it
#     is until the clients have moved to the password URL (steps 2-7); it is then
#     recreated with its password in step 7b. db and pgbackups behave as before.
echo "==> Ensuring infra (db/redis/pgbackups) is up"
NETWORK_RECREATE_SIGNATURE='has active endpoints|is not connected to the network|needs to be recreated'
if ! infra_out=$({ docker compose up -d db pgbackups && docker compose up -d --no-recreate redis; } 2>&1); then
  echo "$infra_out"
  if grep -qE "$NETWORK_RECREATE_SIGNATURE" <<<"$infra_out"; then
    echo "==> Network recreate pending: taking the whole stack down once (brief full outage)"
    docker compose --profile blue --profile green down --remove-orphans
    docker compose up -d db pgbackups
    docker compose up -d --no-recreate redis
  else
    echo "::error::infra up failed for a reason other than a pending network recreate - aborting before touching any color"
    exit 1
  fi
else
  echo "$infra_out"
fi

# 1c. Rotation guard. The infra step never recreates a running redis, so if the
#     REDIS_PASSWORD secret was changed, redis still holds the previous value and
#     every client on the new URL would be refused. An authenticated ping that
#     is answered WRONGPASS stops the deploy here, before any color moves (see
#     DEPLOY.md "Rotating REDIS_PASSWORD"). An open server (no password yet)
#     answers PONG and passes. Redis still starting is waited for; any other
#     failure does not abort here, the later steps catch a dead redis.
echo "==> Checking the redis password"
chk_reply=""; chk_i=0
while [ "$chk_i" -lt "$REDIS_WAIT_TICKS" ]; do
  chk_reply=$(redis_ping)
  if grep -qE 'PONG|WRONGPASS' <<<"$chk_reply"; then break; fi
  sleep $TICK_SECONDS; chk_i=$((chk_i + 1))
done
if grep -q 'WRONGPASS' <<<"$chk_reply"; then
  echo "::error::DEPLOY ABORTED (the running redis rejected REDIS_PASSWORD with WRONGPASS). No color was touched. Add the new password to the live redis first: see DEPLOY.md 'Rotating REDIS_PASSWORD' (ACL SETUSER default >NEW), then redeploy." >&2
  exit 1
fi
if ! grep -q 'PONG' <<<"$chk_reply"; then
  echo "::warning::redis did not answer within $((REDIS_WAIT_TICKS * TICK_SECONDS))s - the early password check could not run; continuing (later steps verify redis)" >&2
fi

# 2. Bring up the new color. The API container's start.sh runs
#    `python -m scripts.bootstrap_db` (alembic upgrade + seed + modules) before
#    gunicorn, so it only goes healthy once schema is at HEAD. A migration
#    failure exits the container → healthcheck never passes → step 3 aborts and
#    the OLD color keeps serving. SKIP_MIGRATIONS=1 (backend env) bypasses.
echo "==> Starting ${NEW} color"
docker compose --profile "${NEW}" up -d --no-deps "backend_${NEW}" "frontend_${NEW}"

# 3. Wait for both new containers to report healthy. A container that EXITS or
#    restarts is a failed bootstrap (start.sh already retried inside it) or a
#    ModuleSchemaDrift refusal: abort at once instead of burning the budget.
echo "==> Waiting for healthchecks"
for svc in backend frontend; do
  cid=$(docker compose ps -q "${svc}_${NEW}")
  if [ -z "$cid" ]; then
    abort_new_color "$svc" "container not found"
  fi
  i=0; state=starting
  while [ "$i" -lt "$HEALTH_WAIT_TICKS" ]; do
    state=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)
    if [ "$state" = "healthy" ]; then
      echo "    ${svc}_${NEW} healthy after $((i * TICK_SECONDS))s"; break
    fi
    status=$(docker inspect --format='{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)
    restarts=$(docker inspect --format='{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)
    if [ "$status" = "exited" ] || [ "$status" = "dead" ] || [ "$restarts" -gt 0 ]; then
      abort_new_color "$svc" "exited during start (status=${status} restarts=${restarts}) - bootstrap_db failed or ModuleSchemaDrift"
    fi
    sleep $TICK_SECONDS; i=$((i + 1))
  done
  if [ "$state" != "healthy" ]; then
    abort_new_color "$svc" "not healthy after $((HEALTH_WAIT_TICKS * TICK_SECONDS))s"
  fi
done

# 4. Swap Caddy to the new color (rewrite fragment + graceful reload).
echo "==> Swapping Caddy to ${NEW} (frontend:${NEW_FE_PORT} backend:${NEW_BE_PORT} under ${BACKEND_PATH})"
TMP_CADDY=$(mktemp)
cat > "$TMP_CADDY" <<EOF
# Managed by blue_green_deploy.sh - do not edit by hand. Active color: ${NEW}.
${APP_DOMAIN} {
	# Claude connector OAuth discovery (RFC 9728 / RFC 8414 path insertion): for
	# the resource/issuer ${BACKEND_PATH}/mcp/<p> an MCP client asks the host ROOT
	# for /.well-known/oauth-*${BACKEND_PATH}/mcp/<p>. Forward those to the backend
	# UNSTRIPPED (it checks the prefix against its public base URL).
	@connector_wellknown path /.well-known/oauth-authorization-server${BACKEND_PATH}/* /.well-known/oauth-protected-resource${BACKEND_PATH}/*
	handle @connector_wellknown {
		reverse_proxy 127.0.0.1:${NEW_BE_PORT} {
			header_up Host {host}
		}
	}
	# Backend under ${BACKEND_PATH} - handle_path STRIPS the prefix so the
	# backend receives root paths (/auth/login, /public/avatars/...).
	# (Caddy already sets X-Forwarded-For/Proto/Host upstream; only Host needs
	# overriding to the public host so tenant resolution + links are correct.)
	handle_path ${BACKEND_PATH}/* {
		reverse_proxy 127.0.0.1:${NEW_BE_PORT} {
			header_up Host {host}
		}
	}
	# Everything else -> frontend (Next pages + /api/auth NextAuth).
	handle {
		reverse_proxy 127.0.0.1:${NEW_FE_PORT} {
			header_up Host {host}
		}
	}
	encode gzip
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer-when-downgrade"
	}
	tls ${TLS_EMAIL}
}
EOF
sudo install -m 0644 "$TMP_CADDY" "$CADDY_SITE_FILE"
rm -f "$TMP_CADDY"
sudo caddy validate --config "$CADDY_CONFIG" --adapter caddyfile
sudo caddy reload --config "$CADDY_CONFIG" --adapter caddyfile

# 5. Drain - let nginx finish in-flight requests on the OLD color.
echo "==> Draining ${DRAIN_SECONDS}s"
sleep "$DRAIN_SECONDS"

# 6. Recreate the Celery workers + beat on the new image (brief background-job
#    blip; safe - tasks pull atomically off Redis). Only reached once the NEW
#    API colour is healthy, i.e. migrations already ran via the API container,
#    so these skip bootstrap (command override in start.sh). Each worker/beat
#    runs the module schema drift guard at start and exits if a module schema
#    is behind its code.
echo "==> Recreating Celery workers + beat on new image"
docker compose up -d --force-recreate --no-deps worker_workflow worker_jobs worker_omni beat

# 6b. Health-gate the celery containers (sorento-crm pattern: a positive
#     startup line, not just "the process exists"). They have no HTTP
#     healthcheck. A worker must log Celery's "celery@<host> ready." line,
#     which prints only AFTER worker_init (the drift guard) passed and the
#     broker connected. Beat has no later startup line than its guard, so it
#     must stay running with zero restarts for 5 consecutive ticks. Any
#     restart/exit fails the gate. A failure here is AFTER the swap: ${NEW}
#     serves, ${OLD} is left running (step 7 not reached) for a rollback.
worker_gate_failed() {
  local svc="$1" cid="$2" reason="$3"
  echo "::error::DEPLOY FAILED AFTER SWAP (${svc} ${reason}). ${NEW} is serving; ${OLD} left running for rollback: IMAGE_TAG=<previous sha> ./scripts/blue_green_deploy.sh (a MODULE schema ahead of the old image is skipped with a warning; a rollback across a CORE migration fails its bootstrap - see DEPLOY.md 'Rollback')" >&2
  docker logs --tail=120 "$cid" || true
  exit 1
}
echo "==> Verifying Celery containers"
for svc in worker_workflow worker_jobs worker_omni beat; do
  cid=$(docker compose ps -q "$svc")
  if [ -z "$cid" ]; then echo "::error::DEPLOY FAILED AFTER SWAP (${svc} not found after recreate)" >&2; exit 1; fi
  i=0; ok=""; up_ticks=0
  while [ $i -lt "$WORKER_WAIT_TICKS" ]; do
    status=$(docker inspect --format='{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)
    restarts=$(docker inspect --format='{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)
    if [ "$restarts" -gt 0 ] || { [ "$status" != "running" ] && [ "$status" != "created" ]; }; then
      worker_gate_failed "$svc" "$cid" "unhealthy: status=${status} restarts=${restarts} - ModuleSchemaDrift or a boot error"
    fi
    if [ "$svc" = "beat" ]; then
      if [ "$status" = "running" ]; then up_ticks=$((up_ticks + 1)); fi
      if [ "$up_ticks" -ge 5 ]; then ok=1; echo "    $svc running (no restarts for ${up_ticks} ticks)"; break; fi
    else
      # Capture first, then match: `docker logs | grep` under pipefail can die
      # of SIGPIPE (141) when grep stops at the first match, reading a
      # started worker as "never ready" (a false post-swap failure).
      logs=$(docker logs "$cid" 2>&1 || true)
      if grep -qE 'celery@[^ ]+ ready\.' <<<"$logs"; then
        ok=1; echo "    $svc ready after $((i * TICK_SECONDS))s"; break
      fi
    fi
    sleep $TICK_SECONDS; i=$((i + 1))
  done
  if [ -z "$ok" ]; then
    worker_gate_failed "$svc" "$cid" "did not prove startup within $((WORKER_WAIT_TICKS * TICK_SECONDS))s"
  fi
done

# 7. Stop + remove the OLD color (tolerate first deploy where it doesn't exist).
echo "==> Stopping ${OLD} color"
docker compose stop "backend_${OLD}" "frontend_${OLD}" || true
docker compose rm -f "backend_${OLD}" "frontend_${OLD}" || true

# 7a. Persist the new active color NOW. The swap already happened (step 4) and
#     the old color is gone, so ${NEW} is what is really serving. Writing it
#     after the Redis check instead would leave a stale file on a failed check,
#     and the next deploy would target the live color in place instead of
#     swapping.
echo "${NEW}" > .active_color

# 7b. Apply the Redis password. Only now: every client already uses the
#     `redis://default:<password>@` URL, which works with or without a password
#     on the server, so recreating redis here cannot lock anyone out. Clients
#     reconnect within seconds; the append-only file keeps queued tasks.
echo "==> Recreating redis with its password"
docker compose up -d redis

# 7c. Prove it. Authenticated PING must return PONG and an unauthenticated one
#     must be refused. The password travels in REDISCLI_AUTH (never on a command
#     line, never echoed), read by the same helper as the pre-flight check.
REDIS_PW=$(read_redis_password)
if [ -z "$REDIS_PW" ]; then
  echo "::error::REDIS_PASSWORD is not set in the environment or .env - cannot verify redis authentication" >&2
  exit 1
fi
echo "==> Verifying redis authentication"
auth_reply=""; i=0
while [ "$i" -lt "$REDIS_WAIT_TICKS" ]; do
  auth_reply=$(REDISCLI_AUTH="$REDIS_PW" ${_exec_timeout[@]+"${_exec_timeout[@]}"} docker compose exec -T -e REDISCLI_AUTH redis redis-cli ping </dev/null 2>&1 || true)
  if grep -q 'PONG' <<<"$auth_reply"; then break; fi
  sleep $TICK_SECONDS; i=$((i + 1))
done
if ! grep -q 'PONG' <<<"$auth_reply"; then
  echo "::error::DEPLOY FAILED AFTER SWAP (redis did not answer an authenticated PING with PONG within $((REDIS_WAIT_TICKS * TICK_SECONDS))s). ${NEW} is serving; check redis logs and REDIS_PASSWORD." >&2
  exit 1
fi
noauth_reply=$(${_exec_timeout[@]+"${_exec_timeout[@]}"} docker compose exec -T redis redis-cli ping </dev/null 2>&1 || true)
if grep -q 'PONG' <<<"$noauth_reply"; then
  echo "::error::DEPLOY FAILED AFTER SWAP (redis accepted an unauthenticated PING, so its password is not applied). ${NEW} is serving." >&2
  exit 1
fi
if ! grep -q 'NOAUTH' <<<"$noauth_reply"; then
  echo "::error::DEPLOY FAILED AFTER SWAP (the unauthenticated redis check could not run: no NOAUTH refusal was returned). ${NEW} is serving; check redis logs." >&2
  exit 1
fi
echo "    redis authenticated PING ok, unauthenticated refused"

# 8. Prune dangling images.
docker image prune -f >/dev/null || true

echo "==> Deploy complete. Active=${NEW}"
