#!/bin/sh
set -e

export PATH=/home/appuser/.local/bin:$PATH

# ── Wait for Postgres ──────────────────────────────────────────────────────
# Parse host:port out of DATABASE_URL (postgresql://user:pass@host:port/db).
DB_HOST_PORT=$(echo "${DATABASE_URL}" | sed -n 's|.*@\([^/]*\)/.*|\1|p')
DB_HOST=$(echo "${DB_HOST_PORT}" | cut -d: -f1)
DB_PORT=$(echo "${DB_HOST_PORT}" | cut -d: -f2)
[ -z "$DB_HOST" ] && DB_HOST="db"
[ -z "$DB_PORT" ] && DB_PORT="5432"

echo "Waiting for Postgres at ${DB_HOST}:${DB_PORT}..."
until pg_isready -h "${DB_HOST}" -p "${DB_PORT}" >/dev/null 2>&1; do
  echo "  db not ready, retrying..."
  sleep 2
done
echo "  db accepting connections"

# ── Worker / beat reuse this image via a command override ──────────────────
# (e.g. `celery -A app.workflow_engine.worker worker`). They must NOT run the
# DB bootstrap — blue/green orchestration owns schema upgrades via the API
# container alone, so we never double-run migrations/seed from a worker.
if [ $# -gt 0 ]; then
  echo "Running override command: $@"
  exec "$@"
fi

# ── API container: canonical idempotent bootstrap ───────────────────────────
# `scripts.bootstrap_db` = ensure role/db → alembic upgrade head → seed →
# bootstrap_modules. Idempotent + alembic advisory-locked, so a concurrent
# blue/green start no-ops. Failure here aborts container start → healthcheck
# fails → blue/green swap aborts → old color keeps serving. SKIP_MIGRATIONS=1
# bypasses for manual expand-contract rollouts.
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  echo "Running DB bootstrap (migrations + seed + modules)..."
  python -m scripts.bootstrap_db
else
  echo "SKIP_MIGRATIONS=1; skipping bootstrap_db"
fi

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8001}"

echo "Starting FastAPI (gunicorn/UvicornWorker) on ${API_HOST}:${API_PORT}..."
exec python -m gunicorn app.main:app \
  --workers "${WORKERS:-4}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "${API_HOST}:${API_PORT}" \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
