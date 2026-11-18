"""Point a tenant's product phone step at the local stand-in product, on a
throwaway test copy ONLY (lane FEEDBACK-SUBSCRIBE, crew hand tests).

The share-link phone step (``modules/ideation/services/phone_verify.py``) asks
the tenant's ``consumer`` connection to look the phone up and to send the
6-digit code. On a test copy nothing should reach a real product, so this
script swaps that connection for a "ZZT stand-in product" connection pointing at
``scripts/fake_feedback_product.py`` (which prints the code instead of sending
a WhatsApp message).

A tenant holds ONE active consumer connection (``uq_connection_tenant_type``),
so ``seed`` parks (deactivates) the active ones and remembers them on the
stand-in row; ``restore`` deletes the stand-in and reactivates exactly those.
While the stand-in is active the copy also sends no status poke to a real CRM.

Usage, on the copy (backend venv, the copy's own ``.env``):

    python -m scripts.fake_feedback_product --port 8099 --known 60123450002="Contact B" &
    python -m scripts.crew_feedback_standin seed --allow-non-dev [--tenant default] [--base-url http://127.0.0.1:8099]
    ... hand test ...
    python -m scripts.crew_feedback_standin restore --allow-non-dev [--tenant default]

Refusals (nothing written): ``ENVIRONMENT=production``; any other environment
than ``development`` without ``--allow-non-dev``; a database host that is not
this machine (loopback); an unknown tenant. Idempotent: a second ``seed``
re-points the existing stand-in, a second ``restore`` does nothing.
"""
import argparse
import secrets
from typing import Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

STANDIN_PROVIDER = "zzt-standin"
STANDIN_NAME = "ZZT stand-in product"
CONSUMER_TYPE = "consumer"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


class StandinRefused(SystemExit):
    pass


def check_safe(environment: str, database_url: str, *, allow_non_dev: bool) -> None:
    """Raise ``StandinRefused`` unless this is a local, non-production copy."""
    env = (environment or "").strip().lower()
    if env in ("production", "prod"):
        raise StandinRefused("Refusing: ENVIRONMENT is production.")
    if env != "development" and not allow_non_dev:
        raise StandinRefused(
            f"Refusing outside ENVIRONMENT=development (now {env!r}); pass --allow-non-dev on a throwaway test copy."
        )
    host = (urlparse(database_url or "").hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        raise StandinRefused(f"Refusing: the database host {host!r} is not this machine.")


def _tenant_id(db: Session, slug_or_id: str) -> str:
    from app.models.tenant import Tenant

    row = (
        db.query(Tenant.id)
        .filter((Tenant.slug == slug_or_id) | (Tenant.id == slug_or_id))
        .first()
    )
    if row is None:
        raise StandinRefused(f"Refusing: no tenant {slug_or_id!r}.")
    return row[0]


def _standin(db: Session, tenant_id: str):
    from app.models.connection import Connection

    return (
        db.query(Connection)
        .filter(Connection.tenant_id == tenant_id, Connection.provider == STANDIN_PROVIDER)
        .first()
    )


def seed(db: Session, tenant: str, base_url: str, product_id: Optional[str] = None) -> Dict[str, object]:
    """Activate the stand-in for ``tenant``; park its other active consumer
    connections. Commits."""
    from app.models.connection import CONNECTION_STATUS_ACTIVE, Connection
    from app.secrets import encrypt_secret

    tenant_id = _tenant_id(db, tenant)
    row = _standin(db, tenant_id)
    others: List[Connection] = (
        db.query(Connection)
        .filter(
            Connection.tenant_id == tenant_id,
            Connection.type == CONSUMER_TYPE,
            Connection.is_active.is_(True),
            Connection.provider != STANDIN_PROVIDER,
        )
        .all()
    )
    parked = list((row.config_json or {}).get("parkedConnectionIds") or []) if row else []
    for conn in others:
        conn.is_active = False
        if conn.id not in parked:
            parked.append(conn.id)
    db.flush()
    config: Dict[str, object] = {"baseUrl": base_url.rstrip("/"), "parkedConnectionIds": parked}
    if product_id:
        config["productId"] = product_id
    if row is None:
        row = Connection(
            tenant_id=tenant_id,
            provider=STANDIN_PROVIDER,
            type=CONSUMER_TYPE,
            name=STANDIN_NAME,
            credentials_json=encrypt_secret({"apiKey": secrets.token_urlsafe(24)}),
        )
        db.add(row)
    row.config_json = config  # a fresh dict: SQLAlchemy misses in-place JSON edits
    row.is_active = True
    row.status = CONNECTION_STATUS_ACTIVE
    db.commit()
    return {"tenantId": tenant_id, "baseUrl": config["baseUrl"], "parked": len(parked)}


def restore(db: Session, tenant: str) -> Dict[str, object]:
    """Delete the stand-in and reactivate the connections it parked. Commits."""
    from app.models.connection import Connection

    tenant_id = _tenant_id(db, tenant)
    row = _standin(db, tenant_id)
    if row is None:
        return {"tenantId": tenant_id, "restored": 0}
    parked = list((row.config_json or {}).get("parkedConnectionIds") or [])
    db.delete(row)
    db.flush()
    restored = 0
    for conn in db.query(Connection).filter(Connection.tenant_id == tenant_id, Connection.id.in_(parked or ["-"])):
        conn.is_active = True
        restored += 1
    db.commit()
    return {"tenantId": tenant_id, "restored": restored}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["seed", "restore"])
    parser.add_argument("--tenant", default="default", help="tenant slug or id (default: default)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8099", help="where fake_feedback_product listens")
    parser.add_argument("--product-id", default=None, help="tag the stand-in to one product (optional)")
    parser.add_argument("--allow-non-dev", action="store_true", help="a throwaway test copy that is not ENVIRONMENT=development")
    args = parser.parse_args()

    from app.config import settings

    check_safe(settings.environment, settings.database_url, allow_non_dev=args.allow_non_dev)
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if args.action == "seed":
            out = seed(db, args.tenant, args.base_url, args.product_id)
            print(f"stand-in active for tenant {args.tenant!r} -> {out['baseUrl']} ({out['parked']} connection(s) parked)")
        else:
            out = restore(db, args.tenant)
            print(f"stand-in removed for tenant {args.tenant!r} ({out['restored']} connection(s) reactivated)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
