# SS-MIGRATION-SYNC: keep pulling respond.io into the Shared Service until cutover

Lane SS-MIGRATION-SYNC. Stage: Plan (behaviour card). No code until the owner answers the
questions at the end. Builds on SS-CHANNEL-SKIP (PR #179).

Owner's ask (4 Nov): "for some interval or when there is new messages, the messages are pumped
into shared service also".

## What exists today (read from the code)

- A migration is ONE `background_jobs` row of type `omnichannel.respondio_migration`
  (`modules/omnichannel/services/migration_service.py:87`). Phases: contacts -> identities ->
  messages -> media -> events -> quick replies (`run_migration_job`, `migration_service.py:2089`).
  It runs once and ends DONE.
- Duplicates are already prevented by `migration_refs` (source id -> local id per tenant +
  workspace). A message whose respond.io `messageId` already has a ref is skipped
  (`migration_service.py:1850`). A second run of the same mapping is safe today, just slow:
  it re-walks every contact and every contact's full history.
- respond.io client: `POST /contact/list`, `GET /contact/{id}/channels`,
  `GET /contact/{id}/message/list`, header-driven rate limiting (4 requests/s default,
  honours `retry-after`, halves its own rate after 4 consecutive 429s)
  (`respondio/client.py:32-46`).
- Migrated rows are "read-only history" (plan 33 D-A6-8): no live inbox push, no workflow
  trigger, no consumer webhook, no 24h-window (CSW) recompute, `external_message_id` NULL
  (`migration_writer.py:815`).
- Contact fields use fill-if-empty: a value already in SS is never overwritten
  (`migration_writer.py:563`). Lifecycle is never moved once set.
- The beat host already runs 60 s sweeps that enqueue jobs (e.g. `autocount-etl-sweep`,
  `app/workflow_engine/worker.py:96`). Same pattern fits here.

## How it would work (proposal)

**One "sync" per workspace, switched on from the finished migration.** On a migration's
detail page, after a successful real run: a toggle "Keep syncing until cutover" + a status
line. No new screen. ON creates a sync record carrying the same connection + mappings
(channel / user / team / lifecycle maps) as that migration.

**Two triggers, one code path:**

1. **Interval poll (safety net, always on while syncing).** Every N minutes (default 15) a
   sweep enqueues one sync job for the workspace. The job:
   - walks `POST /contact/list` (100 per page) -> new contacts are created, as today;
   - for contacts that may have new messages, fetches their message list and writes only
     messages with no ref yet (the existing `_process_contact_messages`, unchanged rules);
   - runs media + derived events for the NEW message refs only (not the whole history);
   - stores a high-water mark (last sync time, last seen contact cursor) on the sync record.
2. **respond.io webhook (fast path, optional).** respond.io can POST to a URL on new
   incoming/outgoing messages and contact changes. We give the owner a per-workspace URL
   with a secret in it. We use the webhook ONLY as a hint "contact X changed": we never
   write the payload; we enqueue the same per-contact sync, which re-reads that contact
   from the respond.io API with our own token. So a forged webhook can at worst make us
   re-read a contact from respond.io (rate limited, tenant scoped), never inject a message.

**What is synced:** new contacts; messages both directions (incoming, agent, workflow,
broadcast); attachments (media phase, new messages only); conversation open/closed events
(derived, as today); assignee for new contacts. Contact field changes: see Q3.

**Duplicates:** `migration_refs` by respond.io `messageId` (exists). New: also store the
WhatsApp message id (`channelMessageId`) on synced rows, and skip a respond.io message whose
WhatsApp id already exists natively in SS (covers the cutover overlap, see edge cases).

**Channel mapping, incl. skipped channels (SS-CHANNEL-SKIP):** each tick re-reads the
mapping. A message from a skipped channel is still imported (channel empty) and we record
its respond.io channel id on the row. When the owner connects the channel and maps it, the
next tick backfills channel identities (as #179 does on a re-run) AND sets the channel on
those earlier synced messages.

**Live inbox / workflows:** synced messages appear in the SS inbox on the next refresh, but
DO NOT fire workflows, consumer webhooks or AI replies (respond.io already answered the
customer; firing here would double-reply). See Q4 for live push.

**Errors and rate limits:** per-contact errors go to the sync's failure list and the next
tick retries them (refs make it idempotent). 429 -> the existing backoff; a tick that runs
past the next interval is not started twice (one running sync job per workspace, the existing
`migration_in_progress` rule). 401/403 (token expired or revoked) -> the sync pauses itself
with "respond.io rejected the access token - update it on the connection", no retries until
the token is replaced, owner alerted by email.

**What he sees:** on the migration detail page: "Syncing every 15 min - last sync 10:42
(2 min ago): +3 contacts, +41 messages, 0 errors", next run time, a "Sync now" button, and the
error list. Each tick is also a job in the Jobs drawer.

**How it stops:** a "Stop syncing (cutover)" button. It runs one final sync, then stops for
good and recomputes the 24h reply window (CSW) from each contact's last incoming message so
agents can reply free-form right after cutover (today migrated history leaves the window
closed). It also stops itself: after 3 days of token errors, or if the connection or
workspace is deleted. Auto-stop by date: see Q5.

## Examples (synthetic, shaped like respond.io payloads; no dev export is reachable from this sandbox)

| # | On respond.io | What the next sync does in SS |
|---|---|---|
| 1 | Existing contact C-1 (migrated last week) sends "Is the part in stock?" at 10:31 | Webhook hint at 10:31 -> per-contact sync -> 1 incoming message added to C-1's thread, `last_message_at` 10:31. No workflow fires. |
| 2 | Agent replies to C-1 at 10:35 from respond.io | Agent message added, sender = the mapped SS user (matched by email), else "agent (respond.io)". |
| 3 | Brand-new contact C-2 messages with a photo at 11:02 | Contact C-2 created, identity on the mapped WhatsApp channel, message + image fetched into storage. |
| 4 | C-3 writes on a channel the owner skipped (no SS channel yet) | Contact + message imported, channel empty. After he connects + maps the channel, next tick: identity added, message gets its channel. |
| 5 | Webhook delivery fails (respond.io outage) | Nothing lost: the 15-min poll picks C-1/C-2/C-3 up from the API. |

## Edge cases

- **Message edited/deleted on respond.io:** v1 does not propagate (WhatsApp messages cannot be
  edited by the customer; a deleted note stays in SS). Logged as a known gap.
- **Contact merged on respond.io:** the surviving id is a new or existing ref; the merged-away id
  stops appearing. SS keeps both contacts (same as the one-off migration, plan 33 backlog row
  "Contact-merge history"). Messages already synced are not moved.
- **Same message arrives natively AND via sync** (after the number moves to SS, before he
  stops syncing): skipped by the WhatsApp-id check. The other order (sync wrote first, then
  Meta delivers natively) needs the native inbound path to also check synced rows' WhatsApp
  id - included in scope.
- **Two workspaces:** one sync per workspace; each has its own record, mapping and status. Two
  workspaces cannot both sync from the same respond.io space into the same SS workspace.
- **Token expiry:** see errors above (pause, alert, resume when the token is updated).
- **Very large contact base:** the poll cannot fetch every contact's messages every 15 min at
  4 requests/s (10,000 contacts = about 40 min per pass). Hence Q2.

## Security notes (for the security review later)

- Token: read from the existing Fernet-encrypted connection at each tick, never logged, never
  on the wire to the browser.
- Webhook: per-workspace random secret in the URL path + constant-time compare; plus
  respond.io's signature header if their webhook offers one (to verify against the dev
  respond.io account). Payload only used as a hint; per-IP throttle; uniform 404 on a wrong
  secret.
- SSRF: the only outbound hosts are the connection's respond.io base URL (already
  operator-set) and media URLs, which go through the existing migration media fetch.

## Questions for the owner (max 5)

1. **Trigger:** (a) interval poll only, (b) webhook + poll safety net, (c) webhook only.
   Recommendation: **(b)** - near-real-time when the webhook works, nothing lost when it does
   not. (a) is simpler if he does not want to touch respond.io settings.
2. **Poll scope with many contacts:** (a) every tick checks only contacts the webhook flagged +
   new contacts, and a full message sweep runs every 6 h; (b) every tick checks every contact's
   messages (only OK under a few thousand contacts); (c) every tick checks contacts active in
   the last 48 h if respond.io's contact filter supports it (to verify on dev).
   Recommendation: **(a)**, with 15-min default interval. Roughly how many contacts does MyFuji
   have?
3. **Contact field changes on respond.io after the first migration:** (a) keep today's
   fill-if-empty (SS edits always win; respond.io changes to already-filled fields are
   ignored); (b) respond.io wins until cutover (overwrites name/email/custom fields/tags/
   lifecycle/assignee in SS). Recommendation: **(b)** - before cutover nobody should be editing
   in SS, so respond.io is the truth; (a) if his team already works in SS in parallel.
4. **Should synced messages pop up live in open SS inboxes (live push + unread badge)?**
   (a) yes, live push + unread, never workflows/webhooks/AI; (b) no, they appear on refresh and
   are marked read. Recommendation: **(b)** while respond.io is still the working inbox (no
   unread noise); switch to (a) only if his team starts answering from SS before cutover.
5. **Stopping:** (a) manual "Stop syncing (cutover)" only; (b) manual + auto-stop on a date he
   sets; (c) auto-stop when the first native WhatsApp message lands in that workspace.
   Recommendation: **(a) + (c)** - the first native message means the number has moved, so
   respond.io is no longer the source; manual stop stays for everything else.
