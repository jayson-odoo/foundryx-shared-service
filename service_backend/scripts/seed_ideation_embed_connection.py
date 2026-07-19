"""Seed / rotate an ideation embed connection (PLAN-ideation-embed-sso §7).

  python -m scripts.seed_ideation_embed_connection \
      --connection-id sorento-ideation \
      --signing-secret "<shared HS256 secret>" \
      --allowed-origin https://fe-sorento.foundryx.my \
      [--tenant-id <tenant>] [--product-id <product>] [--inactive]

Idempotent by ``connection_id`` — re-running rotates the secret / origins. The
secret is Fernet-encrypted at rest and never printed. The SAME ``connection_id``
+ ``signing_secret`` must be set on the host (sorento) default RespondWorkspace.
"""
import argparse

from app.database import SessionLocal
from app.models.tenant import DEFAULT_TENANT_ID
from modules.ideation.services.embed import upsert_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed an ideation embed connection.")
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--signing-secret", required=True)
    parser.add_argument(
        "--allowed-origin", action="append", default=[], dest="allowed_origins"
    )
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--product-id", default=None)
    parser.add_argument("--inactive", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        row = upsert_connection(
            db,
            connection_id=args.connection_id,
            tenant_id=args.tenant_id,
            signing_secret=args.signing_secret,
            allowed_origins=args.allowed_origins,
            product_id=args.product_id,
            is_active=not args.inactive,
        )
        print(
            f"embed connection '{row.connection_id}' seeded for tenant "
            f"'{row.tenant_id}' (active={row.is_active}, "
            f"origins={list(row.allowed_origins or [])})"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
