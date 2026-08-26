"""Quick dev setup: create_all + seed (no migrations).

For the canonical, migration-based path (and on-prem deploys) use
`python -m scripts.bootstrap_db` instead. This remains handy for a fast local
reset:  python -m scripts.init_db
"""
from app.database import Base, SessionLocal, engine
from app.module_loader import bootstrap_modules
from app.seed import seed_all


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_all(db)
        print("seeded: tenant + roles + demo users")
    finally:
        db.close()
    # Module catalog + global installs + backfill (plan 08) - without this a
    # fresh init_db DB has an empty App Store and no module tables.
    bootstrap_modules()
    print("modules: catalog synced + installed")

    # DEV demo inbox (plan 05): sandbox channel + threads/templates/quick
    # replies so the inbox is explorable + E2E has deterministic fixtures.
    from app.config import settings

    if settings.environment == "development":
        from app.models.tenant import DEFAULT_TENANT_ID
        from modules.omnichannel.bootstrap import seed_demo_conversations
        from modules.omnichannel.services.seed_demo_workflow import seed_demo_ai_workflow

        db = SessionLocal()
        try:
            seed_demo_conversations(db, DEFAULT_TENANT_ID)
            print("omnichannel: demo conversations seeded")
            seed_demo_ai_workflow(db, DEFAULT_TENANT_ID)
            print("omnichannel: demo AI workflow seeded")
        finally:
            db.close()


if __name__ == "__main__":
    main()
