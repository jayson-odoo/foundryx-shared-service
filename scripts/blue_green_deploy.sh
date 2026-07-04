#!/usr/bin/env bash
# FoundryX EMS blue/green orchestration. Run on the server from the repo root
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
# Container loopback ports alternate per color (3000/php taken by ecohub on
# this host, so blue uses 3001/8000):
#   blue:  backend 127.0.0.1:8000 | frontend 127.0.0.1:3001
#   green: backend 127.0.0.1:8010 | frontend 127.0.0.1:3011
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

# Caddy: the script rewrites CADDY_SITE_FILE (a self-contained fragment with both
# site blocks pointing at the active color) then reloads CADDY_CONFIG. The main
# Caddyfile must `import` the fragment (see DEPLOY.md). If foundryx is the ONLY site,
# set CADDY_SITE_FILE=CADDY_CONFIG=/etc/caddy/Caddyfile.
CADDY_SITE_FILE="${CADDY_SITE_FILE:-/etc/caddy/foundryx.caddy}"
CADDY_CONFIG="${CADDY_CONFIG:-/etc/caddy/Caddyfile}"
DRAIN_SECONDS="${DRAIN_SECONDS:-30}"
HEALTH_WAIT_TICKS="${HEALTH_WAIT_TICKS:-150}"   # 150 * 2s = 5 min max (bootstrap_db runs on API start)
WORKER_WAIT_TICKS="${WORKER_WAIT_TICKS:-30}"    # 30 * 2s = 60s settle window for celery containers
TICK_SECONDS=2

ACTIVE=$(cat .active_color 2>/dev/null || echo blue)
if [ "$ACTIVE" = "blue" ]; then
  NEW=green; OLD=blue
  NEW_BE_PORT=8010; NEW_FE_PORT=3011
else
  NEW=blue;  OLD=green
  NEW_BE_PORT=8000; NEW_FE_PORT=3001
fi

echo "==> Active=${ACTIVE} New=${NEW} IMAGE_TAG=${IMAGE_TAG}"

# 1. Pull new images for the incoming color + the shared backend image (workers).
echo "==> Pulling images"
docker compose --profile "${NEW}" pull "backend_${NEW}" "frontend_${NEW}"
docker compose pull worker_workflow worker_omni beat

# 1b. Ensure shared infra is up (db/redis/pgbackups are profile-less, NOT
#     blue/green). The color is started with --no-deps below, so its depends_on
#     does NOT auto-start these — without this the API container waits on `db`
#     forever ("db not ready"). Idempotent: already-running = no-op.
echo "==> Ensuring infra (db/redis/pgbackups) is up"
docker compose up -d db redis pgbackups

# 2. Bring up the new color. The API container's start.sh runs
#    `python -m scripts.bootstrap_db` (alembic upgrade + seed + modules) before
#    gunicorn, so it only goes healthy once schema is at HEAD. A migration
#    failure exits the container → healthcheck never passes → step 3 aborts and
#    the OLD color keeps serving. SKIP_MIGRATIONS=1 (backend env) bypasses.
echo "==> Starting ${NEW} color"
docker compose --profile "${NEW}" up -d --no-deps "backend_${NEW}" "frontend_${NEW}"

# 3. Wait for both new containers to report healthy.
echo "==> Waiting for healthchecks"
for svc in backend frontend; do
  cid=$(docker compose ps -q "${svc}_${NEW}")
  if [ -z "$cid" ]; then
    echo "ERROR: container ${svc}_${NEW} not found"; exit 1
  fi
  i=0; state=starting
  while [ $i -lt $HEALTH_WAIT_TICKS ]; do
    state=$(docker inspect --format='{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)
    if [ "$state" = "healthy" ]; then
      echo "    ${svc}_${NEW} healthy after $((i * TICK_SECONDS))s"; break
    fi
    sleep $TICK_SECONDS; i=$((i + 1))
  done
  if [ "$state" != "healthy" ]; then
    echo "ERROR: ${svc}_${NEW} not healthy after $((HEALTH_WAIT_TICKS * TICK_SECONDS))s"
    docker compose logs --tail=200 "${svc}_${NEW}" || true
    exit 1
  fi
done

# 4. Swap Caddy to the new color (rewrite fragment + graceful reload).
echo "==> Swapping Caddy to ${NEW} (frontend:${NEW_FE_PORT} backend:${NEW_BE_PORT} under ${BACKEND_PATH})"
TMP_CADDY=$(mktemp)
cat > "$TMP_CADDY" <<EOF
# Managed by blue_green_deploy.sh — do not edit by hand. Active color: ${NEW}.
${APP_DOMAIN} {
	# Backend under ${BACKEND_PATH} — handle_path STRIPS the prefix so the
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

# 5. Drain — let nginx finish in-flight requests on the OLD color.
echo "==> Draining ${DRAIN_SECONDS}s"
sleep "$DRAIN_SECONDS"

# 6. Recreate the Celery workers + beat on the new image (brief background-job
#    blip; safe — tasks pull atomically off Redis). Migrations already ran via
#    the API container, so these skip bootstrap (command override in start.sh).
echo "==> Recreating Celery workers + beat on new image"
docker compose up -d --force-recreate --no-deps worker_workflow worker_omni beat

# 6b. Verify the celery containers settle (running, no crash-loop). They have no
#     HTTP healthcheck — liveness is the process + restart policy.
echo "==> Verifying Celery containers"
for svc in worker_workflow worker_omni beat; do
  cid=$(docker compose ps -q "$svc")
  if [ -z "$cid" ]; then echo "ERROR: $svc not found after recreate"; exit 1; fi
  i=0; ok=""
  while [ $i -lt "$WORKER_WAIT_TICKS" ]; do
    status=$(docker inspect --format='{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)
    restarts=$(docker inspect --format='{{.RestartCount}}' "$cid" 2>/dev/null || echo 0)
    if [ "$status" = "running" ] && [ "$restarts" -eq 0 ]; then
      sleep $TICK_SECONDS; i=$((i + 1))
      # require it to stay up for a few consecutive ticks
      if [ $i -ge 5 ]; then ok=1; echo "    $svc running"; break; fi
      continue
    fi
    if [ "$restarts" -gt 0 ] || { [ "$status" != "running" ] && [ "$status" != "created" ]; }; then
      echo "ERROR: $svc unhealthy (status=$status restarts=$restarts)"
      docker logs --tail=120 "$cid" || true; exit 1
    fi
    sleep $TICK_SECONDS; i=$((i + 1))
  done
  if [ -z "$ok" ]; then
    echo "ERROR: $svc did not settle within $((WORKER_WAIT_TICKS * TICK_SECONDS))s"
    docker logs --tail=120 "$cid" || true; exit 1
  fi
done

# 7. Stop + remove the OLD color (tolerate first deploy where it doesn't exist).
echo "==> Stopping ${OLD} color"
docker compose stop "backend_${OLD}" "frontend_${OLD}" || true
docker compose rm -f "backend_${OLD}" "frontend_${OLD}" || true

# 8. Persist new active color + prune dangling images.
echo "${NEW}" > .active_color
docker image prune -f >/dev/null || true

echo "==> Deploy complete. Active=${NEW}"
