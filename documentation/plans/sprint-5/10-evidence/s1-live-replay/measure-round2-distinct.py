"""Round-2 post-review re-check measurement - identical logic to measure-run1.py but
DISTINCT ON (source_ref) so repeated unchanged runs (each of which appears to add a fresh
physical ac_staged_record row per the flagged pre-existing pile-up) do not double-count
products. Read-only, imports only, never modifies app code.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DATABASE_URL", "postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s40")

from sqlalchemy import create_engine, text  # noqa: E402
from modules.autocount.canonical.masters import CanonicalProduct  # noqa: E402

engine = create_engine(os.environ["DATABASE_URL"])
COMPANY_ID = sys.argv[1]

with engine.connect() as conn:
    q = text(
        "SELECT DISTINCT ON (source_ref) source_ref, canonical_json, raw_json "
        "FROM app_autocount.ac_staged_record "
        "WHERE company_id = :cid AND entity_type = 'product' "
        "ORDER BY source_ref, created_at DESC"
    )
    rows = conn.execute(q, {"cid": COMPANY_ID}).fetchall()

print(f"distinct products: {len(rows)}")

zero_delivered = 0
enrich_miss = 0
ref_prefix_ok = 0
ref_prefix_bad = []
price_is_string = 0
price_not_string = 0
has_uom_code = has_cost_price = has_remark = has_is_discontinued = 0
double_space_desc = 0
negative_source_count = 0
negative_clamped_confirmed = 0

for source_ref, canonical_json, raw_json in rows:
    if isinstance(canonical_json, str):
        canonical_json = json.loads(canonical_json)
    if isinstance(raw_json, str):
        raw_json = json.loads(raw_json)
    record = CanonicalProduct(**canonical_json)
    payload = record.sink_payload()

    if source_ref.startswith("AED_SORENTO:"):
        ref_prefix_ok += 1
    else:
        ref_prefix_bad.append(source_ref)

    raw_price = (raw_json or {}).get("BaseUOMPrice")
    if raw_price is not None:
        try:
            if float(raw_price) < 0:
                negative_source_count += 1
                if "list_price" in payload and float(payload["list_price"]) == 0.0:
                    negative_clamped_confirmed += 1
        except (TypeError, ValueError):
            pass

    if "list_price" not in payload:
        enrich_miss += 1
    else:
        lp = payload["list_price"]
        if isinstance(lp, str):
            price_is_string += 1
        else:
            price_not_string += 1
        try:
            if float(lp) == 0.0:
                zero_delivered += 1
        except (TypeError, ValueError):
            pass

    if "uom_code" in payload:
        has_uom_code += 1
    if "cost_price" in payload:
        has_cost_price += 1
    if "remark" in payload:
        has_remark += 1
    if "is_discontinued" in payload:
        has_is_discontinued += 1

    desc = payload.get("description", "") or ""
    if "  " in desc:
        double_space_desc += 1

print(f"ref_prefix AED_SORENTO: {ref_prefix_ok} / bad: {len(ref_prefix_bad)}")
print(f"list_price present (enrich matched): {len(rows) - enrich_miss}")
print(f"enrich miss: {enrich_miss}")
print(f"delivered list_price == 0 (post-clamp): {zero_delivered}")
print(f"price as JSON string: {price_is_string}, NOT string: {price_not_string}")
print(f"uom_code present: {has_uom_code}, cost_price present: {has_cost_price}, remark present: {has_remark}, is_discontinued present: {has_is_discontinued}")
print(f"description with internal double space: {double_space_desc}")
print(f"negative source BaseUOMPrice: {negative_source_count}, clamped-confirmed: {negative_clamped_confirmed}")
