# 72 AutoCount project registrations feed (lane AUTOCOUNT-PROJECT-SYNC-SS, S0)

Status: in progress. S0 of the CRM plan AUTOCOUNT-PROJECT-SYNC (sorento-crm PR #2676).
Contract + UAC (S0-1..S0-14) live in the CRM repo; this file is the SS-side plan.

Scope (from the brief):
- New doc-feed kind `project_registrations` on the existing doc feed (`modules/autocount/doc_feed/`).
- Reads `GET /ProjectRegbyDate?Date=yyyymmdd` through the logged reader.
- One feed config row per book, start floor `2006-01-01`.
- The feed's own scheduled poll pushes to `POST /external/ingest/project_registrations`.
- Backfill: one day per call, oldest first, at most 1,000 records per push, own resumable cursor,
  one call in flight per book, dry-run pass with counts by month first.
- Pushes gated on the CRM reporting contract 2.15.
- AutoCount reads: db3 test book only, never db1 / db2.
