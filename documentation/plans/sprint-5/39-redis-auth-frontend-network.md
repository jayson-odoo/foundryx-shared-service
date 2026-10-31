# Plan 39: Redis password and a separate frontend network

Infra hardening. Redis gets a password from an env secret, and the frontend containers move off the network that db and redis use, because the frontend only ever talks to the backend. No application behaviour changes.

## Deploy order

The risk is order: `scripts/blue_green_deploy.sh` brings infra up first, so a plain `--requirepass` would lock out the live color and the workers before they have the new URL.

The fix relies on one Redis behaviour: while the default user is `nopass`, a two-argument `AUTH default <password>` is accepted with any password. The Redis ACL docs state "every password will work against this user", and ACLs date from Redis 6, which covers prod's `redis:7-alpine`. So the URL is `redis://default:<password>@redis:6379/0`, which works before and after Redis has a password.

Do not use `redis://:<password>@...`. On the wire, one-argument `AUTH <password>` is refused while no password is configured. Current redis-py hides this by sending `HELLO 3 AUTH default <password>`, but with `protocol=2` the one-argument URL fails, and `requirements.txt` only pins `redis>=5.0.0`, so that behaviour is version-dependent. AC-39-08 records the live results.

| Step | What happens | Redis state | Live traffic |
|---|---|---|---|
| Before merge | Set the `REDIS_PASSWORD` GitHub secret, hex only. Update the Mac Mini meetings env if that pilot is live | Open | Unchanged |
| 1 Infra up | `redis` is started if missing but not recreated | Open | Old color, old URL, works |
| 2 New color up | Backend and frontend start with the new URL and networks | Open | New URL authenticates, old URL still works |
| 3 Cutover | Caddy moves to the new color | Open | New color |
| 4 Workers | Workers and beat recreated with the new URL | Open | All Celery on the new URL |
| 5 Old color removed | Nothing uses the old URL now | Open | New color |
| 6 Redis recreated | `up -d redis` applies `--requirepass`. Clients reconnect within seconds, the append-only file keeps queued tasks | Password on | Short blip |
| 7 Check | Authenticated ping must pass and unauthenticated must get `NOAUTH`, or the deploy fails loudly | Password on | New color |

If the secret is missing, compose stops at its first interpolation with "set in .env", before the live color is touched.

If a deploy fails before step 6, Redis stays open and everything still works. If it fails at step 6 or 7, the new URL works in either Redis state.

## Acceptance criteria

| AC | Rule |
|---|---|
| AC-39-01 | `redis` runs with `--requirepass` from `${REDIS_PASSWORD}`, using the `:?` form so a missing value stops compose. No password value exists anywhere in the repo |
| AC-39-02 | `REDIS_URL` for backend colors, workers and beat is `redis://default:${REDIS_PASSWORD...}@redis:6379/0` |
| AC-39-03 | `.github/workflows/deploy.yml` writes `REDIS_PASSWORD` from `secrets.REDIS_PASSWORD` into the server `.env` |
| AC-39-04 | `frontend_blue` and `frontend_green` are on `foundryx_ss_edge` only, not on `foundryx_ss_network` |
| AC-39-05 | `backend_blue` and `backend_green` are on both networks, with alias `backend` on the edge network. `db`, `redis`, workers and `beat` are not on the edge network. `foundryx_ss_network` keeps its pinned subnet and gateway |
| AC-39-06 | The infra step never recreates a running `redis` before the clients have moved, using `--no-recreate` for `redis`. `db` and `pgbackups` behave as before. The network-recreate fallback branch still works |
| AC-39-07 | After the old color is removed, the script runs `docker compose up -d redis`, then requires an authenticated `PING` to return `PONG` and an unauthenticated one to be refused. Otherwise it exits non-zero with a clear message. The password is passed through `REDISCLI_AUTH`, never on a command line or in the log |
| AC-39-08 | Live proof on a real `redis-server`, posted on the PR: with redis-py sync, redis-py asyncio and a Celery or kombu connection, the `default:` URL connects to both an open server and a `--requirepass` server. A wrong password fails on the protected server. On the wire, one-argument `AUTH` is refused on the open server. Run on Redis 8.4, prod is 7-alpine |
| AC-39-09 | After a Redis restart, Celery workers and the inbox websocket subscriber recover without an app restart. Verified in code and live where possible. If a path does not recover, fix it or report it |
| AC-39-10 | No code path logs or returns `settings.redis_url` or the password, including ops pages and error messages |
| AC-39-11 | `DEPLOY.md` documents the secret, the networks, the deploy order and the Mac Mini `REDIS_URL` form. Local dev defaults are unchanged and still need no password |
| AC-39-12 | `tests/test_deploy_blue_green_script.py` and `tests/test_s11_compose_worker_jobs.py` still pass |
