# Backend — scope-local rules (`dreamz_ems_backend/`)

> Read `../PRINCIPLES.md` first (governs). `../CLAUDE.md` is the deep reference. This file = backend-only essentials.

## Layering (enforced)
Router (`app/api/v1/`) — HTTP + Pydantic only, NO DB/raw SQL → Service (business logic) → Repository (SQLAlchemy). Auth = `Depends(get_current_user)`. **Every query tenant-scoped** (tenant from JWT). `require_permission("key")` gates protected endpoints.

## Must-dos
- **Datetimes:** `UTCDateTime` columns ONLY (never plain `DateTime`); in-memory aware-UTC `datetime.now(timezone.utc)`; schemas with datetime fields inherit `ApiModel`. Wire = camelCase (`Field(validation_alias="snake")` + `from_attributes`).
- **Migrations:** core via Alembic (`alembic revision --autogenerate` → `upgrade head`); modules via per-module Alembic. **Revision id ≤ 32 chars** (`alembic_version.version_num` is VARCHAR(32) — a longer id passes `create_all` tests but breaks real Postgres deploy). Conftest uses `create_all`, so a broken migration is invisible to pytest — verify `run_module_migrations`/`alembic upgrade` against live Postgres.
- **New permission:** add a CSV row (`app/permissions/permissions.csv` core, or `<module>/permissions/permissions.csv`). Grep core for key collisions first (`sync_permissions` is delete-by-module on a global unique key). Existing tenants' Admin does NOT auto-get it — re-run `tenant_admin_grant(db, tenant_id)` / ship a grant sweep.
- **New column/engine on an existing entity:** ship a BACKFILL (existing rows + existing tenant graphs), not just seed-if-absent in `install_tenant`/`update_tenant`.
- **Secrets:** Fernet via `app/secrets.py` (`FERNET_KEY` required). `encrypt_secret`/`decrypt_secret` — catch `InvalidToken` (clean reject, never 500).

## Modules (`modules/`)
Schema-isolated (`app_<name>`); never touch core `public`. Cross-schema→core = plain indexed column or sanctioned FK; cross-module = capability soft-ref (`resolve_capability`/`register_capability`), never a cross-module join/FK. Register into shared engines at install (status/rule/template/workflow/form/import/terminology) — don't fork them.

## Tests
`source .venv/bin/activate && python -m pytest -q`. In-memory SQLite + `schema_translate_map`. The pre-existing status-engine + tenant-lifecycle suites are load-bearing — keep them green.
