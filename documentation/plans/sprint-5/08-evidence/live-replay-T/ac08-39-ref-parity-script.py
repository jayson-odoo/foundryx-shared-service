"""AC-08-39 ref-parity proof (tester-owned [T], recorded stub) - run against
the REAL lane Postgres DB (foundryx_service_s37), using the production
HttpApiSource + RowHashRepository + row_hash code paths directly (the same
primitives sinks_sorento/sync.py use), never the live hapi.sorento.cc.cd
network, never a Sorento push.

Scenario: a product task's ac_row_hash table is first seeded as if 20 rows
had come from a sql_db run (same key scheme AED_SORENTO:<ItemCode>, same
row_hash function over the same compared fields). The task's source_impl is
then switched to autocount_http and reconciled against a stub of the SAME
20 items, 5 of them carrying a changed Description (a real field edit).
Expect: 0 added, 0 deleted, 5 updated.
"""
import sys

sys.path.insert(0, ".")

import httpx

from app.database import SessionLocal
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany, AcEntityConfig, RUN_MODE_RECONCILE
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark
from modules.autocount.sql_source.hashing import row_hash
from modules.autocount.http_source.source import HttpApiSource

TS = "20260912T004004Z"
DB_NAME = f"AC0839_{TS}"
COMPARED = ["Description", "ItemGroup"]

db = SessionLocal()
try:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp",
        name=f"AC-08-39 stub conn {TS}",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db2", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name=DB_NAME,
        company_name=f"AC-08-39 ref parity {TS}", name=f"AC-08-39 ref parity {TS}",
        is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)

    # 20 "rows" as a sql_db run would have hashed them (same fields, same
    # row_hash function - the ONLY thing that changes on the switch is the
    # fetch transport, per plan 08 D-none/§2.4).
    rows = [
        {"ItemCode": f"SRT-{i:02d}", "Description": f"Item {i}", "ItemGroup": "GRP1"}
        for i in range(20)
    ]
    hashes = {
        f"{DB_NAME}:{r['ItemCode']}": row_hash(r, COMPARED) for r in rows
    }
    RowHashRepository(db).upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, hashes, seen_at=None)
    print(f"Seeded {len(hashes)} row hashes as if from a prior sql_db run.")

    # Switch the task to autocount_http against a stub of the SAME 20 keys;
    # 5 carry a genuinely different Description (a real field edit).
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id,
            "path": "/itembypage",
            "keyFields": ["ItemCode"],
            "watermarkField": None,
            "comparedFields": COMPARED,
            "distinctOf": None,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    stub_rows = []
    for i, r in enumerate(rows):
        row = dict(r)
        if i < 5:
            row["Description"] = f"Item {i} EDITED"
        stub_rows.append(row)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "TotalCount": len(stub_rows), "Page": 1, "PageSize": 1000,
                "TotalPages": 1, "Data": stub_rows,
            },
        )

    transport = httpx.Client(transport=httpx.MockTransport(handler))
    ctx = SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )
    source = HttpApiSource(
        ctx, entity_type=ENTITY_PRODUCT, mode=RUN_MODE_RECONCILE, transport=transport,
    )
    result = source.fetch_changes(Watermark())

    print(f"added_count={result.added_count}")
    print(f"updated_count={result.updated_count}")
    print(f"delete_refs={result.delete_refs}")
    print(f"rows_scanned={getattr(result, 'rows_scanned', None)}")

    assert result.added_count == 0, "expected 0 added on an impl switch with the same keys"
    assert result.delete_refs == [], "expected 0 deleted on an impl switch with the same keys"
    assert result.updated_count == 5, f"expected 5 updated (hash change only), got {result.updated_count}"
    print("AC-08-39: PASS - 0 added, 0 deleted, 5 updated (hash change only) on sql_db -> autocount_http switch")

    # Ref-parity proof (AC-08-27), same connection/company: a product
    # ItemCode "SRT-01" mints the SAME ref whether the task's source_impl is
    # sql_db or autocount_http (both use company_qualified_identity).
    ref = source.source_ref({"ItemCode": "SRT-01"})
    assert ref == f"{DB_NAME}:SRT-01", ref
    print(f"AC-08-27: PASS - ref = {ref} (company-qualified, same scheme as sql_db)")

finally:
    # Explicit cleanup (not a rollback - conn/company/config were already
    # committed above): leave the lane DB exactly as it was found.
    try:
        db.rollback()
        from modules.autocount.models import AcRowHash
        db.query(AcRowHash).filter(AcRowHash.company_id == company.id).delete()
        db.query(AcEntityConfig).filter(AcEntityConfig.company_id == company.id).delete()
        db.query(AcCompany).filter(AcCompany.id == company.id).delete()
        db.query(Connection).filter(Connection.id == conn.id).delete()
        db.commit()
        print("Cleanup: removed the throwaway AC-08-39 connection/company/config/hashes.")
    except Exception as cleanup_exc:  # noqa: BLE001
        db.rollback()
        print(f"CLEANUP FAILED: {cleanup_exc}")
    db.close()
