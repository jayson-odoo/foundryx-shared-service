"""FULFIL-SO-REMARK fix round 1: frozen target texts, ship_info null, line
tiebreak, update gate."""
from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.documents import (
    ENTITY_SALES_ORDER,
    CanonicalSalesOrder,
)
from modules.autocount.mapping import SCOPE_HEADER, SCOPE_LINE
from modules.autocount.models import AcFieldMapping
from modules.autocount.presets import _SO_HEADER_QUERY, _SO_LINE_QUERY

from tests.test_autocount_so_remark_fields import _company, _rows, _task, db  # noqa: F401


def test_frozen_remark_targets_equal_todays_preset():
    # The next preset lane must re-pin these consciously (0025 precedent).
    from modules.autocount.backfill import _REMARK_SO_HEADER_QUERY, _REMARK_SO_LINE_QUERY

    assert _REMARK_SO_HEADER_QUERY == _SO_HEADER_QUERY
    assert _REMARK_SO_LINE_QUERY == _SO_LINE_QUERY


def test_blank_ship_info_goes_out_as_null_on_v2():
    for value in (None, ""):
        so = CanonicalSalesOrder(
            source_ref="AED:SO:1", so_number="SO-1", status="open", ship_info=value,
        )
        payload = so.sink_payload(contract_version=2)
        assert "ship_info" in payload and not payload["ship_info"], payload


def test_ship_info_is_capped_at_255_like_po_ref():
    with pytest.raises(ValidationError):
        CanonicalSalesOrder(
            source_ref="AED:SO:1", so_number="SO-1", status="open", ship_info="x" * 256,
        )


def test_section_heading_apply_is_top_1_with_a_dtlkey_tiebreak():
    assert re.search(r"OUTER APPLY \(SELECT TOP 1 x\.Description AS SectionHeading", _SO_LINE_QUERY)
    assert re.search(r"ORDER BY x\.Seq DESC,\s*x\.DtlKey DESC\)", _SO_LINE_QUERY), _SO_LINE_QUERY


def test_update_tenant_from_0_18_0_does_not_rerun_the_remark_backfill(db):  # noqa: F811
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_RM_GATE")
    _task(
        db, company,
        query="SELECT h.DocKey FROM AED_RM_GATE.dbo.SO AS h",
        line_query="SELECT d.DtlKey FROM AED_RM_GATE.dbo.SODTL AS d WHERE d.DocKey = :doc_key",
        columns=["DocKey"], line_columns=["DtlKey"],
    )
    update_tenant(db, DEFAULT_TENANT_ID, "0.17.0")
    db.commit()
    db.expire_all()
    for scope, field in ((SCOPE_HEADER, "ship_info"), (SCOPE_LINE, "line_remark"),
                         (SCOPE_LINE, "section_heading")):
        for row in _rows(db, company.id, scope, field):
            db.delete(row)
    db.commit()
    update_tenant(db, DEFAULT_TENANT_ID, "0.18.0")
    db.commit()
    db.expire_all()
    for scope, field in ((SCOPE_HEADER, "ship_info"), (SCOPE_LINE, "line_remark"),
                         (SCOPE_LINE, "section_heading")):
        assert _rows(db, company.id, scope, field) == [], (scope, field)
