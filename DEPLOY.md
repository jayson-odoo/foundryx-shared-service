# Foundryx Shared Service Platform - Deployment (CI/CD, blue/green)

> Shared-service fork (see `PRINCIPLES.md` → "What this is"). Forked from Foundryx EMS; the EMS domain is stripped, each module is a **Service** (first = `omnichannel`). Image/service/host names below may still read "foundryx" - they are the deployment identifiers carried over from the fork; rename per environment as the platform is renamed.


Every push to `main` triggers `.github/workflows/deploy.yml`: validate → test →
build & push images to Docker Hub → SSH into the server →
`scripts/blue_green_deploy.sh` → verify. PRs run validate + test only (no
deploy) - `build-and-deploy` `needs` every validate AND test job, so a failing
suite blocks the deploy the same way a failing build does.

## CI

Every PR against `main` (and every push to it) runs six gate jobs in parallel:
`lint-conventions` (no em/en dash, brand spelling, no stray mentions of the
retired E2E tool - see AGENTS.md), `validate-backend` / `validate-frontend`
(Docker build + import smoke + `next build`), and `test-backend` / `test-frontend` (the real
suites: `pytest -q` from `service_backend` against the conftest's in-memory
SQLite, and `npm run lint && npm test -- --run` from `service_frontend`).
Only a push to `main` (or `workflow_dispatch`) runs `build-and-deploy`, which
`needs` all six - a red test job blocks the deploy exactly like a red build.
`test-backend` sets throwaway env (`DATABASE_URL`/`JWT_SECRET`/`FERNET_KEY`/
`OMNICHANNEL_FERNET_KEY`/`REDIS_URL`) so `app.config.Settings` and
`app.main` import cleanly; the suite itself never opens a real DB or Redis
connection (conftest builds its own SQLite engine per test, `fakeredis`
stands in for Redis, and the email dispatcher / startup orphan sweep are
disabled). Coders still run targeted globs locally during a lane - CI is the
full-suite backstop, not the first place a coder discovers a red test.

## Topology

Caddy (auto-TLS) fronts everything; containers bind `127.0.0.1` only. **One**
public domain (`APP_DOMAIN`, no extra DNS needed): the frontend serves at root,
the backend under a stripped path prefix (`BACKEND_PATH`, default `/be`):

```
https://icp-demo.foundryx.my/        -> frontend (Next pages + /api/auth)
https://icp-demo.foundryx.my/be/*    -> Caddy handle_path strips /be -> backend
```

`handle_path` removes `/be` before proxying, so the backend still sees root paths
(`/auth/login`, `/public/avatars/…`). The backend's own absolute URLs stay correct
because `PUBLIC_BASE_URL` carries the `/be` prefix. Bonus: API calls are
same-origin → no CORS preflight. (Backend root routes like `/forms`/`/templates`
would collide with frontend pages on a shared root - the prefix is what avoids it.)

This platform **shares the host with the dreamz EMS stack** (the fork origin),
so every identifier is namespaced away from it: containers `foundryx_ss_*`,
volumes `foundryx_ss_pg`/`_redis`, network `foundryx_ss_network`, image
`foundryx-shared-service`, DB host port `5433` (`POSTGRES_PORT` var), Caddy
fragment `/etc/caddy/foundryx-ss.caddy` (`CADDY_SITE_FILE` var), and the
loopback port range below (dreamz owns 8000/8010/3001/3011).

| Service | blue | green | notes |
|---|---|---|---|
| backend (API) | `:8200` | `:8210` | gunicorn/UvicornWorker, `/health` |
| frontend (Next standalone) | `:3200` | `:3210` | `node server.js` |
| db / redis / pgbackups | - | - | infra, not blue/green; db host port `5433` |
| worker_workflow / worker_jobs / worker_omni / beat | - | - | Celery; recreated in place each deploy |
| code_runner | - | - | sandboxed workflow Code action; own stdlib-only image, internal-only network, recreated each deploy |

**Code runner** (`service_backend/code_runner/`, image tag `code-runner-<tag>`): the
ONLY process that executes builder-authored Python (workflow `code.run`). It is
a separate image with no application code, no pip packages and no secrets;
compose runs it read-only, non-root, `cap_drop: ALL`, memory/pids-capped, on
the `internal: true` network `foundryx_ss_runner` (no egress). The API colors
and `worker_workflow` join that network to reach it; the runner reaches
nothing. Auth = `CODE_RUNNER_TOKEN` (GitHub Secret, rendered into `.env` for
both the backend env and the runner). Backend `CODE_RUNNER_URL` defaults to
`http://code_runner:8011`. If the runner is down, Code nodes fail cleanly and
publishing a Code-bearing workflow is blocked until `/health` returns.

Two Celery apps share the backend image: `app.workflow_engine.worker` (tasks +
**beat** schedule) and `modules.omnichannel.worker` (inbound WhatsApp). Exactly
one `beat` runs. DB migrations + seed run **only** on the API container start
(`start.sh` → `python -m scripts.bootstrap_db`); workers skip it (command override).

**`worker_jobs` (sprint-5/11 S1, AC-11-80..88) - the worker-starvation fix.**
2026-09-20/21 incident: `worker_workflow` ran `-Q workflow` with no `-c`
(one `ForkPoolWorker` on the 1-vCPU host), and `jobs.run` (any
`background_jobs`-dispatched task - an AutoCount build, a storage migration,
...) shared that ONE process with every 60s beat tick. A hung `jobs.run`
starved the entire platform's scheduled work for 8+ hours; beat itself
stayed healthy throughout, so nothing alerted until an operator noticed by
hand. The fix, all in `app.workflow_engine.worker`'s single Celery app
(`task_routes`, not a second app - a message already queued on `workflow`
at deploy time still executes there):

- `jobs.run` routes onto a **new `jobs` queue**, consumed by the new
  `worker_jobs` compose service (`-Q jobs -c 2`) - `worker_workflow` keeps
  `-Q workflow` only and never sees a `jobs.run` message again post-deploy.
- `worker_prefetch_multiplier = 1` on the whole app - the default of 4 is
  what let a blocked child hold several beat messages in its prefetch
  buffer ("received by MainProcess, never executed").
- Every task is time-limited: the tick family gets an app-level
  `task_soft_time_limit=300` / `task_time_limit=330`; `jobs.run` overrides
  that with its own generous, settings-driven bound
  (`BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS`, default 7200s / 2h - sized
  above the longest legitimate build measured in the sprint-5/11 plan, a
  25+ minute Mocha snapshot). A wedged `jobs.run` fails cleanly on
  `SoftTimeLimitExceeded` (job -> failed, module bookkeeping closed -
  `app/jobs/service.py`) instead of holding its worker's slot forever.
- The orphan sweep gets its OWN 5-minute beat tick (`jobs.sweep_orphaned`),
  explicitly routed onto `workflow` - **never `jobs`, the very queue it
  exists to recover from** (the rule the incident teaches: a sweep must
  never share a queue with the jobs it sweeps). Previously the ONLY caller
  of the sweep outside app startup was the AutoCount scheduler tick -
  itself queued behind the hung job, which is why the symptom lasted 8
  hours instead of 15 minutes.
- `worker_workflow` and `worker_jobs` (only - never `backend_blue`/
  `backend_green`) get three Postgres session-bound envs
  (`WORKER_DB_STATEMENT_TIMEOUT_SECONDS` / `WORKER_DB_LOCK_TIMEOUT_SECONDS` /
  `WORKER_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_SECONDS`, all seconds,
  defence-in-depth against a stuck Postgres statement/lock. **Shipped INERT
  (default `0` = no timeout, review round 1 2026-09-21)**: S0 could not
  complete the slowest-statement measurement of a full `SRT` build on the
  shared dev Postgres (see `11-evidence/s0-baseline/README.md` (c)), so
  R10's numbers (120s/30s/300s) are not yet confirmed - enable these ONLY
  after that measurement lands. When enabling, `idle_in_transaction_session_
  timeout` MUST stay **>= 3x `AUTOCOUNT_SINK_TIMEOUT_SECONDS`** (default
  300s): `sync_service.auto_push` holds an open transaction across the sink
  POST, so a too-tight idle timeout would kill that transaction mid-push.
  Recommended hot values once enabling: statement >= 600s, idle >= 900s.
- `workflows.run_workflow` and `workflows.wake_serialized` (review round 1,
  B2) each declare their OWN soft/hard Celery time limit from
  `WORKFLOW_RUN_SOFT_TIME_LIMIT_SECONDS` (default 1800s / 30 min, hard =
  soft + 300s) instead of silently inheriting the app-level tick-family
  bound (300s/330s) - a legitimate multi-node run or a serialized drain
  processing several queued runs in one wakeup must survive it. On
  `SoftTimeLimitExceeded` the run is failed cleanly (`workflow_runs.status`
  never left `running`) with a dedicated "exceeded its soft time limit"
  sentence, mirroring `jobs.run`'s own cooperative handling.
- Beat publishes a tiny `ops.ping` to EACH queue (`workflow`, `jobs`) every
  60s; the consuming worker stamps a Redis key with a 300s TTL
  (`app/ops_liveness.py`). `GET /platform/ops/queues` (operator-only,
  `tenants.read`) reports `{queue, lastSeen, stale, alive}` per queue - a
  wedged worker is now visible within minutes, not discovered by hand hours
  later. `stale` means "no free slot OR dead" (a worker consuming this queue
  has not drained a recent `ops.ping` broker message - it may simply be busy
  on a long job); `alive` (review round 1, S2) is the Celery control plane's
  OWN synchronous answer - a live `ping()` from a worker whose
  `active_queues()` names this queue, from `celery_app.control.inspect
  (timeout=1.0)`, independent of the broker-routed stamp. A dead/unreachable
  broker reads `alive: false` for every queue and never raises. This route
  covers ONLY the workflow Celery app's queues (`workflow`, `jobs`); the
  omnichannel app's `omni` queue, and any future `stt`/`bots` app, are
  separate Celery apps with no liveness signal wired here yet.

**`BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES` (sprint-5/11 S2, AC-11-50..57,
optional, default **150** (amended from 60, review round 1 2026-09-21),
floor 15)** - the same `jobs.sweep_orphaned` beat tick above also fails a
PENDING job (`started_at` NULL) whose Celery message was itself lost and
never delivered to a worker (incident 2026-09-21: a deploy restarted
`worker_jobs` mid-`pending`); FAILED, never re-dispatched (R6/D12/D13) - the
next tick enqueues a fresh job. No new compose service or queue; just this
one env alongside the S1 vars above. A `model_validator` now rejects a
window that does not exceed `BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS` (7200s
default): the window must outlive `jobs.run`'s own soft time limit, or a
message that is merely queued behind a legitimately long build on a busy
`-c 2` `worker_jobs` could be mistaken for a lost message and failed out
from under it. **This validator runs at settings-load time, so it gates
EVERY process that imports `app.config`** - the API, `worker_workflow`,
`worker_jobs`, `beat`, and `python -m scripts.bootstrap_db` all REFUSE TO
START (a `pydantic.ValidationError` at import) if
`BACKGROUND_JOB_SOFT_TIME_LIMIT_SECONDS` is ever raised in `.env`/GitHub
Secrets without raising `BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES` to match
- change the two together.

**Run `free -m` before `docker compose up -d`** when raising `worker_jobs`'
concurrency above the R9 default; `-c 1` is the fallback if the host is
memory-tight rather than CPU-bound.

**Deploy-time step:** `blue_green_deploy.sh` never runs a bare `docker compose
up -d` over every service - it pulls and force-recreates the Celery workers
from an explicit, named list (`worker_workflow worker_jobs worker_omni beat`,
twice in the script: the pull step and the force-recreate step). A new worker
service (like `worker_jobs` itself, sprint-5/11 S1) is **not** picked up
automatically - it must be added to both lists in `scripts/blue_green_deploy.sh`
by hand, or its queue simply has no consumer in production (the 2026-09-21
`worker_jobs` incident: PR #76 added the compose service and routed `jobs.run`
to it, but the deploy script's worker list was never updated, so every
`autocount_sync` job stayed `pending`). `tests/test_s11_compose_worker_jobs.py`
now pins this: it fails if any top-level `worker_*`/`beat` compose service is
missing from either list. The one-time step after adding a new worker service
to the script is `docker compose up -d <new_service>` on the host (or wait for
the next deploy, since `blue_green_deploy.sh` now force-recreates it). A plain
`docker compose restart worker_workflow` (or any existing service) does
**NOT** pick up a new/changed `environment:` block - see "Notes / gotchas"
below (settings is an import-time singleton; a changed env needs the
container **recreated**, `up -d`, not merely restarted).

## Config = GitHub, not the server (no SSH to edit config)

`docker-compose.yml` carries **no secrets** (all `${VAR}`), so CI commits + syncs
it to the server. The `.env` (secrets) is **rendered on the server by CI** from
GitHub Secrets/Variables on every deploy. To change any config: edit the Secret/
Variable in GitHub and re-run the workflow - never SSH in to hand-edit `.env`.
(`.env.example` documents the keys; the live `.env` is generated, written `0600`.)

## One-time server setup

1. Install Docker + compose plugin. Create the deploy dir (matches `DEPLOY_PATH`
   secret), e.g. `/opt/foundryx-ems`. CI delivers compose + `.env` + the deploy
   script on first push.
2. DNS: already done - you reuse the existing `icp-demo.foundryx.my` record. No
   new subdomain needed. Caddy issues TLS for it automatically.
3. Caddy: the deploy script **owns** a site fragment (`CADDY_SITE_FILE`, default
   `/etc/caddy/foundryx.caddy`) - it rewrites the single site block to the active
   color's ports each swap and runs `caddy reload`. Your main Caddyfile
   (`CADDY_CONFIG`, default `/etc/caddy/Caddyfile`) must import it:
   ```caddyfile
   import /etc/caddy/foundryx.caddy
   ```
   (If foundryx is the only site, set both `CADDY_SITE_FILE` and `CADDY_CONFIG` to
   `/etc/caddy/Caddyfile`.) The deploy user needs passwordless `sudo caddy
   validate` / `caddy reload` / `install`. Each swap the script writes:
   ```caddyfile
   icp-demo.foundryx.my {
       handle_path /be/* { reverse_proxy 127.0.0.1:8001 { header_up Host {host} … } }
       handle          { reverse_proxy 127.0.0.1:3001 { header_up Host {host} … } }
       encode gzip
       tls you@foundryx.my
   }
   ```
   Replace your old sorento site block with this import (and stop the old
   containers so ports `3001`/`8001` are free).
4. First deploy: `.active_color` is absent → script starts `blue`, brings up the
   stack, writes the fragment, reloads Caddy; later pushes flip to green and back.
   (Manual first run: `IMAGE_TAG=<sha> APP_DOMAIN=icp-demo.foundryx.my
   TLS_EMAIL=you@foundryx.my ./scripts/blue_green_deploy.sh`.)

## GitHub secrets / variables

Settings → Secrets and variables → Actions.

**Secrets** (sensitive - masked in logs, used to render the server `.env`):
- Pipeline: `DOCKER_USERNAME`, `DOCKER_PASSWORD`, `SSH_HOST`, `SSH_USER`,
  `SSH_PRIVATE_KEY`, `DEPLOY_PATH` (e.g. `/opt/foundryx-ems`).
- App: `POSTGRES_PASSWORD`, `JWT_SECRET`, `FERNET_KEY`, `OMNICHANNEL_FERNET_KEY`,
  `NEXTAUTH_SECRET`, `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`,
  `PLATFORM_SMTP_USERNAME`, `PLATFORM_SMTP_PASSWORD`.
- Optional email notify: `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `OWNER_EMAIL`.

**Variables** (non-sensitive). Caddy/deploy: `APP_DOMAIN` (e.g.
`icp-demo.foundryx.my`), `TLS_EMAIL` (required); `BACKEND_PATH` (default `/be`),
`CADDY_SITE_FILE`, `CADDY_CONFIG` (optional, have defaults). App config (written
into the server `.env`): `NEXT_PUBLIC_BACKEND_API_URL` (= `https://$APP_DOMAIN/be`,
baked into the frontend image; the script also writes it as `PUBLIC_BASE_URL`),
`FRONTEND_URL` (`https://$APP_DOMAIN`), `CORS_ORIGINS` (`https://$APP_DOMAIN`),
`NEXTAUTH_URL` (`https://$APP_DOMAIN`). Optional:
`POSTGRES_USER`, `POSTGRES_DB`, `IMAGE_REPO`, `RELEASE_TAG`, `BACKEND_WORKERS`,
`META_APP_ID`, `META_ES_CONFIG_ID`, `META_GRAPH_VERSION`, `NEXT_PUBLIC_META_*`,
`PLATFORM_SMTP_HOST`/`_PORT`/`_SECURITY`/`_FROM_EMAIL`/`_FROM_NAME`.

> Keys left unset render as empty in `.env` (fine for the optional Meta/SMTP
> blocks - empty = dev-safe/console-log). The required ones (`${VAR:?...}` in
> compose) will abort the deploy if blank, so set those before the first push.

## Rollback

Re-run a previous successful deploy from the Actions tab (it re-pulls that SHA),
or on the server set `IMAGE_TAG=<old-sha> ./scripts/blue_green_deploy.sh`.

Schema direction on a rollback (no downgrade is ever run automatically):

- A **module** schema cleanly ahead of the old image is skipped by the
  bootstrap with an ERROR-level `ROLLBACK: module '<m>' database is at ...`
  line, and the drift guard lets the old image start. Module migrations are
  additive, so the old code runs on the newer schema. "Cleanly ahead" means:
  every revision the database carries that the old code does not know is
  numbered strictly AFTER every code head (module revision ids are
  `00NN_...` / `00NNa_...`, pinned by a test for every module), and no code
  head is missing.
- Anything else with an unknown revision is **foreign** and the bootstrap
  REFUSES it (`ModuleSchemaForeign`, the deploy aborts): a code head missing
  next to an unknown revision (partly behind), an unknown revision numbered
  at or before a code head (a hotfix image's sibling-branch revision, a
  renamed revision), or an id that does not parse (a corrupted or hand-edited
  version row). Skipping those would silently leave the schema short of the
  code, which is issue #89 again. Reconcile the module's
  `alembic_version_<module>` row and schema by hand, then re-run the deploy.
- A rollback across a **core** migration fails: core `alembic upgrade head`
  raises "Can't locate revision" for a database stamped by a newer image, the
  old colour's bootstrap exits non-zero and the deploy aborts (the newer
  colour keeps serving). This was already true before issue #89. Roll back
  core schema changes deliberately (downgrade by hand, or roll forward with a
  fix), not by redeploying an older image.

## Deploy-time migrations: abort, lock timeouts, drift guard

Incident 26 Sep 2026 (issue #89): the ideation module's migration 0008 hit
`canceling statement due to lock timeout`, `bootstrap_modules` logged
`Module 'ideation' bootstrap failed` and CONTINUED, `start.sh` printed
`bootstrap complete`, the swap went through, and production served ideation
code at migration 0010 against a database at 0007 (`column ideas.title does
not exist` on every idea save). The lock holder was the bootstrap ITSELF: the
module's install hook seeded `ideation_artifact_templates` through the shared
session and kept that transaction open while Alembic, on its own connection,
waited for a lock on the same table.

### What happens now, per deploy

1. The new API colour's `start.sh` runs `python -m scripts.bootstrap_db`:
   core `alembic upgrade head` → core seed → `bootstrap_modules` → drift
   check → `bootstrap complete`. Every connection it opens carries
   `lock_timeout` (`BOOTSTRAP_LOCK_TIMEOUT`, default `20s`, via `PGOPTIONS`),
   module migrations included.
2. Per module, the bootstrap commits its session BEFORE the module's
   migrations (it can never block itself again), and a module already in the
   database migrates FIRST, then its install/seed hook runs against the
   up-to-date schema. A module brand-new to the database keeps the old
   install (`create_all`) → commit → `stamp head` path.
3. **Any module migration or seed failure is fatal.** The log keeps the
   per-module line (`Module '<name>' bootstrap failed; aborting bootstrap:`
   plus the failing SQL); `bootstrap_db` exits non-zero and never prints
   `bootstrap complete`. `start.sh` retries the whole bootstrap
   `BOOTSTRAP_ATTEMPTS` times (default 4, `BOOTSTRAP_RETRY_DELAY` 8s apart;
   everything is idempotent) so a TRANSIENT lock clears, then exits 1.
   A module whose database is cleanly AHEAD of this code (a rollback, see
   "Rollback") is skipped with an ERROR-level `ROLLBACK:` line instead of
   failing on "Can't locate revision"; a FOREIGN one aborts the bootstrap
   (`ModuleSchemaForeign`).
4. On a lock timeout the module migration first logs every session holding a
   lock in that module's schema (`lock holder on schema 'app_<module>':
   pid=... state=... xact_age=... locks=[...] query=...`), then re-raises.
   Query text is redacted (every quoted literal becomes `'?'`) and cut to 200
   characters: live SQL carries emails, tokens and password hashes. When no
   session holds a lock inside the schema, it says the holder may be outside
   it and lists the database's `idle in transaction` sessions older than 10s.
5. `scripts/blue_green_deploy.sh` waits up to **4 minutes**
   (`HEALTH_WAIT_TICKS=120` x 2s, sorento-crm's bound) for the new colour. If
   the new container exits or restarts, or the budget runs out, it prints
   `::error::DEPLOY ABORTED (backend_<new> ...). Swap NOT performed - <old>
   keeps serving.`, dumps the last 200 log lines, STOPS the new colour (so a
   restart loop cannot keep re-running DDL against the live database) and
   exits 1. Caddy is never touched.

   **Timing (why 4 attempts).** One failed attempt costs at most about
   20s of lock wait (`BOOTSTRAP_LOCK_TIMEOUT`) plus the bootstrap's own work
   (core + module migrations, seed; roughly 20-30s on the 1-vCPU host), and
   attempts are 8s apart: 4 x (20 + 30) + 3 x 8 = 224s, inside the 240s
   budget. 5 attempts (the old default) is 282s and would be cut off by the
   deploy script mid-retry. The backend `HEALTHCHECK` polls every 30s, so a
   bootstrap that succeeds late can still be reported healthy up to 30s after
   gunicorn is up. **Consequence (owner ruling):** a data migration or seed
   that needs more than about 4 minutes now aborts the deploy. Run such a
   migration out of band first (`SKIP_MIGRATIONS=1` below, or a one-off
   `docker compose run`), then deploy.
6. Only after the new API colour is healthy are the Celery workers + beat
   recreated on the new image, and each is health-gated: a worker must log
   Celery's `celery@<host> ready.` line within 90s (`WORKER_WAIT_TICKS=45`);
   beat must stay running with zero restarts for 5 ticks. A failure here is
   `DEPLOY FAILED AFTER SWAP`: the new colour serves, the old colour is left
   running for a rollback.

### Module schema drift guard (last line of defence)

`app/module_platform/drift_guard.py` runs at the end of `bootstrap_db`, in the
API lifespan (every gunicorn worker) and at every Celery worker/beat start.
For each module under per-module Alembic it compares the database's
`alembic_version_<module>` with the code's alembic head:

| database vs code | result |
|---|---|
| equal | start |
| a KNOWN older revision (DB behind) | refuse to start: `ModuleSchemaDrift: module '<m>' database schema is at <db> but this code needs <head>` (gunicorn exits 3, a Celery process exits 1) |
| a revision this code does not know, numbered after every code head, no head missing (DB ahead) | WARNING, start. Normal during blue/green: the new colour migrated first, the old colour or its workers may still restart |
| any other unknown revision (foreign: partly behind, sibling-branch / renamed, corrupted) | WARNING, start. NOT refused at process start: that would kill the old colour's respawning workers mid-deploy. Bootstrap is where it is fatal (`ModuleSchemaForeign`), so no deploy goes healthy on it |
| no version table (module never installed here) / no `alembic/` dir | ignored |

A known limit of a version-level guard: it compares revision ids, not tables
and columns. A module adopted through the legacy stamp-without-DDL path
(tables built by `create_all`, then `stamp head`) reads as "at head" even if
those tables were built from older models; only the migrations' own
existence-checked DDL repairs that.

`SKIP_MIGRATIONS=1` skips the bootstrap, NOT the guard: code ahead of its
schema never serves traffic. There is no environment switch that disables the
guard. The workers run it too because they execute the same module code
against the same tables (a worker on new code and an old schema fails every
task that touches a new column), and in a deploy they are recreated only after
the API colour migrated the schema, so a healthy deploy always passes.

### SKIP_MIGRATIONS=1 (the only bypass)

For a hand-run expand-contract rollout: set `SKIP_MIGRATIONS=1` in the shell
that runs the deploy script (compose passes it into the backend env; the
script prints a `::warning::`), run the migrations yourself first, then
deploy. Unset it afterwards. `BOOTSTRAP_LOCK_TIMEOUT`, `BOOTSTRAP_ATTEMPTS`
and `BOOTSTRAP_RETRY_DELAY` reach the container the same way.

### Module migration lock timeout (operator recovery)

Symptom: the deploy aborted with `DEPLOY ABORTED (backend_<new> ...)` and the
new colour's log shows `Module '<m>' migration hit a lock timeout` followed by
`lock holder on schema 'app_<m>': pid=...` lines. Production is fine: the old
colour kept serving on the old schema.

1. **Find the holder.** The log already names it. To look again, live:

   ```
   docker exec -it foundryx_ss_db psql -U foundryx -d foundryx_service
   ```
   ```sql
   SELECT a.pid, a.state, now() - a.xact_start AS xact_age,
          a.application_name, a.client_addr, a.backend_type,
          string_agg(DISTINCT n.nspname || '.' || c.relname || ' ' || l.mode, ', ') AS locks,
          left(regexp_replace(a.query, '''[^'']*''', '''?''', 'g'), 200) AS query  -- literals redacted
   FROM pg_locks l
   JOIN pg_class c ON c.oid = l.relation
   JOIN pg_namespace n ON n.oid = c.relnamespace
   JOIN pg_stat_activity a ON a.pid = l.pid
   WHERE l.granted AND n.nspname = 'app_ideation'   -- the module's schema
     AND a.pid <> pg_backend_pid()
   GROUP BY a.pid, a.state, a.xact_start, a.application_name,
            a.client_addr, a.backend_type, a.query
   ORDER BY xact_age DESC NULLS LAST;
   ```
   While a migration is waiting, `SELECT pid, pg_blocking_pids(pid),
   wait_event_type, left(regexp_replace(query, '''[^'']*''', '''?''', 'g'), 200)
   FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;` shows who blocks whom. Map a
   `client_addr` to its container with `docker network inspect
   foundryx_ss_network`. Keep the `regexp_replace` redaction when you paste
   results anywhere: raw `query` text carries customer literals.
2. **Decide.**
   - `idle in transaction` with a large `xact_age`: a leaked transaction
     (a worker task, a hand-opened psql). Restart the owning container
     (`docker compose restart worker_jobs`, ...) or end the session.
   - `active` long query from the live API or a worker: wait for it, or
     re-run the deploy off-peak.
   - Your own leftover psql / script session: close it.
3. **`pg_terminate_backend` with care.** `SELECT pg_cancel_backend(<pid>);`
   first (cancels the running statement only). `SELECT
   pg_terminate_backend(<pid>);` ends the session and ROLLS BACK its open
   transaction: an API request's write is lost, a worker task fails (the job
   orphan sweep marks it failed). Never terminate replication/autovacuum
   backends (`backend_type`), never guess a pid that is not in the report.
4. **Re-run the bootstrap.** Re-run the deploy workflow from the Actions tab
   (the new colour bootstraps again), or on the host, with the stopped new
   colour's image:

   ```
   IMAGE_TAG=<sha> docker compose --profile <new> run --rm --no-deps backend_<new> python -m scripts.bootstrap_db
   ```
   (`start.sh` runs an override command directly, one attempt, still under
   `lock_timeout`.) It must end with `bootstrap complete: migrated + seeded +
   modules`; then re-run the deploy. The issue-#89 workaround (running
   `run_module_migrations` by hand) is no longer needed: the bootstrap cannot
   block its own migrations any more.

### Safeguards vs sorento-crm's deploy (owner ruling: mirror the mature one)

Compared against sorento-crm's `start.sh` + `scripts/blue_green_deploy.sh`.

Adopted:

- **Migrations before the server, any failure exits the container.** Already
  true for core; extended to module migrations and seeds (issue #89).
- **4-minute health budget for the new colour with a named error**
  (`HEALTH_WAIT_TICKS` 150 → 120; `DEPLOY ABORTED ... Swap NOT performed`).
- **Workers recreated only after the API colour is healthy**, unchanged
  (step 6 after step 3).
- **Workers health-gated on a positive startup line** (sorento greps its
  scheduler/role line; here Celery's `celery@<host> ready.`), 90s window
  (`WORKER_WAIT_TICKS` 30 → 45, sorento's value). Beat keeps the
  running-with-zero-restarts gate: its only startup line prints BEFORE the
  drift guard runs, so it proves nothing.
- **`SKIP_MIGRATIONS=1` as the only bypass.** It was documented but never
  reached the container (the compose env block is an allow-list); it is now
  passed through, with the `BOOTSTRAP_*` tuning knobs, and announced by the
  script.

Added beyond sorento (reason):

- **Fail fast when the new colour exits or restarts** instead of polling out
  the whole budget: `start.sh` already retried inside the container, so an
  exit is final.
- **Stop the new colour on abort**: with `restart: unless-stopped` a failed
  container re-runs the bootstrap forever, and a DDL statement waiting on a
  lock queues every new query on that table behind it for up to
  `lock_timeout`, on the LIVE database.
- **Lock-holder report and module schema drift guard** (sections above).

Rejected (reason):

- **`docker image prune -af --filter until=48h`** (sorento's disk-fill fix):
  this host is shared with the dreamz EMS stack, and `-a` would also delete
  that stack's unused images (its rollback targets). Keep dangling-only
  pruning; a repo-scoped prune is a separate change.
- **gunicorn `preload_app` + `post_fork` engine dispose** (sorento's
  `gunicorn.conf.py`): a memory/startup tuning, not a deploy safeguard; out of
  scope for this fix.
- **nginx upstream swap**: sorento fronts with nginx; the Caddy fragment swap
  here already validates (`caddy validate`) before `caddy reload`, the same
  guarantee as `nginx -t`.

## Notes / gotchas

- `NEXT_PUBLIC_*` are compile-time - changing the public API origin requires a
  **rebuild**, not just an env change.
- A failed migration (core OR module) exits the new API container → the
  script aborts with a named error and the **old color keeps serving**. See
  "Deploy-time migrations" below. `SKIP_MIGRATIONS=1` is the only bypass.
- The email-outbox dispatcher is a lifespan thread inside each gunicorn worker;
  it claims under a DB lease, so multiple workers are safe.
- Meetings transcription (`meetings.transcribe`, sprint-5 prod-enablement) now
  routes onto its own `stt` Celery queue, which NONE of the compose workers
  consume (`worker_workflow` runs `-Q workflow` only). A transcribe job simply
  WAITS in Redis - no more instant failures - until the pilot host's dedicated
  `stt` worker attaches over the tunnel below and drains it. `meetings.calendar_
  sync` and `meetings.bot_run` (the `bots` queue) are unaffected. The chunked
  runner (`mlx_runner.py`, S3 code-switch fix) needs `ffmpeg` AND `ffprobe` on
  the pilot host's `PATH` - it segments the audio with the former and measures
  each chunk's real duration with the latter.

## Meetings pilot host (Mac Mini)

The meetings module's two Metal/Docker-bound workers - `stt` (mlx transcription)
and `bots` (meeting recorder, needs a Docker socket) - never run in the Linux
compose stack. They run on the pilot Mac Mini instead, attached to prod Redis
and Postgres over an SSH tunnel:

```
ssh -L 6379:127.0.0.1:6379 -L 5433:127.0.0.1:5433 user@host -N
```

(`6379` = redis, loopback-published in `docker-compose.yml` for exactly this;
`5433` = the `POSTGRES_PORT` mapping from "Topology" above - the Mini's stt
worker still needs `DATABASE_URL` to write transcript rows.) With the tunnel up,
point the Mini's `.env` at `REDIS_URL=redis://127.0.0.1:6379/0` and the tunneled
Postgres port, then start each worker (both need the macOS fork-safety prefix -
see `modules/meetings/worker.py`'s module docstring for why):

```
no_proxy='*' PGGSSENCMODE=disable OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  celery -A app.workflow_engine.worker worker -Q stt -c 1 --loglevel info

no_proxy='*' PGGSSENCMODE=disable OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES \
  celery -A modules.meetings.worker worker -Q bots -c 2 --loglevel info
```

Neither worker is part of `docker-compose.yml`'s managed set (the `stt` app
reuses `app.workflow_engine.worker`, just on a queue that worker never
declares in its own command; `worker_bots` stays commented out in compose for
the same reason). Both are the operator's responsibility to keep running
alongside the tunnel.
