# FoundryX Shared Service Platform — Deployment (CI/CD, blue/green)

> Shared-service fork (see `PRINCIPLES.md` → "What this is"). Forked from FoundryX EMS; the EMS domain is stripped, each module is a **Service** (first = `omnichannel`). Image/service/host names below may still read "foundryx" — they are the deployment identifiers carried over from the fork; rename per environment as the platform is renamed.


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
would collide with frontend pages on a shared root — the prefix is what avoids it.)

| Service | blue | green | notes |
|---|---|---|---|
| backend (API) | `:8000` | `:8010` | gunicorn/UvicornWorker, `/health` (`:3000`/php = ecohub) |
| frontend (Next standalone) | `:3001` | `:3011` | `node server.js` |
| db / redis / pgbackups | — | — | infra, not blue/green |
| worker_workflow / worker_omni / beat | — | — | Celery; recreated in place each deploy |

Two Celery apps share the backend image: `app.workflow_engine.worker` (tasks +
**beat** schedule) and `modules.omnichannel.worker` (inbound WhatsApp). Exactly
one `beat` runs. DB migrations + seed run **only** on the API container start
(`start.sh` → `python -m scripts.bootstrap_db`); workers skip it (command override).

## Config = GitHub, not the server (no SSH to edit config)

`docker-compose.yml` carries **no secrets** (all `${VAR}`), so CI commits + syncs
it to the server. The `.env` (secrets) is **rendered on the server by CI** from
GitHub Secrets/Variables on every deploy. To change any config: edit the Secret/
Variable in GitHub and re-run the workflow — never SSH in to hand-edit `.env`.
(`.env.example` documents the keys; the live `.env` is generated, written `0600`.)

## One-time server setup

1. Install Docker + compose plugin. Create the deploy dir (matches `DEPLOY_PATH`
   secret), e.g. `/opt/foundryx-ems`. CI delivers compose + `.env` + the deploy
   script on first push.
2. DNS: already done — you reuse the existing `icp-demo.foundryx.my` record. No
   new subdomain needed. Caddy issues TLS for it automatically.
3. Caddy: the deploy script **owns** a site fragment (`CADDY_SITE_FILE`, default
   `/etc/caddy/foundryx.caddy`) — it rewrites the single site block to the active
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

**Secrets** (sensitive — masked in logs, used to render the server `.env`):
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
> blocks — empty = dev-safe/console-log). The required ones (`${VAR:?...}` in
> compose) will abort the deploy if blank, so set those before the first push.

## Rollback

Re-run a previous successful deploy from the Actions tab (it re-pulls that SHA),
or on the server set `IMAGE_TAG=<old-sha> ./scripts/blue_green_deploy.sh`.

## Notes / gotchas

- `NEXT_PUBLIC_*` are compile-time — changing the public API origin requires a
  **rebuild**, not just an env change.
- A failed migration exits the new API container → healthcheck never passes →
  the script aborts and the **old color keeps serving**. Set `SKIP_MIGRATIONS=1`
  in backend env for manual expand-contract rollouts.
- The email-outbox dispatcher is a lifespan thread inside each gunicorn worker;
  it claims under a DB lease, so multiple workers are safe.
