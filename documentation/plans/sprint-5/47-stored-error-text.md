# Plan 47: stored error text, remaining sites

UAC: `47-stored-error-text-acceptance-criteria.md`. Size S to M. Branch `crew/ss-stored-error-text`. Reuses `app/db_errors.py` from plan 46.

| Area | File | Change |
|---|---|---|
| Sorento sink | `modules/autocount/sinks_sorento.py` (chunk commit), `services/sync_service.py` | Database errors through `db_error_text` |
| Scheduler | `modules/autocount/scheduler.py` (task last run error) | Same |
| Import engine | `app/import_engine/service.py` (stored errors) | Same, database errors only |
| Activity log | `app/activity_log/middleware.py` (stored error message) | Same |
| Tests | new test files per AC | Real driver error objects where possible |

Traps: run tests under a sqlite and a Postgres-shaped URL; keep operator-built messages; never format `exc.orig`.

Slices: S1 tester red, coder. S2 lead kill. S3 reviewer plus security-reviewer.
