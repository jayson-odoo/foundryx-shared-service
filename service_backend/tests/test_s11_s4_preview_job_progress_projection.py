"""Sprint-5/11 S4 - the ``GET /autocount/previews/{jobId}`` route's own
projection of ``progress`` (AC-11-27's wire shape), scoped DELIBERATELY to
what S4 owns.

RESCOPING NOTE (read before extending this file): the brief that spawned
this file asked for a spy proving the HANDLER calls a per-stage
``JobService.beat_progress``-style method with the exact six-stage sequence
(``source``, ``lookup:<alias>``, ``combine``, ``mapping``, ``dry_run``,
``storing``). That instrumentation is Group C's job (plan section 2.3,
AC-11-40..42, slice **S5** - "Progress for real": ``beat_progress``, stages
in both handlers) - the plan's own S4 test list (section "Test list per
slice") does NOT mention progress sequencing at all, only "the 202 contract
... cancel stops within one page ... the save-gate stamps ... the prediction
cap ... the column-probe timeout ceiling ... cross-tenant 404". Asserting an
exact ``beat_progress`` call sequence here would pin S5 behaviour a slice
early, on a method name/signature this file cannot yet confirm.

What genuinely IS S4's job (and is pinned below): the GET route must
PROJECT whatever ``progress_done``/``progress_total``/``cursor_json.stage``
the job row already carries (the core ``background_jobs`` columns
``JobService`` already writes for every heartbeating job type, per
``app/jobs/service.py``) into the wire ``{stage, pagesDone, pagesTotal}``
shape - and omit it entirely (never guess) when nothing is known yet. This
is testable today by constructing the job row directly, independent of
whether the S4 handler itself calls any progress-stamping helper per page
(S5's job) - it only requires the ROUTE to read the columns that already
exist on ``BackgroundJob``.
"""
from __future__ import annotations

from typing import Dict

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_RUNNING, BackgroundJob

JOB_TYPE = "autocount_source_preview"


@pytest.fixture(autouse=True)
def _block_live_network(monkeypatch):
    real_send = httpx.Client.send

    def guarded_send(self, request, *args, **kwargs):
        if isinstance(self._transport, (httpx.HTTPTransport, httpx.AsyncHTTPTransport)):
            raise RuntimeError(
                f"blocked a LIVE network call to {request.url} - stub the "
                "transport (httpx.MockTransport) instead."
            )
        return real_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_get_preview_job_projects_a_known_stage_and_page_count(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "full", "companyId": "x", "entityType": "product"},
        progress_done=1, progress_total=3, cursor_json={"stage": "lookup:uom"},
    )
    db.add(job)
    db.commit()

    response = client.get(f"/autocount/previews/{job.id}", headers=_auth(client))
    assert response.status_code == 200, response.text
    progress = response.json()["progress"]
    assert progress == {"stage": "lookup:uom", "pagesDone": 1, "pagesTotal": 3}, progress


def test_get_preview_job_omits_progress_entirely_when_nothing_is_known_yet(client, db):
    job = BackgroundJob(
        tenant_id=DEFAULT_TENANT_ID, type=JOB_TYPE, status=JOB_RUNNING,
        payload_json={"scope": "sample", "companyId": "x", "entityType": "product"},
    )
    db.add(job)
    db.commit()

    response = client.get(f"/autocount/previews/{job.id}", headers=_auth(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["progress"] is None, body
