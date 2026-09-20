"""Read-only measurement script for the S1 live replay (Part B).

Reconstructs each staged product's CanonicalProduct from ac_staged_record.canonical_json
and calls the REAL app sink_payload() (never comparable()) to inspect the actual wire form
that would cross to Sorento - safely, because the company's sink stays 'logging' throughout.
No app code is modified; this only imports and calls existing methods.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

os.environ.setdefault("DATABASE_URL", "postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s40")

# Run from service_backend cwd (added to path by caller via PYTHONPATH or cwd)
from sqlalchemy import create_engine, text  # noqa: E402

from modules.autocount.canonical.masters import CanonicalProduct  # noqa: E402

engine = create_engine(os.environ["DATABASE_URL"])

COMPANY_ID = sys.argv[1] if len(sys.argv) > 1 else None

with engine.connect() as conn:
    q = text(
        "SELECT source_ref, canonical_json, raw_json FROM app_autocount.ac_staged_record "
        "WHERE company_id = :cid AND entity_type = 'product'"
    )
    rows = conn.execute(q, {"cid": COMPANY_ID}).fetchall()

print(f"total staged rows: {len(rows)}")

zero_delivered = 0
negative_clamped_examples = []
enrich_miss = 0
ref_prefix_ok = 0
ref_prefix_bad = []
price_is_string = 0
price_not_string = 0
has_uom_code = 0
has_cost_price = 0
has_remark = 0
has_is_discontinued = 0
double_space_desc = 0
sample_payloads = []
list_prices_seen = 0
negative_source_count = 0
negative_clamped_confirmed = 0

for source_ref, canonical_json, raw_json in rows:
    if isinstance(canonical_json, str):
        canonical_json = json.loads(canonical_json)
    if isinstance(raw_json, str):
        raw_json = json.loads(raw_json)
    record = CanonicalProduct(**canonical_json)
    payload = record.sink_payload()

    raw_price = (raw_json or {}).get("BaseUOMPrice")
    if raw_price is not None:
        try:
            if float(raw_price) < 0:
                negative_source_count += 1
                if "list_price" in payload and float(payload["list_price"]) == 0.0:
                    negative_clamped_confirmed += 1
        except (TypeError, ValueError):
            pass

    if source_ref.startswith("AED_SORENTO:"):
        ref_prefix_ok += 1
    else:
        ref_prefix_bad.append(source_ref)

    if "list_price" not in payload:
        enrich_miss += 1
    else:
        list_prices_seen += 1
        lp = payload["list_price"]
        if isinstance(lp, str):
            price_is_string += 1
        else:
            price_not_string += 1
        # delivered zero (post-clamp)
        try:
            if float(lp) == 0.0:
                zero_delivered += 1
        except (TypeError, ValueError):
            pass
        # source negative -> clamped, cross-check against raw BaseUOMPrice on canonical_json's
        # extras if present (not stored) - instead cross check via the ORIGINAL raw row we don't
        # have here; negative detection instead done in a second pass below using raw preview.

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

    if len(sample_payloads) < 5:
        sample_payloads.append({"source_ref": source_ref, "payload": payload})

print(f"ref_prefix AED_SORENTO: {ref_prefix_ok} / bad: {len(ref_prefix_bad)} (sample: {ref_prefix_bad[:5]})")
print(f"list_price present (enrich matched): {list_prices_seen}")
print(f"enrich miss (list_price absent): {enrich_miss}")
print(f"delivered list_price == 0 (post-clamp, includes negatives): {zero_delivered}")
print(f"price as JSON string: {price_is_string}, price NOT string: {price_not_string}")
print(f"payloads carrying uom_code key: {has_uom_code}")
print(f"payloads carrying cost_price key: {has_cost_price}")
print(f"payloads carrying remark key: {has_remark}")
print(f"payloads carrying is_discontinued key: {has_is_discontinued}")
print(f"description with internal double space: {double_space_desc}")
print(f"negative source BaseUOMPrice (raw < 0): {negative_source_count}")
print(f"of those, delivered list_price == 0 (clamped, confirmed): {negative_clamped_confirmed}")
print()
print("SAMPLE PAYLOADS (first 5):")
for s in sample_payloads:
    print(json.dumps(s, indent=2))
