"""E2E seed helper for the omnichannel embed host (sprint-4/11).

Invoked by `e2e/omnichannel-embed.spec.ts` in `beforeAll` (via the backend
.venv python). Idempotently ensures the dev demo inbox exists (threads
cnt-001..005 on the dev-cred `chn-demo` channel - sends never hit Graph), then
creates/refreshes a single `omnichannel_shared` core connection for the `default`
tenant carrying a KNOWN `embedSecret` (Fernet-encrypted) + `allowedOrigins`.

Prints ONE line of JSON on stdout:
    {"connectionId": "...", "workspaceId": "...", "contactId": "cnt-001",
     "contactName": "Sarah Chen", "embedSecret": "...", "allowedOrigins": [...]}

Usage (from service_frontend):
    <backend .venv python> e2e/helpers/seed_embed_connection.py \
        --secret <embedSecret> --origin http://localhost:3001 \
        [--connection-id <fixed id>]

Run with cwd = service_backend so `app`/`modules` import. The spec resolves the
backend dir + its venv python and passes them.
"""
import argparse
import json
import sys

from app.database import SessionLocal
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.omnichannel.bootstrap import seed_demo_conversations
from modules.omnichannel.models import Contact, Workspace


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secret", required=True)
    ap.add_argument("--origin", action="append", required=True)
    ap.add_argument("--connection-id", default=None)
    ap.add_argument("--contact-id", default="cnt-001")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # 1) Ensure the deterministic dev demo inbox exists (idempotent).
        if db.query(Contact).filter(Contact.id == args.contact_id).first() is None:
            seed_demo_conversations(db, DEFAULT_TENANT_ID)
            db.commit()

        contact = db.query(Contact).filter(Contact.id == args.contact_id).first()
        if contact is None:
            print(
                json.dumps({"error": f"contact {args.contact_id} not seeded"}),
                file=sys.stderr,
            )
            return 2
        workspace_id = contact.workspace_id
        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        contact_name = " ".join(
            p for p in [contact.first_name, contact.last_name] if p
        ).strip()

        # 2) Create / refresh the omnichannel_shared connection with the known
        #    embedSecret + allowedOrigins. Reuse a fixed id if given so parallel
        #    reruns don't accumulate rows.
        conn = None
        if args.connection_id:
            conn = db.query(Connection).filter(Connection.id == args.connection_id).first()
        if conn is None:
            conn = Connection(
                id=args.connection_id,
                tenant_id=DEFAULT_TENANT_ID,
                provider="omnichannel_shared",
                type="omnichannel",
                name="E2E embed link",
                config_json={"allowedOrigins": list(args.origin)},
                credentials_json=encrypt_secret({"embedSecret": args.secret}),
                status="ACTIVE",
            )
            db.add(conn)
        else:
            conn.config_json = {"allowedOrigins": list(args.origin)}
            conn.credentials_json = encrypt_secret({"embedSecret": args.secret})
            conn.status = "ACTIVE"
        db.commit()

        print(
            json.dumps(
                {
                    "connectionId": conn.id,
                    "workspaceId": workspace_id,
                    "workspaceName": workspace.name if workspace else "",
                    "contactId": contact.id,
                    "contactName": contact_name,
                    "embedSecret": args.secret,
                    "allowedOrigins": list(args.origin),
                }
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
