#!/bin/sh
set -e

export PATH=/home/appuser/.local/bin:$PATH

# Make the app root importable regardless of launch method. The API starts via
# `python -m …` which puts the CWD (/app) on sys.path, so `import app` AND
# `import modules.*` both work. The Celery workers/beat, however, run as a
# console-script (`exec celery …` below) which does NOT add the CWD - so
# `import modules.omnichannel.*` raised `ModuleNotFoundError: No module named
# 'modules'` in the worker, breaking module bootstrap + the storage-migration
# location registration (silently on old code; loudly since sprint-4/12). Pin it
# here so every container - API and workers - resolves both packages.
export PYTHONPATH="/app${PYTHONPATH:+:$PYTHONPATH}"

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
# DB bootstrap - blue/green orchestration owns schema upgrades via the API
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
  # bootstrap_db sets a lock_timeout (see _apply_bootstrap_lock_timeout) so a
  # lock held by the still-live (blue) color makes a migration/seed FAIL FAST
  # instead of hanging the whole ~300s healthcheck window and aborting the swap.
  # Retry a few times: a TRANSIENT lock (a live query that finishes) clears
  # between attempts and the deploy still goes green. A PERSISTENT lock exhausts
  # the retries → container start aborts (the old color keeps serving) with a
  # NAMED lock_timeout error in the log - diagnosable, not a silent hang.
  BOOTSTRAP_ATTEMPTS="${BOOTSTRAP_ATTEMPTS:-5}"
  BOOTSTRAP_RETRY_DELAY="${BOOTSTRAP_RETRY_DELAY:-8}"
  n=1
  until python -m scripts.bootstrap_db; do
    if [ "$n" -ge "$BOOTSTRAP_ATTEMPTS" ]; then
      echo "ERROR: bootstrap_db failed after ${n} attempts (a lock held by the live color, or a real error above). Aborting start so the current color keeps serving." >&2
      exit 1
    fi
    echo "bootstrap_db attempt ${n}/${BOOTSTRAP_ATTEMPTS} failed; retrying in ${BOOTSTRAP_RETRY_DELAY}s..." >&2
    n=$((n + 1))
    sleep "$BOOTSTRAP_RETRY_DELAY"
  done
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
