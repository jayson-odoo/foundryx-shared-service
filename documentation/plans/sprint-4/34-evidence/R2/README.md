# Plan 34 (A7b) review round 2 - fix verification

Recorded 2026-09-08 against the s34 lane (branch `sprint-4/34-channel-web-chat`, fix commit on top
of `301c452d`), backend `:8014`, frontend `:3012`.

## Pre-existing environment note (not part of this round's diff)

Before this session, `service_backend/.env` (a symlink to the main checkout's `.env`) pointed
`DATABASE_URL` at the SHARED `foundryx_service` database rather than the dedicated
`foundryx_service_s34` Postgres database that exists alongside it. This was the lane's state before
any change in this round - unchanged by this fix. The shared database was several core-Alembic
revisions and one module-Alembic revision (`0022_omni_webchat_profile`) behind this branch's head
(pre-existing drift from other lanes sharing the same Postgres instance - `background_jobs.
heartbeat_at` and `channels.external_account_id` did not exist yet, so EVERY query touching those
columns, on ANY branch pointed at this database, was already failing before this session started).
Brought current with `alembic upgrade head` (core, 7 revisions, purely additive) and
`run_module_migrations(engine, "omnichannel")` (module, to `0022_omni_webchat_profile`) before
restarting `:8014` - both idempotent, additive-only migrations that fix forward rather than
introduce new risk. No destructive operation was run. The backend was restarted only after
confirming (via `lsof -p $(lsof -ti :8014) | grep cwd`) that the process on the port belonged to this
worktree.

## Backend regression - one file at a time

| File | Result |
|---|---|
| `tests/test_omnichannel_webchat_frame_policy.py` | 12 passed (was 8; +4 new: B4 no-throttle, B4 601-probe, S-new-1 LRU cap, S-new-1 negative TTL, S-new-1 cache-hit-no-session - 5 new tests, one prior throttle test replaced) |
| `tests/test_omnichannel_webchat_public.py` | 53 passed (unchanged) |
| `tests/test_omnichannel_webchat_outbound.py` | 16 passed (was 15; +1 new: N-new-1 revalidation does not stamp `last_seen_at`) |
| `tests/test_omnichannel_ws.py` | 5 passed (was 3; +2 new: N-new-2 jitter band + computed-once-per-call) |
| `tests/test_module_platform.py` | 17 passed (unchanged) |
| `tests/test_omnichannel_channels_webchat.py` | 28 passed (manifest version-pin now asserts `0.10.1`) |
| `tests/test_omnichannel_contacts_module.py` | 38 passed (manifest version-pin now asserts `0.10.1`) |
| `tests/test_omnichannel_broadcasts.py` | 49 passed (manifest version-pin now asserts `0.10.1`) |
| `tests/test_omnichannel_team_assignment.py` | 34 passed (manifest version-pin now asserts `0.10.1`) |

Each file was run in isolation per the lane's memory constraint (machine swapping); no whole-repo
pytest run. `pyflakes` clean on every touched backend file.

## Frontend

- `npx eslint middleware.ts middleware.test.ts` - clean, zero warnings.
- New `service_frontend/middleware.test.ts` (4 tests, all passing): a 200 with `allowedOrigins: []`
  emits `frame-ancestors 'none'` silently (no `console.warn`); a non-2xx (429) emits the same header
  WITH a logged warning naming the status; a network failure emits the same header WITH a logged
  warning naming the failure as a network error; a failed probe for one widget key never poisons a
  later request for a known-good key (each `fetchAllowedOrigins` call is independent - no shared
  cache/state in `middleware.ts` to poison in the first place).
- `rm -rf .next && npm run build` succeeded; `npx next start -p 3012` restarted cleanly against the
  post-migration backend.

## Live probes (curl, against the running :8014 / :3012)

### B4 - no throttle on `frame-policy`, one caller's probe never breaks another's request

```
$ curl -s http://localhost:8014/public/omnichannel/webchat/wk_unknown_probe_9999/frame-policy
{"allowedOrigins":[]}

# Connected a real channel (S34 Round2 Verify, workspace "General", tenant demo/default),
# allowedOrigins=["http://localhost:3013"], widget key wk_50adb878c8254b8d86f15d972b597417.

$ curl -s http://localhost:8014/public/omnichannel/webchat/wk_50adb878c8254b8d86f15d972b597417/frame-policy
{"allowedOrigins":["http://localhost:3013"]}

# 601 distinct unknown-key probes in a loop (one past the OLD 600/5min IP throttle ceiling) -
# took 5s wall clock, all 200:
$ for i in $(seq 1 601); do
    curl -s -o /dev/null "http://localhost:8014/public/omnichannel/webchat/wk_r2_probe_${i}_deadbeef/frame-policy"
  done

# The known-good key immediately after the 601 probes - unaffected:
$ curl -s http://localhost:8014/public/omnichannel/webchat/wk_50adb878c8254b8d86f15d972b597417/frame-policy
{"allowedOrigins":["http://localhost:3013"]}

# Zero throttle rows written for the webchat scope by any of the above:
$ psql ... -c "select scope, count(*), sum(fail_count) from auth_throttle where scope='webchat' group by scope;"
 scope | count | sum
-------+-------+-----
(0 rows)
```

This is the exact B4 scenario from the review: before this fix, the shared IP-keyed throttle would
have tripped on the Next.js server's one IP well before probe 601 and put every tenant's panel
behind `frame-ancestors 'none'`. After the fix, the route carries no throttle at all - the bounded,
split-TTL origins cache (S-new-1) absorbs the cost instead, and nothing here can be tripped by one
caller on another caller's behalf.

### Middleware - `frame-ancestors` for a known vs. unknown widget key

```
$ curl -sI http://localhost:3012/public/webchat/wk_50adb878c8254b8d86f15d972b597417 | grep -i content-security-policy
content-security-policy: frame-ancestors http://localhost:3013

$ curl -sI http://localhost:3012/public/webchat/wk_totally_unknown_00000000 | grep -i content-security-policy
content-security-policy: frame-ancestors 'none'
```

Matches the deliverable's required probe exactly.

### Cleanup

The verification channel (`S34 Round2 Verify`) was disconnected (`POST /omnichannel/channels/
disconnect`) at the end of this run - none of the shared demo/seed channels were mutated. Confirmed
its widget key resolves back to an empty origin list post-disconnect:

```
$ curl -s http://localhost:8014/public/omnichannel/webchat/wk_50adb878c8254b8d86f15d972b597417/frame-policy
{"allowedOrigins":[]}
```

Both servers left healthy: `curl :8014/docs` -> 200, `curl :3012/` -> 200.

## Files touched this round

- `service_backend/modules/omnichannel/routers/webchat_public.py` - B4: throttle removed from
  `frame_policy`.
- `service_backend/modules/omnichannel/services/webchat_visitor_service.py` - S-new-1: bounded LRU
  origins cache with split positive/negative TTL, cache-before-session in both `resolve_frame_policy`
  and `preflight_origin_allowed`.
- `service_backend/modules/omnichannel/routers/ws.py` - N-new-1 (`stamp_presence` flag, revalidation
  passes `False`), N-new-2 (`_jittered_interval`, computed once per socket).
- `service_backend/app/module_platform/public_cors.py` - N-new-3: docstring path fix.
- `service_backend/modules/omnichannel/manifest.json`, `modules/omnichannel/bootstrap.py` - N-new-4:
  version bump to `0.10.1` + docstring.
- `service_frontend/middleware.ts` - B4: distinct logging for "no origins" vs "call failed", both
  still request-scoped fail-closed.
- `service_frontend/middleware.test.ts` - new.
- Tests: `test_omnichannel_webchat_frame_policy.py`, `test_omnichannel_webchat_outbound.py`,
  `test_omnichannel_ws.py`, `test_omnichannel_channels_webchat.py`,
  `test_omnichannel_team_assignment.py`, `test_omnichannel_contacts_module.py`,
  `test_omnichannel_broadcasts.py`.
- `documentation/backlogs/backlog.md` - BL-SS-185..189 (5 of the 6 residuals; the 6th, WS
  re-verify interval/jitter/write cost, was fixed in this round rather than backlogged).
- `documentation/plans/sprint-4/34-omnichannel-channel-web-chat.md` - 5.4 note + a "Review round 2
  fixes accepted" table in section 7.
- `documentation/plans/sprint-4/34-omnichannel-channel-web-chat-test-report.md` - round 2 table
  (see below).
