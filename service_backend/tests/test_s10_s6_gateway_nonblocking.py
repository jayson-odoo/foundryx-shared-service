"""Sprint-5/10 S6 - the public gateway's build route must not block the
ASGI event loop (live-replay Finding 2, ``documentation/plans/sprint-5/10-
evidence/live-replay/README.md``): a genuine, slow build triggered through
``POST /api/v1/autocount/snapshots`` froze `/openapi.json` (an unrelated,
unauthenticated, no-DB route) for the ENTIRE 8m47.9s build - reproduced and
timed 3 separate times in the replay session.

Root cause, verified at HEAD: ``routers/pull_v1.py``'s
``async def build_snapshot`` calls straight through, with no ``await`` on
the actual extraction, to ``PullGatewayService(db).build(...)`` ->
``PullService.request_build(...)`` -> (eager mode, this suite's own
``CELERY_TASK_ALWAYS_EAGER``) ``JobService.enqueue`` ->
``app.jobs.service.run_job(db, job_id)`` -> the registered
``autocount_pull_snapshot`` handler (``sync._run_pull_snapshot``) - fully
SYNCHRONOUS, GIL-holding work, all of it inside the coroutine's own call
stack with zero ``await`` points. Because the route is declared
``async def``, FastAPI/Starlette run it DIRECTLY on the event loop (never
the automatic threadpool ordinary ``def`` routes get) - so nothing else on
this worker can make progress until it returns.

Two acceptable fix shapes:
1. Make the route a plain ``def`` (Starlette threadpools it automatically,
   exactly like ``routers/pull.py``'s own operator build route already
   does - it did NOT exhibit the freeze in the replay).
2. Keep ``async def`` but offload the actual extraction via
   ``starlette.concurrency.run_in_threadpool`` (or an equivalent thread
   hop) so the coroutine genuinely ``await``s rather than blocking inline.

sprint-5/10 confirm-3 B2 - this file USED TO also carry a behavioural race
test (two ``asyncio.create_task``s racing a slow build against a concurrent
``GET /openapi.json`` over ``httpx.ASGITransport``, both against the SAME
app/event loop). It was DELETED: it passed even with ``build_snapshot``
reverted to the original blocking ``async def`` (verified directly - the
whole point of a red/green pin is that reverting the fix must fail it, and
this one did not), because ``asyncio.create_task`` only SCHEDULES a
coroutine - it does not start it - and the two tasks' relative starting
order (and how many awaits each hits before yielding, e.g. more DB
round-trips upstream of the build route's own synchronous section than
``GET /openapi.json`` needs) is scheduler-dependent, not something this test
pinned down. A false green on a security-adjacent perf regression is worse
than no coverage at all; see the backlog row added this round for a harder
version (the stub setting an explicit event, the concurrent request
starting only once the blocking section is confirmably entered). The pin
below is the one this file keeps: it is a structural fact about the route
declaration, not a timing race, so it cannot flake either way, and it is
the ENFORCING check that stops a future edit from quietly reinstating
``async def build_snapshot`` with the extraction called straight through -
the exact regression this file exists to catch.
"""
from __future__ import annotations

import inspect

GATEWAY_PREFIX = "/api/v1/autocount"


# ── the enforcing pin: the route shape itself ───────────────────────────────


def test_gateway_build_route_is_not_a_coroutine_function():
    """The one shape ``routers/pull_v1.py``'s ``build_snapshot`` must NOT be:
    a coroutine function that calls its (fully synchronous, GIL-holding)
    extraction straight through with no ``await``. A plain ``def`` route is
    auto-threadpooled by Starlette (fix shape 1 above); an ``async def``
    route that genuinely ``await``s the extraction via
    ``starlette.concurrency.run_in_threadpool`` (fix shape 2) also satisfies
    the underlying concern but reads as `async def` here - if the coder ever
    takes that shape instead, re-express this pin against the threadpool
    call rather than weakening it back to nothing. At HEAD (pre-fix) the
    route was ``async def`` AND blocked inline, so this failed for the
    right, documented reason before the fix landed."""
    from modules.autocount.routers import pull_v1

    assert inspect.iscoroutinefunction(pull_v1.build_snapshot) is False, (
        "modules.autocount.routers.pull_v1.build_snapshot is `async def` "
        "again and (per this file's own module docstring) the live-replay "
        "finding was that it performs its extraction synchronously in-line "
        "- either make it a plain `def` (Starlette auto-threadpools it) or "
        "keep `async def` and genuinely `await` the extraction via "
        "`run_in_threadpool`."
    )
