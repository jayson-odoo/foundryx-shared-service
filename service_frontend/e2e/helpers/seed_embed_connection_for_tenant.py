"""E2E seed helper - embed connection for an ARBITRARY (dedicated) tenant.

Sibling of ``seed_embed_connection.py`` (which is hardcoded to the ``default``
tenant + the demo inbox). This one resolves a tenant by SLUG and inserts a single
``omnichannel_shared`` core connection carrying a KNOWN ``embedSecret``
(Fernet-encrypted) + ``allowedOrigins`` - used by the Developer-Logs Slice-3 E2E
(AC-DLC-24) to drive a real failing ``POST /embed/session`` exchange (→ an
``embed_session`` error activity row) on a DEDICATED tenant, so the default
tenant's live embed-config connection (depended on by other specs) is never
touched.

Prints ONE line of JSON on stdout:  {"connectionId": "...", "tenantId": "..."}

Usage (cwd = service_backend, backend .venv python):
    python e2e/helpers/seed_embed_connection_for_tenant.py \
        --tenant-slug <slug> --secret <embedSecret> \
        --origin https://consumer.example --connection-id <fixed id>
"""
import argparse
import json
import sys

from app.database import SessionLocal
from app.models.connection import Connection
from app.models.tenant import Tenant
from app.secrets import encrypt_secret


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--origin", action="append", required=True)
    ap.add_argument("--connection-id", default=None)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug == args.tenant_slug).first()
        if tenant is None:
            print(json.dumps({"error": f"tenant {args.tenant_slug} not found"}), file=sys.stderr)
            return 2

        conn = None
        if args.connection_id:
            conn = db.query(Connection).filter(Connection.id == args.connection_id).first()
        if conn is None:
            conn = Connection(
                id=args.connection_id,
                tenant_id=tenant.id,
                provider="omnichannel_shared",
                type="omnichannel",
                name="E2E DLC embed link",
                config_json={"allowedOrigins": list(args.origin)},
                credentials_json=encrypt_secret({"embedSecret": args.secret}),
                status="ACTIVE",
            )
            db.add(conn)
        else:
            conn.tenant_id = tenant.id
            conn.config_json = {"allowedOrigins": list(args.origin)}
            conn.credentials_json = encrypt_secret({"embedSecret": args.secret})
            conn.status = "ACTIVE"
        db.commit()
        print(json.dumps({"connectionId": conn.id, "tenantId": tenant.id}))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
