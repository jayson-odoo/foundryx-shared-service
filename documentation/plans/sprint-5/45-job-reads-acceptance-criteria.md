# Plan 45 acceptance criteria: job reads and stored crash text

## Rules

| AC | Rule |
|---|---|
| AC-45-01 | [BE] Every registered job type names the permission that reads it (`JobHandlerDef.read_permission`). A registered type without one fails a registry test |
| AC-45-02 | [BE] `GET /jobs` lists only jobs whose type the caller may read, by `effective_permission_keys`; `total` counts the same set. A `type` filter for a type the caller may not read returns an empty page |
| AC-45-03 | [BE] `GET /jobs/{id}` for a job whose type the caller may not read answers 404 "Job not found.", the same as a missing id |
| AC-45-04 | [BE] A job whose type has no registered handler is listed to nobody and answers 404 |
| AC-45-05 | [BE] A handler crash stores `Job crashed (<ClassName>).` as the job's error, never the exception's text. The storage connection sentence is unchanged |
| AC-45-06 | [BE] Read permission per type: storage_migration `integrations.migrate_storage`; autocount_doc_feed_run, autocount_sync `autocount.sync.read`; autocount_doc_feed_backfill, autocount_source_preview `autocount.companies.read`; autocount_doc_lookup, autocount_pull_snapshot `autocount.pull.read`; meetings.calendar_sync, meetings.bot_run, meetings.transcribe `meetings.settings.manage`; omnichannel.broadcast_send `broadcasts.read`; omnichannel.contacts_export `contacts.export`; omnichannel.respondio_migration `omnichannel_migration.read`; omnichannel.report_export `reports.export` |
| AC-45-07 | [BE] A user holding a type's permission reads it as before: list, detail, and the export pollers on `/jobs/{id}` |
| AC-45-08 | [E2E] `agent-browser` at 1280 and 375: a user with one module's read key sees only that module's jobs on the Jobs page; an admin sees all |

No new permission key, so no grant sweep. No migration. Frontend unchanged.
