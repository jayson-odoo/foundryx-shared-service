# Plan 46 acceptance criteria: database error text

## Engine setting

| AC | Rule |
|---|---|
| AC-46-01 | [BE] The app's database engine is created with `hide_parameters=True` through one shared builder in `app/database.py`, so SQLAlchemy's parameter list and echo output carry no bound values |
| AC-46-02 | [BE] The engines the AutoCount SQL source opens at run time use the same setting |
| AC-46-03 | [BE] Tests build an engine through that shared builder on a local URL; they never depend on the deployed database |
| AC-46-04 | [BE] Alembic environments and one-off scripts are unchanged |

## Shared error text

| AC | Rule |
|---|---|
| AC-46-05 | [BE] One helper turns a database or driver error into fixed text: a caller's sentence, the error class, and when the driver gives them, the error code (SQLSTATE or driver number) and the constraint name. It never includes the driver's message or detail, a statement literal, or a bound value. Postgres, SQL Server and MySQL errors are covered |
| AC-46-06 | [BE] The AutoCount SQL source uses the helper for every error text it returns or stores: the error response of the test and preview routes, the call record, run and task errors, the incident's last error and the alert email. Connection errors an operator must act on (login refused, database not found, host not reachable, timeout) keep a fixed sentence per known code |
| AC-46-07 | [BE] These app sites use the helper: the workflow node error, the deferred action error and the document download error |
| AC-46-08 | [BE] The full detail goes to the server log only |

No migration, no new permission, no screen change. Job, run and snapshot error fields covered by plan 45 are not touched here.
