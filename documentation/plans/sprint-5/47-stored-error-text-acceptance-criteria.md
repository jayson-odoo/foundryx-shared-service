# Plan 47 acceptance criteria: stored error text, remaining sites

Rule (as plan 46): a database or driver error that is stored, returned or emailed is reported as fixed text built by `app.db_errors.db_error_text`, never with the driver's message, a statement literal or a bound value. The detail goes to the server log.

| AC | Rule |
|---|---|
| AC-47-01 | [BE] A database error while the AutoCount Sorento sink commits a chunk is stored as fixed text in the run error, the task error, the incident's last error and the alert email |
| AC-47-02 | [BE] The AutoCount scheduler's stored task `last_run_error` follows the rule |
| AC-47-03 | [BE] The import engine's stored `errors_json` follows the rule for database errors; row validation messages the engine writes itself stay as they are |
| AC-47-04 | [BE] The gateway activity log's stored `errorMessage` follows the rule for database errors |
| AC-47-05 | [BE] A message the code builds for operators (no driver text) keeps its wording at every site above |

No migration, no new permission, no screen change.
