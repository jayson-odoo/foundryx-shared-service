# AUTOCOUNT-INDEX-JOB - move the 0047/0048 index backfills out of the migrations

Deploy of #250 aborted: the 0047 (`ac_spo_po_link`) and 0048 (`ac_so_row_index`) migrations backfill
from every staged shipping order / sales order inside `alembic upgrade` at backend start, which ran past
the 240 s health budget on prod.

Plan:
1. 0047/0048 create the tables + indexes only (no row work), so the migration is seconds.
2. A `background_jobs` handler (core `app/services/background_jobs`, the sprint-4/10 pattern) fills each
   index per (tenant, company) in batches, keyset-resumable, idempotent; a per-scope readiness row records
   when a scope's index is complete.
3. Until a scope's index is complete, every lookup that reads the index falls back to the old full-scan
   path for that call (correct, slower) - never a partial index answer.
4. Tests: partial index -> fallback; job resumes from its cursor; re-run is idempotent; migration timing.
