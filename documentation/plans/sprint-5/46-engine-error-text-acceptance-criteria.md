# Plan 46 acceptance criteria: database error text

| AC | Rule |
|---|---|
| AC-46-01 | [BE] The app's database engine (`app/database.py`) is created with `hide_parameters=True`: a database error's text names the statement and never the bound values |
| AC-46-02 | [BE] The same holds for the engines the AutoCount SQL source opens at run time (`modules/autocount/sql_provider.py`, `modules/autocount/sql_source/runtime.py`) |
| AC-46-03 | [BE] A real constraint error raised through the app engine carries no bound value in `str(exc)`; the statement is still there |
| AC-46-04 | [BE] Alembic environments and one-off scripts are unchanged |

No migration, no new permission, no screen change.
