# 52 - respond.io continuous sync until cutover - acceptance criteria

Lane SS-MIGRATION-SYNC. Behaviour card: `ss-migration-sync-card.md`. Owner answers (4 Nov):
Q1 webhook + 15 min poll safety net; Q2 each tick = webhook-flagged + new contacts, full sweep
every 6 h; Q3 respond.io wins until cutover; Q4 synced messages appear on refresh, marked read;
Q5 manual Stop only. Plan: `52-migration-continuous-sync.md`.

Tags: `[BE]` backend, `[FE]` frontend, `[T]` automated test, `[E2E]` recorded agent-browser run.

## Slice 1 - the sync record and its lifecycle

- AC-SYNC-01 [BE][T] Given a workspace whose latest finished migration is a real API-mode run
  (status DONE), When an operator with `omnichannel_migration.manage` POSTs
  `/omnichannel/migration/syncs {workspaceId}`, Then a sync is created with status `active`,
  interval 15 min, full sweep 6 h, its mapping taken from that run, and a webhook secret.
- AC-SYNC-02 [BE][T] Given no finished real API-mode run for the workspace (none, only dry runs,
  only CSV runs, or the run failed), When the sync is created, Then 409
  `{reason: "no_finished_migration"}` and nothing is stored.
- AC-SYNC-03 [BE][T] Given an `active` or `paused` sync already exists for the workspace, When
  another create arrives, Then 409 `{reason: "sync_exists"}`. Given a `stopped` sync, create
  re-activates that same row (same id, new secret, totals kept).
- AC-SYNC-04 [BE][T] A sync, its endpoints and its jobs are tenant-scoped: another tenant's sync
  id reads as 404 on every route; a `read`-only user can GET but every write is 403.
- AC-SYNC-05 [BE][T] GET `/omnichannel/migration/syncs?workspaceId=` returns the workspace's sync
  or `null`; the item never contains the webhook secret or URL.
  GET `/syncs/{id}/webhook` (manage only) returns the full webhook URL.
  POST `/syncs/{id}/webhook/rotate` replaces the secret; the old URL then 404s.
- AC-SYNC-06 [BE][T] The sync item reports `sourceContactCount` and `estimatedFullSweepMinutes`:
  before the first tick, from the latest dry run's fetched contacts; after a tick, from that
  tick's contact walk. Estimate = ceil(contacts x 3 calls / requestsPerSecond / 60).

## Slice 2 - the tick (poll, hints, full sweep)

- AC-SYNC-10 [BE][T] Given an `active` sync whose `nextSyncAt` has passed, When the 60 s beat
  sweep runs, Then exactly one `omnichannel.respondio_sync` job is enqueued for it; a second
  sweep while that job is pending/running enqueues nothing.
- AC-SYNC-11 [BE][T] A poll tick walks the respond.io contact list once: a contact with no ref is
  created (contact + channel identities + full message history + media + events); an existing
  contact gets the Q3 update (AC-SYNC-20); no existing contact's messages are fetched unless it
  is flagged or the full sweep is due.
- AC-SYNC-12 [BE][T] Given webhook hints for contacts A (migrated) and B (not yet in SS), When the
  next sweep runs (no need to wait for `nextSyncAt`), Then a hints tick fetches A's new messages
  and creates B (via `GET /contact/id:B`) with its history; the hints are consumed; contacts
  without hints are not touched.
- AC-SYNC-13 [BE][T] Given `lastFullSweepAt` older than 6 h (or null), When a poll tick runs, Then
  every migrated contact's identities and messages are re-checked; `lastFullSweepAt` is set when
  the sweep completes, not when it starts.
- AC-SYNC-14 [BE][T] Dedupe: running the same tick twice writes nothing the second time (no new
  messages, contacts, identities, events, media); a respond.io message whose WhatsApp id
  (`channelMessageId`) already exists natively in the tenant (`external_message_id`) is skipped
  and counted under `skip`.
- AC-SYNC-15 [BE][T] Synced messages follow plan 33 D-A6-8: no realtime publish, no workflow /
  entity event, no consumer webhook, no CSW recompute; the contact's `agent_last_read_at` equals
  its `last_message_at` after the tick (Q4: appears on refresh, read).
- AC-SYNC-16 [BE][T] Skipped channel: a synced message from a source channel mapped to nothing is
  imported with no channel. After a newer DONE re-run maps that channel, the next tick that
  touches the contact gives the message the channel (the #179 re-link) and adds the identity.
- AC-SYNC-17 [BE][T] Mapping follows the newest DONE real API run for the workspace at each tick
  (not frozen at create).
- AC-SYNC-18 [BE][T] Mutual exclusion: a tick does not start while a migration job for the
  workspace is pending/running (it is re-tried on the next sweep); creating a migration job while
  a sync job is pending/running returns 409 `migration_in_progress`.
- AC-SYNC-19 [BE][T] Per-contact isolation: an error on one contact (vendor 404/500, malformed
  row) is recorded in the tick's failures and the next contact continues; the tick still
  finishes and `lastSyncAt` advances.

## Slice 3 - respond.io wins (Q3)

- AC-SYNC-20 [BE][T] On an existing synced contact, respond.io's non-empty values overwrite SS:
  first/last name, email, language, country code, custom field values, lifecycle (when mapped),
  assignee (when mapped), conversation open/closed. Tags become exactly respond.io's set
  (mapped/created as in the migration). A value respond.io leaves empty never clears SS. No
  change = no write (the contact's `updated_at` does not move). No entity event is emitted.
- AC-SYNC-21 [BE][T] The one-off migration keeps fill-if-empty (plan 33 D-A6-11) - the existing
  migration suites stay green.

## Slice 4 - webhook (Q1)

- AC-SYNC-30 [BE][T] `POST /omnichannel/migration-hooks/{syncId}/{secret}` with a body carrying a
  respond.io contact id (`contact.id`, `contactId` or `data.contact.id`; digits only) stores one
  hint and answers 200 within the request (no respond.io call made in the request).
- AC-SYNC-31 [BE][T] Wrong secret, unknown sync id, stopped sync, or omnichannel not active for
  the tenant: uniform 404, nothing stored. Secret compared in constant time.
- AC-SYNC-32 [BE][T] A body with no usable contact id, invalid JSON, or over 64 KB: 200/204/413
  as specified in the plan, nothing stored, never 500. Hints are deduped per contact; pending
  hints per sync are capped (5000) - over the cap the hint is dropped and the next full sweep
  covers it.
- AC-SYNC-33 [BE][T] The webhook payload is never written: only the contact id is kept; the
  message itself is re-read from the respond.io API with the stored token.

## Slice 5 - errors, pause, stop

- AC-SYNC-40 [BE][T] respond.io 401/403 during a tick: the sync goes `paused` with
  `pausedReason: "token_rejected"`, the tick ends, no retry until Resume; one email to the sync
  creator (outbox). Resume (POST `/syncs/{id}/resume`) sets `active` and makes it due now.
- AC-SYNC-41 [BE][T] 429: the existing client backoff applies; a tick that still fails on rate
  limits ends with `lastError` set and the sync stays `active` (next tick retries).
- AC-SYNC-42 [BE][T] Pause / Resume / Sync now: pause stops new ticks (a running tick stops at its
  next checkpoint); Sync now on an `active` sync makes it due now (409 when a tick is running).
- AC-SYNC-43 [BE][T] Stop (POST `/syncs/{id}/stop`): status `stopping`, one final tick (poll +
  hints, no full sweep) runs, then for every respond.io-migrated contact of the workspace
  `csw_expires_at` = `last_incoming_message_at + 24 h` when that is in the future (else
  untouched), and the sync ends `stopped`. No automatic stop exists (Q5).
- AC-SYNC-44 [BE][T] The sync never stops itself: deleted connection or workspace pauses it with
  a reason (`connection_missing` / `workspace_missing`), it does not delete it.

## Slice 6 - frontend

- AC-SYNC-50 [FE][T] On a DONE real API migration's detail page, a "Continuous sync" card shows
  "Start syncing" (manage only). Not shown for dry runs, CSV runs or unfinished jobs.
- AC-SYNC-51 [FE][T] Active: status line "Syncing every 15 min. Last sync <time>: +N contacts,
  +M messages, E errors. Next sync <time>." plus "Sync now", "Pause", "Stop syncing (cutover)";
  contact count + full sweep estimate; webhook URL with a copy button (manage only).
- AC-SYNC-52 [FE][T] Paused shows the reason ("respond.io rejected the access token" etc.) and
  "Resume". Stop opens a confirm dialog; after stopping the card reads "Stopped <time>".
- AC-SYNC-53 [FE][T] The last tick's failures list (sample) renders with the existing failure
  table; the card polls while a tick is running.
- AC-SYNC-54 [E2E] Recorded agent-browser run at 1280 px and 375 px: start, status line, sync
  now, pause/resume, stop - no sideways scroll at 375 px.
