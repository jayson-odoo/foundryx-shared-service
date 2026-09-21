# Foundryx Shared Service Platform - Deployment (CI/CD, blue/green)

> Shared-service fork (see `PRINCIPLES.md` → "What this is"). Forked from Foundryx EMS; the EMS domain is stripped, each module is a **Service** (first = `omnichannel`). Image/service/host names below may still read "foundryx" - they are the deployment identifiers carried over from the fork; rename per environment as the platform is renamed.


Every push to `main` triggers `.github/workflows/deploy.yml`: validate → build &
push images to Docker Hub → SSH into the server → `scripts/blue_green_deploy.sh`
→ verify. PRs run validate only (no deploy).

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
  defence-in-depth against a stuck Postgres statement/lock - defaults in
  `docker-compose.yml` carry R10's recommended starting point, not yet a
  measured value).
- Beat publishes a tiny `ops.ping` to EACH queue (`workflow`, `jobs`) every
  60s; the consuming worker stamps a Redis key with a 300s TTL
  (`app/ops_liveness.py`). `GET /platform/ops/queues` (operator-only,
  `tenants.read`) reports `{queue, lastSeen, stale}` per queue - a wedged
  worker is now visible within minutes, not discovered by hand hours later.

**`BACKGROUND_JOB_UNDISPATCHED_AFTER_MINUTES` (sprint-5/11 S2, AC-11-50..57,
optional, default 60, floor 15)** - the same `jobs.sweep_orphaned` beat tick
above also fails a PENDING job (`started_at` NULL) whose Celery message was
itself lost and never delivered to a worker (incident 2026-09-21: a deploy
restarted `worker_jobs` mid-`pending`); FAILED, never re-dispatched (R6/D12/
D13) - the next tick enqueues a fresh job. No new compose service or queue;
just this one env alongside the S1 vars above.

**Deploy-time step:** a new compose service is picked up by `docker compose
up -d` (which this deploy's CI already runs, force-recreating changed
services) - no manual step beyond a normal push-triggered deploy. A plain
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

## Notes / gotchas

- `NEXT_PUBLIC_*` are compile-time - changing the public API origin requires a
  **rebuild**, not just an env change.
- A failed migration exits the new API container → healthcheck never passes →
  the script aborts and the **old color keeps serving**. Set `SKIP_MIGRATIONS=1`
  in backend env for manual expand-contract rollouts.
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
