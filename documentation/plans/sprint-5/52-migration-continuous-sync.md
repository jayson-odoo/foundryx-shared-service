# 52 - respond.io continuous sync until cutover (plan)

Lane SS-MIGRATION-SYNC. UAC: `52-migration-continuous-sync-acceptance-criteria.md` (the contract).
Card + owner answers: `ss-migration-sync-card.md`. Builds on plan 33 (respond.io migration) and
#179 (skip channel, re-link on re-run).

## 1. Decisions

| Id | Decision | Why |
|---|---|---|
| D1 | A **sync** = one `migration_syncs` row per (tenant, workspace). Ticks are `background_jobs` of a new type `omnichannel.respondio_sync` (payload `{syncId, kind}`) | house rule: any new async job rides `background_jobs`; the Jobs drawer shows ticks for free |
| D2 | Mapping (connection, channel/user/team/lifecycle maps, `messagesSince`) is read at EACH tick from the newest DONE `run`-mode `source=api` migration job of the workspace | the #179 flow (re-run with the channel mapped) updates the sync with no new mapping UI (AC-SYNC-17) |
| D3 | Tick kinds: `poll` (contact walk + hints + new contacts + full sweep when due), `hints` (only flagged contacts, between polls), `final` (poll WITH a full sweep, then cutover CSW + `stopped`). Sync now also forces a full sweep (clears `last_full_sweep_at`). Crew ruling 4 Nov: a new message on an existing contact without a webhook hint must not wait 6 h nor be lost at Stop | Q1/Q2 + crew ruling |
| D4 | Scheduling = one 60 s beat task `omnichannel.migration_sync_due` (`app/workflow_engine/worker.py`, the sole beat host, same guarded pattern as `omnichannel.broadcasts_due`) calling `run_due_syncs(db)`. Per active sync: skip if a sync job or a migration job for the workspace is pending/running; else enqueue `hints` if hints exist and the poll is not due, `poll` if `next_sync_at <= now`. Claim with a guarded UPDATE of `next_sync_at` / a `running_job_id` so two beats cannot double-enqueue | webhook-flagged contacts land within ~1-2 min; no per-webhook job storm |
| D5 | The webhook is a **hint**: store `(sync_id, external_contact_id)` only; never trust or write the payload; the tick re-reads from the API with our token | a forged webhook can at most cause a rate-limited re-read (security) |
| D6 | Webhook auth = 256-bit random secret in the URL path, Fernet-encrypted at rest (`app/secrets.encrypt_secret`), compared with `hmac.compare_digest`. respond.io signature verification is NOT built (scheme unverified; backlog) | works with any respond.io webhook setup; secret in URL is the documented capability |
| D7 | Writer gets `contact_mode: "fill_empty" (default) | "source_wins"`; the sync uses `source_wins` (Q3). Only non-empty source values overwrite; tags = exact source set; lifecycle/assignee only when mapped; thread open/closed from source `status`; write only on difference; `emit=False` | Q3 + never clear SS data by accident |
| D8 | Messages: reuse `_process_contact_messages` unchanged except: the writer stores `payload_json.migration.channelMessageId` and skips (counts `skip`) when that WhatsApp id exists natively in the tenant (`ConversationMessage.external_message_id`, indexed) | AC-SYNC-14; a WABA number lives on one BSP at a time, so the reverse order (sync first, then native) cannot happen for the same message; no change to the native inbound path |
| D9 | Per touched contact: identities -> messages (+#179 re-link) -> media for message refs created in this tick for that contact -> events. One savepoint + commit per contact. Uses the existing `_process_contact_identities`, `_process_contact_messages`, `_process_message_media`, `_process_contact_events` | one code path with the migration |
| D10 | Mutual exclusion with the one-off migration: `MigrationService._in_progress_job` also counts pending/running sync jobs; the sweep skips a workspace with a pending/running migration job | concurrent writers on the same refs would race the unique index |
| D11 | 401/403 -> `paused/token_rejected` + one outbox email to the creator (`email_service.enqueue_raw`). Missing connection/workspace -> `paused` with reason. Nothing auto-stops (Q5) | |
| D12 | Stop = `stopping` + enqueue `final`. After it: for respond.io-migrated contacts in the workspace set `csw_expires_at = last_incoming_message_at + 24h` when in the future; then `stopped`. Restart from `stopped` re-activates the same row | agents can reply free-form straight after cutover |
| D13 | Contact count is a dry-run measurement: `sourceContactCount` comes from the latest dry run's `report.entities.contacts.fetched` until a tick walks the list; `estimatedFullSweepMinutes = ceil(n * 3 / rps / 60)` (rps from the connection, default 4) | owner gave no count; never measured from the sandbox |
| D14 | No new permission: reads `omnichannel_migration.read`, writes `omnichannel_migration.manage` | no grant sweep needed |

## 2. Data (module `app_omnichannel`, migration `0024_omni_migration_sync`)

`migration_syncs`: `id`, `tenant_id` (idx), `workspace_id` (FK workspaces), `status`
(`active|paused|stopping|stopped`), `paused_reason` (nullable), `interval_minutes` (15),
`full_sweep_hours` (6), `webhook_secret_enc`, `created_by_user_id`, `last_sync_at`,
`next_sync_at` (idx), `last_full_sweep_at`, `running_job_id`, `last_error`,
`last_result_json`, `totals_json`, `source_contact_count`, `stopped_at`, `created_at`,
`updated_at`. UNIQUE(`tenant_id`, `workspace_id`). All datetimes `UTCDateTime`, JSON
`JSON(none_as_null=True)`.

`migration_sync_hints`: `id`, `tenant_id`, `sync_id` (FK, idx), `external_contact_id`,
`created_at`. UNIQUE(`sync_id`, `external_contact_id`). The tick claims by selecting then
deleting the rows it read (hints arriving mid-tick stay for the next one).

No backfill: both tables are new and start empty; no existing row gains a column.

## 3. API (router `migration_sync.py`, prefix `/omnichannel/migration/syncs`, gated module)

- `GET ?workspaceId=` -> `MigrationSyncItem | null` (read)
- `GET /{id}` (read); `POST {workspaceId}` (manage, AC-SYNC-01..03)
- `POST /{id}/run-now | /pause | /resume | /stop` (manage)
- `GET /{id}/webhook` -> `{url}` (manage); `POST /{id}/webhook/rotate` -> `{url}` (manage)

`MigrationSyncItem` (ApiModel): `id, workspaceId, status, pausedReason, intervalMinutes,
fullSweepHours, lastSyncAt, nextSyncAt, lastFullSweepAt, runningJobId, lastError,
lastResult{contactsCreated, contactsUpdated, messagesCreated, messagesSkipped, errors,
failureSample[]}, totals{same counters}, sourceContactCount, estimatedFullSweepMinutes,
sourceJobId, stoppedAt, createdAt`.

Public router `migration_sync_hooks.py`, `"public": true`, prefix `/omnichannel/migration-hooks`:
`POST /{sync_id}/{secret}`. Read at most 64 KB + 1 (413 above). Lookup sync unscoped by id, then
verify module active for its tenant, status in (`active`, `paused`, `stopping`), secret
compare - any failure 404 `{"detail":"Not Found"}`. Invalid JSON or no usable contact id
(digits, 1-20) -> 204. Hint stored (insert-ignore) -> 200 `{"ok": true}`. Cap 5000 pending.

URL base = `settings.public_base_url`.

## 4. Service layout

- `services/migration_sync_service.py`: `MigrationSyncService` (CRUD/lifecycle, item mapping),
  `run_due_syncs(db)` (beat body), `run_sync_job(db, job)` (handler, registered beside the
  migration handler), `record_hint(db, sync_id, secret, body)`.
- `repositories/migration_sync_repository.py` (tenant-scoped reads + the unscoped by-id read
  used ONLY by the public hook before the secret check).
- `migration_writer.py`: `contact_mode` (D7), `channelMessageId` store + native skip (D8).
- `migration_service.py`: shared helpers stay where they are; `_in_progress_job` widened (D10).

## 5. Frontend (Phase 1 mock first, then real)

`[jobId]/page.tsx` gains `<MigrationSyncCard jobId workspaceId />` under the report for DONE
real API runs. Service trio `respondio-migration-service.{ts,mock,real}` gains `getSync`,
`createSync`, `syncAction(id, action)`, `getSyncWebhook`, `rotateSyncWebhook`; hook
`use-migration-sync.ts` (polls every 5 s while `runningJobId`, else 30 s).

Element -> component map (no new primitives; no hint copy):
| Element | Component |
|---|---|
| card shell | `Card`, `CardHeader`, `CardContent` (as `migration-report-card.tsx`) |
| status | `StatusBadge` with a `sync-status.ts` registry (Active / Paused / Stopping / Stopped) |
| status line + counts | plain text, times via `useDatetime()` |
| Start / Sync now / Pause / Resume | `Button` (secondary for Pause) |
| Stop syncing (cutover) | `Button` destructive + `ConfirmActionDialog` |
| webhook URL | read-only `Input` + copy `Button` (manage only) |
| failures | `MigrationFailuresTable` |
At 375 px buttons wrap (`flex flex-wrap gap-2`), URL input full width.

## 6. Tests (tester writes them red first)

`tests/test_omnichannel_migration_sync.py` (fake respond.io via the same `httpx.MockTransport`
fixtures the migration suites use): lifecycle + tenant scope (01-06), sweep enqueue + claim
(10, 18), poll / hints / full sweep (11-13), dedupe incl. native wamid (14), seams untouched
(15), skipped-channel re-link (16), mapping follows newest run (17), isolation (19), source-wins
(20) + migration still fill-if-empty (21), webhook (30-33), token pause + email, 429, pause /
resume / run-now / stop + CSW (40-44). Frontend vitest for the card states (50-53).

## 7. Backlog

- respond.io webhook signature verification once the scheme is confirmed on a real account.
- Message edits/deletes on respond.io are not propagated.
- Contact merges on respond.io are not reconciled (plan 33 backlog row).
