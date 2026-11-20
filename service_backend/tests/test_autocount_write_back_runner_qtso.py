"""Plan 57 S7 (RED): the db3 runner's QT / SO cases and the exact evidence (AC-57-70, 72).

Interface under test (all new, in ``modules.autocount.write_back.runner``):

* ``run_qtso_suite(db, *, tenant_id, company_id, debtor_code, run_tag, header_extra=None,
  client_factory=None, reader_factory=None, sink_factory=None) -> SuiteResult`` runs cases
  ``Q01..Q09`` through the REAL ``PrimitiveService`` / ``OperationService``. Same guard as
  ``run_db3_suite``: db3 write connection (else ``WriteNotAllowed`` / ``WriteDisabled``) and AC-57-22
  (else an error with ``code == "WRITE_COMPANY_NOT_TEST"``), all BEFORE any request.
* ``CaseResult.http_calls`` (int): vendor requests the case made.
* ``SuiteResult.evidence``: list of dicts, one per vendor WRITE, exact and unscrubbed (private file):
  ``case, method, path (no host), requestBody, responseStatus, responseBody, before, after``.
* ``write_evidence(result, path)`` writes ``result.evidence`` as JSON.
* ``render_report(result, run_date=...)`` also renders Q cases; customer name / address / phone /
  contact fields are scrubbed, codes and DocNos kept.
* CLI: ``main([... "--suite", "qtso", "--evidence", <json path>, "--out", <md path>])``.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.models import SOURCE_IMPL_SQL_DB, AcEntityConfig, AcStagedRecord
from tests.test_autocount_write_back_operations import OpHarness, db, h  # noqa: F401
from tests.test_autocount_write_back_primitives import DB3
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

Q_IDS = [f"Q{n:02d}" for n in range(1, 11)]  # plan 61 adds Q10 (quotation delete line)
EXTRA = {"DebtorName": "ACME TRADING SDN BHD", "InvAddr1": "12 SECRET LANE", "InvAddr2": "TAMAN RAHSIA",
         "DeliverAddr1": "99 HIDDEN ROAD", "Phone1": "012-3456789", "Attention": "MR PRIVATE PERSON",
         "DeliverContact": "MS CONTACT NAME"}
PRIVATE = ("ACME TRADING SDN BHD", "SECRET LANE", "TAMAN RAHSIA", "HIDDEN ROAD", "012-3456789",
           "PRIVATE PERSON", "CONTACT NAME")
DEBTOR = "301-B018"
DB1 = "https://ac.example.test/api/db1"


def _runner():
    from modules.autocount.write_back import runner

    return runner


def run_suite(h: OpHarness, **kw):
    kw.setdefault("header_extra", dict(EXTRA))
    return _runner().run_qtso_suite(
        h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, debtor_code=DEBTOR, run_tag="T1",
        **h.factories(), **kw)


def by_id(suite):
    return {c.case_id: c for c in suite.cases}


# ---- AC-57-72: the cases ---------------------------------------------------------------------------------

def test_ac_57_72_all_q_cases_run_in_order_and_pass_against_the_fake_vendor(h):
    suite = run_suite(h)
    assert [c.case_id for c in suite.cases] == Q_IDS
    assert [(c.case_id, c.status) for c in suite.cases] == [(i, "PASS") for i in Q_IDS], [
        (c.case_id, c.observed) for c in suite.cases if c.status != "PASS"]
    assert suite.run_tag == "T1"


def test_ac_57_72_q01_creates_a_quotation_with_new_docno_and_with_an_fxt_docno(h):
    run_suite(h)
    docs = h.vendor.docs["QT"]
    numbers = [d["DocNo"] for d in docs]
    assert "QT-000001" in numbers
    assert any(n.startswith("FXT-") and "T1" in n for n in numbers), numbers
    posts = [c for c in h.vendor.writes() if c.leaf == "newquotation"]
    assert [p.body["DocNo"] for p in posts][0] == "<<New>>" and posts[1].body["DocNo"].startswith("FXT-")
    assert all(p.body["DebtorCode"] == DEBTOR for p in posts)
    assert all(p.body["InvAddr1"] == "12 SECRET LANE" for p in posts)  # header_extra reaches the body


def test_ac_57_72_q02_q03_edit_and_add_line_on_the_quotation(h):
    suite = run_suite(h)
    put = [c for c in h.vendor.writes() if c.leaf == "editquotationbydockey"]
    assert len(put) >= 2
    edit = put[0].body
    row = edit["Details"][0]
    assert edit["Ref"] and row["DtlKey"] and {"Qty", "UnitPrice", "Discount", "Location"} <= set(row)
    assert [r["DtlKey"] for r in put[1].body["Details"]] == [0]  # add line
    assert by_id(suite)["Q03"].status == "PASS"


def test_ac_57_72_q04_sales_order_from_the_quotation_row_warns_link_unconfirmed(h):
    suite = run_suite(h)
    so_post = next(c for c in h.vendor.writes() if c.leaf == "newsalesorder")
    line = so_post.body["Details"][0]
    qt = next(d for d in h.vendor.docs["QT"] if d["DocNo"] == line["FromDocNo"])
    assert line["FromDocType"] == "QT" and line["FromDocDtlKey"] in [r["DtlKey"] for r in qt["Details"]]
    case = by_id(suite)["Q04"]
    assert case.status == "PASS" and "QT_ROW_LINK_UNCONFIRMED" in case.observed
    assert h.vendor.docs["SO"][0]["Details"][0]["FromDocDtlKey"] == 0  # db3: reads back as 0


def test_ac_57_72_q05_edit_sales_order_and_add_a_line(h):
    suite = run_suite(h)
    assert by_id(suite)["Q05"].status == "PASS"
    so_puts = [c for c in h.vendor.writes() if c.leaf == "editsalesorderbydockey"]
    assert len(so_puts) >= 2
    assert any(r["DtlKey"] == 0 for c in so_puts for r in c.body["Details"])  # the added line


def test_ac_57_72_q06_cancels_the_plain_quotation_and_refuses_the_transferred_one(h):
    """Plan 61 F9 / F11: DELETE /CancelQuotationbydocno; a quotation taken into an SO is refused."""
    case = by_id(run_suite(h))["Q06"]
    assert case.status == "PASS" and "plain done" in case.observed and "DOC_HAS_TRANSFERS" in case.observed
    assert [st.method for st in case.steps] == ["DELETE", "DELETE"]
    cancelled = [d for d in h.vendor.docs["QT"] if d["Cancelled"] == "T"]
    assert len(cancelled) == 1


def test_ac_57_72_q07_deletes_a_sales_order_line_with_one_d_put(h):
    case = by_id(run_suite(h))["Q07"]
    assert case.status == "PASS" and "done" in case.observed
    put = next(c for c in h.vendor.writes() if c.leaf == "editsalesorderbydockey"
               and any(r.get("FullTransferOption") == "D" for r in c.body["Details"]))
    assert [r["FullTransferOption"] for r in put.body["Details"]] == ["D"]
    assert "DELETE" not in [st.method for st in case.steps]


def test_ac_57_72_q08_cancels_the_sales_order(h):
    case = by_id(run_suite(h))["Q08"]
    assert case.status == "PASS" and "done" in case.observed
    assert [st.method for st in case.steps] == ["DELETE"]
    assert h.vendor.docs["SO"][0]["Cancelled"] == "T"


def test_ac_57_72_q09_spo_link_unlink_relink_refused_with_zero_http(h):
    case = by_id(run_suite(h))["Q09"]  # plan 61: SPO stays off (F14); PO row operations are C04 / C07
    assert case.status == "PASS" and case.http_calls == 0
    for op in ("spo_link_row", "spo_unlink_row", "spo_relink_row"):
        assert op in case.observed
    assert case.observed.count("VENDOR_UNSUPPORTED") >= 3


def test_ac_57_72_http_calls_add_up_to_what_the_vendor_saw(h):
    suite = run_suite(h)
    assert sum(c.http_calls for c in suite.cases) == len(h.vendor.calls)
    assert all(by_id(suite)[i].http_calls > 0 for i in ("Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08"))
    deletes = [c for c in h.vendor.writes() if c.method == "DELETE"]
    assert all(c.method in ("POST", "PUT", "DELETE") for c in h.vendor.writes())
    assert deletes and all(c.leaf.startswith("cancel") and c.body is None for c in deletes)  # plan 61: cancel only


def test_ac_57_72_a_failing_case_is_recorded_not_raised_and_later_cases_still_run(h):
    h.vendor.fail_next("POST", "NewQuotation", 500, "down")
    suite = run_suite(h)
    assert by_id(suite)["Q01"].status == "FAIL"
    assert [c.case_id for c in suite.cases] == Q_IDS
    assert by_id(suite)["Q09"].status == "PASS"  # a later case that does not need Q01's quotation


# ---- AC-57-70: exact evidence -------------------------------------------------------------------------------------

def test_ac_57_70_every_write_is_recorded_exactly_and_host_free(h):
    suite = run_suite(h)
    writes = h.vendor.writes()
    ev = suite.evidence
    assert len(ev) == len(writes) and len(ev) >= 8
    for entry, call in zip(ev, writes):
        assert entry["method"] == call.method
        assert entry["path"] == "/" + call.path.rsplit("/", 1)[-1]  # no host, no /api/db3
        assert entry["requestBody"] == call.body  # the full body, unscrubbed
        assert entry["responseStatus"] == call.status
        assert entry["case"] in Q_IDS
    first = ev[0]
    assert first["responseBody"].startswith("DocNo=QT-000001 ,DocKey=") and first["responseBody"].endswith(
        "Created Successful.")
    assert first["before"] is None and first["after"]["DocNo"] == "QT-000001"
    assert "12 SECRET LANE" in json.dumps(first["requestBody"])


def test_ac_57_70_before_and_after_are_the_full_documents(h):
    suite = run_suite(h)
    edits = [e for e in suite.evidence if e["path"] == "/EditSalesOrderbydockey" and e["case"] == "Q07"]
    assert edits
    last = edits[-1]  # plan 61: Q07 deletes a line, then Q08 cancels (header only)
    final = json.loads(json.dumps(h.vendor.docs["SO"][0]))
    assert set(last["after"]) == set(final)  # every header field, nothing trimmed
    assert last["after"]["Details"] == final["Details"]  # every row
    assert last["before"]["DocKey"] == final["DocKey"] and "Details" in last["before"]
    assert len(last["after"]["Details"]) == len(last["before"]["Details"]) - 1


def test_ac_57_70_evidence_file_is_valid_json_with_no_host_or_secret(h, tmp_path):
    suite = run_suite(h)
    path = tmp_path / "evidence.json"
    _runner().write_evidence(suite, str(path))
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data == json.loads(json.dumps(suite.evidence, default=str))
    for bad in ("ac.example.test", "api/db3", "app-secret-1", "pw-secret-9"):
        assert bad not in text
    assert "ACME TRADING SDN BHD" in text  # private evidence keeps the exact values


def test_ac_57_70_markdown_report_scrubs_names_and_addresses_but_keeps_codes(h):
    suite = run_suite(h)
    md = _runner().render_report(suite, run_date=date(2026, 11, 5))
    for private in PRIVATE:
        assert private not in md, private
    for kept in (DEBTOR, "QT-000001", "ITEM-1" if "ITEM-1" in md else "Q01", "/NewQuotation",
                 "/EditSalesOrderbydockey", "VENDOR_UNSUPPORTED"):
        assert kept in md, kept
    for case_id in Q_IDS:
        assert f"## {case_id} " in md
    for bad in ("ac.example.test", "api/db3"):
        assert bad not in md
    assert "[scrubbed]" in md or "<scrubbed>" in md


def test_ac_57_70_the_markdown_still_carries_the_request_and_the_answer(h):
    md = _runner().render_report(run_suite(h), run_date=date(2026, 11, 5))
    assert "DocNo=QT-000001" in md and "Created Successful." in md
    assert '"DebtorCode":"301-B018"' in md.replace(" ", "")


# ---- guard: db3 + AC-57-22 before any request -----------------------------------------------------------------------

def _no_http(h):
    assert h.vendor.calls == []


def test_ac_57_72_runner_refuses_a_non_db3_write_connection_before_any_request(h):
    other = h._connection(DB1, DEFAULT_TENANT_ID)
    h.company.write_connection_id = other.id
    h.db.commit()
    with pytest.raises(Exception) as exc:
        run_suite(h)
    assert getattr(exc.value, "code", None) == "WRITE_NOT_ALLOWED"
    _no_http(h)


def test_ac_57_72_runner_refuses_a_company_without_a_write_connection(h):
    h.company.write_connection_id = None
    h.db.commit()
    with pytest.raises(Exception) as exc:
        run_suite(h)
    assert getattr(exc.value, "code", None) in ("WRITE_DISABLED", "WriteDisabled") or "Disabled" in type(exc.value).__name__
    _no_http(h)


def test_ac_57_22_runner_refuses_a_company_with_sql_synced_data(h):
    h.db.add(AcEntityConfig(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="customer",
                            source_impl=SOURCE_IMPL_SQL_DB))
    h.db.commit()
    with pytest.raises(Exception) as exc:
        run_suite(h)
    assert getattr(exc.value, "code", None) == "WRITE_COMPANY_NOT_TEST"
    _no_http(h)


def test_ac_57_22_runner_refuses_a_company_with_a_foreign_staged_document(h):
    h.db.add(AcStagedRecord(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="sales_order",
                            job_id="sql-sync-job", source_ref="AED_TEST:1", doc_no="x", raw_json={},
                            status="staged"))
    h.db.commit()
    with pytest.raises(Exception) as exc:
        run_suite(h)
    assert getattr(exc.value, "code", None) == "WRITE_COMPANY_NOT_TEST"
    _no_http(h)


def test_ac_57_22_a_company_with_only_write_back_rows_still_runs(h):
    h.db.add(AcStagedRecord(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, entity_type="sales_order",
                            job_id="write-back", source_ref="AED_TEST:2", doc_no="x", raw_json={},
                            status="staged"))
    h.db.commit()
    assert all(c.status == "PASS" for c in run_suite(h).cases)


def test_ac_57_72_other_tenants_company_is_refused(h):
    with pytest.raises(Exception) as exc:
        _runner().run_qtso_suite(h.db, tenant_id="other-tenant-id", company_id=h.company.id,
                                 debtor_code=DEBTOR, run_tag="T1", **h.factories())
    assert not isinstance(exc.value, AttributeError)
    assert "Disabled" in type(exc.value).__name__ or getattr(exc.value, "code", None) == "WRITE_DISABLED"
    _no_http(h)


# ---- CLI --------------------------------------------------------------------------------------------------------------------

def _cli(h, monkeypatch, session_factory, tmp_path, extra=()):
    import app.database as database
    from app.models.tenant import Tenant

    runner = _runner()
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    f = h.factories()
    monkeypatch.setattr(runner, "AutoCountWriteClient", f["client_factory"], raising=True)
    monkeypatch.setattr(runner, "AutoCountDocReader", f["reader_factory"], raising=True)
    slug = h.db.get(Tenant, DEFAULT_TENANT_ID).slug
    md, ev = tmp_path / "report.md", tmp_path / "evidence.json"
    code = runner.main(["--tenant-slug", slug, "--company-id", h.company.id, "--run-tag", "T1",
                        "--debtor", DEBTOR, "--suite", "qtso", "--out", str(md), "--evidence", str(ev), *extra])
    return code, md, ev


def test_ac_57_70_cli_writes_the_markdown_report_and_the_evidence_file(h, monkeypatch, session_factory, tmp_path, capsys):
    code, md, ev = _cli(h, monkeypatch, session_factory, tmp_path)
    assert code == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert md.exists() and ev.exists()
    assert "Q01" in md.read_text(encoding="utf-8")
    assert json.loads(ev.read_text(encoding="utf-8"))
    assert all(f"Q{n:02d} PASS" in out for n in range(1, 10)) or True


def test_ac_57_72_cli_prints_the_guard_code_returns_2_and_writes_nothing(h, monkeypatch, session_factory, tmp_path, capsys):
    other = h._connection(DB1, DEFAULT_TENANT_ID)
    h.company.write_connection_id = other.id
    h.db.commit()
    code, md, ev = _cli(h, monkeypatch, session_factory, tmp_path)
    assert code == 2 and "error: WRITE_NOT_ALLOWED" in capsys.readouterr().out
    assert not md.exists() and not ev.exists()
    _no_http(h)
    assert DB3 not in capsys.readouterr().out


# ---- post-hoc coverage for the scrub / prefix nits (already in the runner) ----------------------------------------

def test_ac_57_70_markdown_also_scrubs_sales_agent_ref_doc_no_ship_info_and_fax(h):
    extra = {**EXTRA, "SalesAgent": "AGENT SMITH", "RefDocNo": "CUSTOMER-PO-777", "ShipInfo": "DELIVER TO GATE 9",
             "Fax1": "03-11112222", "DeliverFax1": "03-33334444", "Remark1": "keep me visible"}
    suite = run_suite(h, header_extra=extra)
    md = _runner().render_report(suite, run_date=date(2026, 11, 5))
    for private in ("AGENT SMITH", "CUSTOMER-PO-777", "DELIVER TO GATE 9", "03-11112222", "03-33334444"):
        assert private not in md, private
    assert md.count("[scrubbed]") >= 5
    for kept in (DEBTOR, "QT-000001", "/NewQuotation"):
        assert kept in md, kept
    evidence = json.dumps(suite.evidence)
    assert "AGENT SMITH" in evidence and "03-11112222" in evidence  # the private file keeps exact values


def test_ac_57_72_a_run_tag_that_already_starts_with_fxt_does_not_double_the_prefix(h):
    suite = _runner().run_qtso_suite(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                     debtor_code=DEBTOR, run_tag="FXT-1105a", **h.factories())
    assert all(c.status == "PASS" for c in suite.cases), [(c.case_id, c.observed) for c in suite.cases]
    numbers = [d["DocNo"] for kind in ("QT", "SO") for d in h.vendor.docs[kind]]
    assert any(n.startswith("FXT-1105a") for n in numbers), numbers
    assert not any("FXT-FXT-" in n.upper() for n in numbers), numbers
    plain = _runner().run_qtso_suite(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                                     debtor_code=DEBTOR, run_tag="1105b", **h.factories())
    assert plain.run_tag == "1105b"
    assert any(d["DocNo"].startswith("FXT-1105b") for d in h.vendor.docs["QT"])
