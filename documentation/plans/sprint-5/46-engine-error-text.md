# Plan 46: database error text

UAC: `46-engine-error-text-acceptance-criteria.md`. Size S. Branch `crew/ss-engine-settings`.

## Change

| Area | File | Change |
|---|---|---|
| App engine | `app/database.py:108` | `hide_parameters=True` |
| AutoCount SQL source | `modules/autocount/sql_provider.py:54`, `sql_source/runtime.py:338` | `hide_parameters=True` |
| Tests | new `tests/test_engine_error_text.py` | Per AC |

## Traps

- SQLAlchemy keeps the statement and replaces the values with a fixed marker; debugging uses the statement and the server log context.
- `echo=settings.debug` also stops printing values, which is intended.

## Slices

S1 tester red, coder; S2 lead kill; S3 reviewer plus security-reviewer.
