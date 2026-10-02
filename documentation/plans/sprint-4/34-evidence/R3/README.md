# Plan 34 (A7b) - Review round 3 fix verification

Range: fix commit on `sprint-4/34-channel-web-chat`, lane worktree `.claude/worktrees/s34`.
Backend `:8014` (`DATABASE_URL=foundryx_service_s34`), frontend not touched this round (no
`middleware.ts` behaviour change requires a rebuild for these curl checks - `middleware.test.ts`
covers the fix at the unit level).

## Backend restart, exact lane command

```
P=$(lsof -ti :8014); lsof -p $P | grep -q worktrees/s34 && kill $P; sleep 2
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s34 \
CELERY_TASK_ALWAYS_EAGER=true \
CORS_ORIGINS=http://localhost:3001,http://localhost:3002,http://localhost:3012 \
CORS_ORIGIN_REGEX='http://[a-z0-9-]+\.localhost:301[0-9]' \
PUBLIC_BASE_URL=http://localhost:8014 \
FRONTEND_URL=http://localhost:3012 \
ENVIRONMENT=development \
nohup .venv/bin/python -m uvicorn app.main:app --port 8014 > .../s34-backend.log 2>&1 &
```

Environment verification (both lines present, confirming this is the lane's own process, not a
stale sibling worktree's server):

```
$ ps eww -p $(lsof -ti :8014) -o command= | tr ' ' '\n' | grep -E '^(DATABASE_URL|FRONTEND_URL)='
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s34
FRONTEND_URL=http://localhost:3012

$ curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8014/docs
200
```

## B5 - preflight resolver off the event loop (end-to-end curl probe)

An unknown widget key's preflight gets a `204` (a preflight always does) but NO
`Access-Control-Allow-Origin`:

```
$ curl -s -i -X OPTIONS 'http://localhost:8014/public/omnichannel/webchat/nope/session' \
    -H 'Origin: http://x.example' -H 'Access-Control-Request-Method: POST'
HTTP/1.1 204 No Content
access-control-allow-methods: GET, POST, OPTIONS
access-control-allow-headers: authorization, content-type
access-control-max-age: 600
vary: Origin
```
(no `access-control-allow-origin` line - the browser will block the real request)

The seeded dev demo web chat channel (`chn-demo-web`, widget key
`wk_demo00000000000000000000000000`, `allowedOrigins` includes `http://localhost:3013` -
`modules/omnichannel/bootstrap.py`) gets an EXACT echo of that origin:

```
$ curl -s -i -X OPTIONS \
    'http://localhost:8014/public/omnichannel/webchat/wk_demo00000000000000000000000000/session' \
    -H 'Origin: http://localhost:3013' -H 'Access-Control-Request-Method: POST'
HTTP/1.1 204 No Content
access-control-allow-methods: GET, POST, OPTIONS
access-control-allow-headers: authorization, content-type
access-control-max-age: 600
vary: Origin
access-control-allow-origin: http://localhost:3013
```

Both preflights answered correctly with the resolver now dispatched through
`starlette.concurrency.run_in_threadpool` rather than run synchronously on the event loop
(`app/module_platform/public_cors_middleware.py`). The thread-identity assertion itself is pinned
by `tests/test_module_platform.py::
test_public_cors_middleware_resolver_runs_off_the_event_loop_and_fails_closed_on_error`, which
drives the middleware with a hand-rolled ASGI scope and a resolver that records
`threading.current_thread()`, asserting it never equals the thread that ran `asyncio.run` (i.e.
never the loop thread) - a curl probe alone cannot observe which OS thread served a request, so the
thread-identity claim is pytest-verified, not curl-verified.

## Pytest (one file at a time)

```
$ .venv/bin/python -m pytest -q tests/test_module_platform.py
18 passed
$ .venv/bin/python -m pytest -q tests/test_omnichannel_webchat_frame_policy.py
13 passed
$ .venv/bin/python -m pytest -q tests/test_omnichannel_webchat_public.py
53 passed
```

`test_module_platform.py` went from 17 -> 18 (new B5 end-to-end test; the pre-existing
`test_public_cors_middleware_refuses_when_a_resolver_raises` updated for `_allows`'s new `async`
signature - it now drives it via `asyncio.run`). `test_omnichannel_webchat_frame_policy.py` went
from 12 -> 13 (new S-new-2 thread-hammering test, 16 threads, near-zero TTL and a tiny cap to force
constant expiry AND eviction - asserts nothing raised). `test_omnichannel_webchat_public.py`
unchanged at 53, all still green, including every existing CORS preflight test - proving B5's
`async _allows` change is not a regression on the real `TestClient` path.

## Vitest + eslint

```
$ npx vitest run middleware.test.ts
✓ middleware.test.ts (5 tests)
$ npx eslint middleware.ts middleware.test.ts
(no output - 0 errors)
```

`middleware.test.ts` went from 4 -> 5 (new N-new-5 case: a 200 with a non-JSON body now fails
closed with a logged "bad body" warning instead of throwing out of `middleware()`).

## Files touched this round

- `app/module_platform/public_cors_middleware.py` - B5 (`_allows` now `async`, dispatches through
  `run_in_threadpool`)
- `app/module_platform/public_cors.py` - B5 (provider contract docstring: resolvers MAY block, are
  always run off the loop)
- `modules/omnichannel/services/webchat_visitor_service.py` - S-new-2 (module-level
  `threading.Lock` around every `_origins_cache` read/write) + N-new-6 (comment rewrite)
- `modules/omnichannel/routers/webchat_public.py` - N-new-6 (`frame_policy` docstring rewrite)
- `service_frontend/middleware.ts` + `middleware.test.ts` - N-new-5 (fail-closed on a non-JSON 200
  body) + new test
- `tests/test_module_platform.py` - B5 tests (new + updated)
- `tests/test_omnichannel_webchat_frame_policy.py` - S-new-2 test (new)
- `documentation/backlogs/backlog.md` - BL-SS-181 amended, BL-SS-190/191 added
- `documentation/plans/sprint-4/34-omnichannel-channel-web-chat.md` - round-3 fixes table + RR7/RR8
  residual rows added to section 7
- `documentation/plans/sprint-4/34-omnichannel-channel-web-chat-test-report.md` - "Review round 3"
  section added
