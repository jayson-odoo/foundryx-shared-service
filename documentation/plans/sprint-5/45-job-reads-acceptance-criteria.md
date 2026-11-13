# Plan 45 acceptance criteria: job reads and stored crash text

## Rules

| AC | Rule |
|---|---|
| AC-45-01 | [BE] Every registered job type either names the permission that reads it on the generic routes (`JobHandlerDef.read_permission`) or is marked as read only through its own module routes. A registered type with neither fails a registry test |
| AC-45-02 | [BE] `GET /jobs` lists only jobs whose type the caller may read, by `effective_permission_keys`; `total` counts the same set. A `type` filter for a type the caller may not read returns an empty page |
| AC-45-03 | [BE] `GET /jobs/{id}` for a job whose type the caller may not read answers 404 "Job not found.", the same as a missing id, including for a caller who may read no type at all |
| AC-45-04 | [BE] A job whose type has no registered handler is listed to nobody and answers 404 |
| AC-45-05 | [BE] A handler crash stores `Job crashed (<ClassName>).` as the job's error, never the exception's text. A handler that catches an error itself and fails the job, its run row or a snapshot that a gateway returns stores its own fixed sentence with the class name in that error field, never the exception's text; the detail goes to the server log. The storage connection sentence is unchanged. Result contents a module writes for its own screens follow that module's rules |
| AC-45-06 | [BE] Read permission per type: storage_migration `integrations.migrate_storage`; autocount_doc_feed_run, autocount_sync `autocount.sync.read`; autocount_doc_feed_backfill `autocount.companies.read`; meetings.calendar_sync, meetings.bot_run, meetings.transcribe `meetings.settings.manage`; omnichannel.broadcast_send `broadcasts.read`; omnichannel.contacts_export `contacts.export`; omnichannel.respondio_migration `omnichannel_migration.read`; omnichannel.report_export `reports.export` |
| AC-45-09 | [BE] autocount_doc_lookup, autocount_source_preview and autocount_pull_snapshot are read only through their module routes, which check each row; the generic routes list them to nobody and answer 404 |
| AC-45-10 | [BE] Scheduling a deferred `jobs.abort` or `jobs.complete` names a storage migration job; any other job id answers as a missing one |
| AC-45-07 | [BE] A user holding a type's permission reads it as before: list, detail, and the export pollers on `/jobs/{id}` |
| AC-45-08 | [E2E] `agent-browser` at 1280 and 375: a user with one module's read key sees only that module's jobs on the Jobs page; an admin sees all |

No new permission key, so no grant sweep. No migration. Frontend unchanged.
