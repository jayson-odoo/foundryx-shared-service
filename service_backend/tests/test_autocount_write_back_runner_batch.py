"""Plan 62 S5: the db3 runner's ``--suite batch`` (B00..B11), run against the fake vendor.

``run_batch_suite`` drives the REAL ``OperationService`` (ops ``link_batch`` / ``link_row`` /
``unlink_row``) over documents it creates, taps every vendor request into the exact evidence, and renders
a timing table. Same db3 guards as the other suites (all BEFORE any request).
"""

from __future__ import annotations

import json

import pytest

from app.models import DEFAULT_TENANT_ID
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

IDS = [f"B{n:02d}" for n in range(0, 12)]
DB1 = "https://ac.example.test/api/db1"


def _runner():
    from modules.autocount.write_back import runner

    return runner


def run_suite(h: OpHarness):
    h.vendor.stamp_created = True  # created documents carry CreatedTimeStamp, as db3 does (the create-resend lookup)
    return _runner().run_batch_suite(
        h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, creditor_code="400-N004",
        debtor_code="301-B018", run_tag="T1", **h.factories())


def test_the_setup_and_batch_cases_pass_in_order_against_the_fake_vendor(h):
    suite = run_suite(h)
    assert [c.case_id for c in suite.cases] == IDS
    by = {c.case_id: c for c in suite.cases}
    assert [(i, by[i].status) for i in IDS] == [(i, "PASS") for i in IDS], [
        (c.case_id, c.observed) for c in suite.cases if c.status != "PASS"]


def test_a_batch_is_one_put_and_the_timing_table_names_every_case(h):
    suite = run_suite(h)
    assert "## Timings" in suite.summary and "batch of 5" in suite.summary and "today: 3 calls" in suite.summary
    puts = [e for e in suite.evidence if e["method"] == "PUT" and e["case"] == "B03"]
    assert 1 <= len(puts) <= 2  # PUT 1 and at most one restore PUT


def test_the_evidence_is_json_without_a_host(h, tmp_path):
    suite = run_suite(h)
    path = tmp_path / "e.json"
    _runner().write_evidence(suite, str(path))
    text = path.read_text()
    assert json.loads(text) and "ac.example.test" not in text


def test_the_report_renders_the_batch_cases(h):
    from datetime import date

    text = _runner().render_report(run_suite(h), run_date=date(2026, 11, 11))
    assert "B03" in text and "## Timings" in text


def test_the_suite_refuses_a_non_db3_write_connection_before_any_request(h):
    other = h._connection(DB1, DEFAULT_TENANT_ID)
    h.company.write_connection_id = other.id
    h.db.commit()
    with pytest.raises(Exception) as exc:
        run_suite(h)
    assert getattr(exc.value, "code", None) == "WRITE_NOT_ALLOWED"
    assert h.vendor.calls == []
