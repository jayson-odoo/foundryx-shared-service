# Plan 46: database error text

UAC: `46-engine-error-text-acceptance-criteria.md`. Size M. Branch `crew/ss-engine-settings`. Plan 45 owns the job, run and snapshot error fields; this plan does not touch those lines.

## Design

```text
app/database.py      build_engine(url, **extra) -> Engine(hide_parameters=True, ...); engine = build_engine(settings.database_url)
app/db_errors.py     db_error_text(exc, what) -> "<what> (<Class>[, code <c>][, constraint <n>])."
                     reads exc.orig (psycopg2 pgcode, diag.constraint_name; pyodbc/pymssql/pymysql args[0] numbers)
sql_source/runtime.py sanitize_error -> known connection codes map to fixed sentences, everything else db_error_text
```

## Changes

| Area | File | Change |
|---|---|---|
| Builder | `app/database.py` | `build_engine`, used by the app engine |
| Helper | new `app/db_errors.py` | `db_error_text` |
| SQL source | `modules/autocount/sql_source/runtime.py:162-181`, `sql_provider.py` | Use the helper and the shared setting |
| App sites | `app/workflow_engine/executor.py:409,765`, `app/deferred_actions/service.py:458`, `app/services/document_service.py:569` | Use the helper |
| Tests | `tests/test_engine_error_text.py` plus new files | Per AC |

## Traps

- The operator's connection test must still say what to fix: map known codes to fixed sentences, never pass the driver text.
- Postgres puts values in DETAIL, the failing row and the LINE excerpt; never format `exc.orig`.
- CI's database URL points at a database that does not exist: tests build their own engine.

## Slices

S1 tester red, coder. S2 lead kill. S3 reviewer plus security-reviewer.
