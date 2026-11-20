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
        "ORDER BY source_ref, created_at ASC"
    )
    rows = conn.execute(q, {"cid": COMPANY_ID}).fetchall()

double_space_example = None
negative_example = None
zero_example = None

for source_ref, canonical_json, raw_json in rows:
    if isinstance(canonical_json, str):
        canonical_json = json.loads(canonical_json)
    if isinstance(raw_json, str):
        raw_json = json.loads(raw_json)
    record = CanonicalProduct(**canonical_json)
    payload = record.sink_payload()
    desc = payload.get("description", "") or ""
    raw_price = (raw_json or {}).get("BaseUOMPrice")

    if double_space_example is None and "  " in desc:
        double_space_example = {"source_ref": source_ref, "raw_description": raw_json.get("Description"), "raw_desc2": raw_json.get("Desc2"), "delivered_payload": payload}
    if negative_example is None and raw_price is not None and float(raw_price) < 0:
        negative_example = {"source_ref": source_ref, "raw_BaseUOMPrice": raw_price, "delivered_payload": payload}
    if zero_example is None and raw_price is not None and float(raw_price) == 0.0:
        zero_example = {"source_ref": source_ref, "raw_BaseUOMPrice": raw_price, "delivered_payload": payload}

    if double_space_example and negative_example and zero_example:
        break

print("=== double-space description example ===")
print(json.dumps(double_space_example, indent=2))
print("=== negative-clamped-to-zero example ===")
print(json.dumps(negative_example, indent=2))
print("=== raw-zero example ===")
print(json.dumps(zero_example, indent=2))
