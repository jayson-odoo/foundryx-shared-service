"""AC-08-37 'flip one item's compared field in a recorded stub' proof - a
clean, minimal two-pass run (explicit comparedFields, no fallback ambiguity)
against a throwaway customer-entity config on a REAL, currently-existing
connection, cleaned up on exit. Complements the live product/customer
Activate+Run(x2) proof recorded in this pass's README with the SPECIFIC
"flip a field -> exactly 1 updated" assertion the AC calls out as a stub
step.
"""
import sys
sys.path.insert(0, ".")

import httpx

from app.database import SessionLocal
from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import AcCompany, AcEntityConfig, RUN_MODE_RECONCILE
from modules.autocount.repositories import RowHashRepository, EntityConfigRepository, CompanyRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.http_source.source import HttpApiSource

# `all_hashes()` (RECONCILE mode) reads EVERY row_hash for (tenant, company,
# entity_type) with no ref-pattern scoping, so reusing the REAL live
# customer task's (company_id, 'customer') pair here would collide with the
# 2,508 real hashes just staged by this pass's live runs (confirmed: it
# tripped the REAL delete guard, "would delete 2508 of 2508" - a genuine,
# useful confirmation the guard fires on live data, but not this proof). A
# throwaway company (same real connection, cleaned up on exit - exactly the
# AC-08-39 pattern) isolates this specific "flip one field" assertion.
CONN_ID = "7ff8b70d-26c8-4c8d-8cc6-b42e328b7b4f"  # the real, live Mocha REST connection from this pass

db = SessionLocal()
company = None
config = None
try:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=CONN_ID, database_name="FLIPTEST_20260912",
        company_name="AC-08-37 flip-test throwaway", name="AC-08-37 flip-test throwaway",
        is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=ENTITY_CUSTOMER, source_impl="autocount_http",
        source_config={
            "connectionId": CONN_ID, "path": "/debtorbypage", "keyFields": ["AccNo"],
            "watermarkField": None, "comparedFields": ["CompanyName"],
            "incrementalMinutes": 15, "reconcileMode": "dailyAt", "reconcileAt": "02:00",
        },
    )

    rows_pass1 = [
        {"AccNo": "FLIP-TEST-01", "CompanyName": "Original Co A"},
        {"AccNo": "FLIP-TEST-02", "CompanyName": "Original Co B"},
    ]
    rows_pass2 = [
        {"AccNo": "FLIP-TEST-01", "CompanyName": "Original Co A"},        # unchanged
        {"AccNo": "FLIP-TEST-02", "CompanyName": "Original Co B FLIPPED"},  # changed
    ]

    def make_handler(rows):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"TotalCount": len(rows), "Page": 1, "PageSize": 1000, "TotalPages": 1, "Data": rows},
            )
        return handler

    ctx = SourceContext(db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
                         company_service=CompanyService(db))

    # Pass 1: seeds the two hashes (the "first run").
    source1 = HttpApiSource(ctx, entity_type=ENTITY_CUSTOMER, mode=RUN_MODE_RECONCILE,
                             transport=httpx.Client(transport=httpx.MockTransport(make_handler(rows_pass1))))
    result1 = source1.fetch_changes(Watermark())
    print(f"PASS 1: added={result1.added_count} updated={result1.updated_count} deleted={len(result1.delete_refs)}")
    assert result1.added_count == 2 and result1.updated_count == 0

    # Pass 2: ONE field flipped on FLIP-TEST-02 - the "second run".
    source2 = HttpApiSource(ctx, entity_type=ENTITY_CUSTOMER, mode=RUN_MODE_RECONCILE,
                             transport=httpx.Client(transport=httpx.MockTransport(make_handler(rows_pass2))))
    result2 = source2.fetch_changes(Watermark())
    print(f"PASS 2: added={result2.added_count} updated={result2.updated_count} deleted={len(result2.delete_refs)}")
    assert result2.added_count == 0, result2.added_count
    assert result2.delete_refs == [], result2.delete_refs
    assert result2.updated_count == 1, f"expected 1 updated, got {result2.updated_count}"
    print("AC-08-37 flip proof: PASS - 0 added, 0 deleted, 1 updated (CompanyName flipped on FLIP-TEST-02 only)")
finally:
    try:
        from modules.autocount.models import AcRowHash
        db.rollback()
        if company is not None:
            db.query(AcRowHash).filter(AcRowHash.company_id == company.id).delete(synchronize_session=False)
            db.query(AcEntityConfig).filter(AcEntityConfig.company_id == company.id).delete(synchronize_session=False)
            db.query(AcCompany).filter(AcCompany.id == company.id).delete(synchronize_session=False)
            db.commit()
            print("Cleanup: removed the throwaway flip-test company/config/hashes.")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"CLEANUP FAILED: {exc}")
    db.close()
