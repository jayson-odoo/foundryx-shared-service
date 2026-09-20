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

Two acceptable fix shapes (either passes this file):
1. Make the route a plain ``def`` (Starlette threadpools it automatically,
   exactly like ``routers/pull.py``'s own operator build route already
   does - it did NOT exhibit the freeze in the replay).
2. Keep ``async def`` but offload the actual extraction via
   ``starlette.concurrency.run_in_threadpool`` (or an equivalent thread
   hop) so the coroutine genuinely ``await``s rather than blocking inline.

The behavioural test below stubs the registered job handler with a REAL,
GIL-holding busy-wait (never ``time.sleep`` - this file's name starts with
``test_s10_``, and ``tests/conftest.py``'s own autouse
``_no_real_sleep_in_autocount_http_tests`` fixture patches ``time.sleep`` to
a no-op for every ``test_s10_*``/``test_autocount_http_*`` file, which would
silently defeat a ``time.sleep``-based stub here) to reproduce the exact
mechanism the replay observed, without needing a real slow HTTP transport.
"""
from __future__ import annotations

import asyncio
import inspect
import time as time_module
from typing import Any, Dict

import httpx
import pytest

from app.jobs.registry import JobHandlerDef
import app.jobs.registry as job_registry
from app.jobs.service import JobService
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig

GATEWAY_PREFIX = "/api/v1/autocount"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    """Lane rule: no test in this file may touch the network. See
    ``test_s10_s3_delivery_mode.py``'s copy of this fixture for the full
    rationale (coordinator finding 2026-09-20)."""
    real_send = httpx.Client.send
    real_async_send = httpx.AsyncClient.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    async def guarded_async_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return await real_async_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_async_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _pull_task(db, company) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http", etl_status="active", delivery_mode="pull",
        source_config={
            "connectionId": company.connection_id, "path": "/itembypage",
            "keyFields": ["ItemCode"], "watermarkField": None, "comparedFields": [],
            "distinctOf": None, "incrementalMinutes": 15, "reconcileMode": "dailyAt",
            "reconcileAt": "02:00", "lookups": [],
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _issue_key(db, *, company_ids):
    from modules.autocount.services.pull_key_service import PullKeyService

    _key, plaintext = PullKeyService(db).issue(
        DEFAULT_TENANT_ID, name="S6 nonblocking test key", company_ids=company_ids,
    )
    return plaintext


# ── cheap pin: the route shape itself ────────────────────────────────────────


def test_gateway_build_route_is_not_a_coroutine_function():
    """Either acceptable fix (plain ``def``, or ``async def`` +
    ``run_in_threadpool``) may satisfy the BEHAVIOURAL test below; this pin
    only covers the simplest of the two shapes and is explicitly allowed to
    stay red if the coder instead offloads via ``run_in_threadpool`` while
    keeping ``async def`` - the behavioural test is the authoritative one.
    At HEAD today the route is ``async def`` AND blocks inline, so this
    fails for the right (documented) reason."""
    from modules.autocount.routers import pull_v1

    assert inspect.iscoroutinefunction(pull_v1.build_snapshot) is False, (
        "modules.autocount.routers.pull_v1.build_snapshot is still `async "
        "def` and (per the behavioural test in this file) still performs "
        "its extraction synchronously in-line - either make it a plain "
        "`def` (Starlette auto-threadpools it) or keep `async def` and "
        "genuinely `await` the extraction via `run_in_threadpool`."
    )


# ── behavioural: a slow build must not stall a concurrent request ───────────


def test_a_slow_build_does_not_stall_a_concurrent_request_on_the_same_app(
    client, db, monkeypatch
):
    """Reproduces the live-replay finding without a slow real transport:
    the registered ``autocount_pull_snapshot`` job handler is swapped for a
    REAL, GIL-holding ~1s busy-wait (a synchronous stand-in for "a page
    request that genuinely takes a while"). A concurrent, unrelated,
    no-DB route (``GET /openapi.json`` - the exact route the replay used)
    must still answer promptly. `client` (the `TestClient(app)` fixture)
    is only used to trigger the app's own startup/dependency-override
    wiring; the actual concurrent calls go through a real
    ``httpx.AsyncClient`` bound to the SAME ASGI ``app`` via
    ``httpx.ASGITransport`` so both requests genuinely race on ONE event
    loop, exactly like the single uvicorn worker the replay ran against."""
    from modules.autocount.sync import AUTOCOUNT_PULL_SNAPSHOT

    def _blocking_handler(handler_db, job) -> None:
        # A REAL busy-wait, never `time.sleep` (patched to a no-op for this
        # file - see the module docstring). Holds the GIL/event loop for
        # ~1s, exactly reproducing "the worker cannot service any other
        # request while this runs".
        deadline = time_module.monotonic() + 1.0
        while time_module.monotonic() < deadline:
            pass
        JobService(handler_db).finish(job, status=JOB_DONE, result={"ok": True})

    monkeypatch.setitem(
        job_registry._REGISTRY,
        AUTOCOUNT_PULL_SNAPSHOT,
        JobHandlerDef(AUTOCOUNT_PULL_SNAPSHOT, _blocking_handler, "S6 test stub", heartbeats=True),
    )

    conn = _connection(db)
    company = _company(db, conn.id)
    _pull_task(db, company)
    key = _issue_key(db, company_ids=[company.id])

    async def _race() -> Dict[str, Any]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            build_task = asyncio.create_task(
                ac.post(
                    f"{GATEWAY_PREFIX}/snapshots",
                    json={"companyCode": "SRT", "entity": "products"},
                    headers={"X-API-Key": key},
                )
            )
            openapi_task = asyncio.create_task(ac.get("/openapi.json"))

            openapi_start = time_module.monotonic()
            openapi_response = await asyncio.wait_for(openapi_task, timeout=5.0)
            openapi_elapsed = time_module.monotonic() - openapi_start

            build_response = await asyncio.wait_for(build_task, timeout=5.0)
            return {
                "openapi_response": openapi_response,
                "openapi_elapsed": openapi_elapsed,
                "build_response": build_response,
            }

    result = asyncio.run(_race())

    assert result["openapi_response"].status_code == 200
    assert result["build_response"].status_code == 202, result["build_response"].text
    assert result["openapi_elapsed"] < 0.3, (
        f"GET /openapi.json took {result['openapi_elapsed']:.2f}s while an "
        f"autocount pull build was running on the same app - the gateway "
        f"build route is blocking the event loop for the whole build "
        f"duration (live-replay Finding 2)."
    )
