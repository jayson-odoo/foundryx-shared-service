# Plan 56: partner inbox D5 (Meta rate-limit retry, Meta pricing, contact erase)

Lane SS-FUJI-READINESS. Owner ruling D5 (a), 1 Nov (crew ask a67164769): add forward + store Meta pricing, contact erase for PDPA, retry Meta 429 to this lane. Per-key rate limit, webhook replay, retention setting, file library and the usage API (BL-106) go to the backlog.

Code checked at origin/main c7fa99dc (gap 7, PR 181, merged). UAC: `56-partner-d5-pricing-erase-retry-acceptance-criteria.md`.

Three PRs, in this order: A (S), B (M), C (L). B and C start only after crew relays the answers to the behaviour card. A starts now on the recommendations below unless crew says otherwise.

## A. Meta rate-limit retry on WhatsApp sends (size S)

### Today

- `adapters/meta_graph.py:63` `_RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}` and `is_rate_limited_error` (`:66-77`, HTTP 429 or one of those codes). Only Messenger uses it (`adapters/messenger.py:179,374,493`; Instagram subclasses Messenger, `adapters/instagram.py:43`).
- WhatsApp `send` and `upload_media` mark an error retryable only on HTTP >= 500 or a network failure (`adapters/whatsapp_cloud.py:310,324,461,474`). A WhatsApp 429 or Meta code 130429, 131056 or 80007 ends FAILED on the first attempt.
- Every send goes through `MessageService._enqueue_and_finalize` (`services/message_service.py:359-393`) into the Celery task `omnichannel_send_message` (`worker.py:66-73`: `autoretry_for=(Exception,)`, `retry_backoff=5`, `retry_backoff_max=600`, jitter, `max_retries=3`). A retryable error goes through `_requeue_transient` (`services/send_runner.py:188-201`); the QUEUED to SENDING claim (`:354-383`) stops a double send; the last attempt runs `fail_unfinished` (`worker.py:94-95`, `send_runner.py:207-235`). Public API, staff, workflow, template, broadcast sends all use this path.
- Sync in-request Meta calls with no retry: reactions (`services/message_service.py:910-918`), read receipts (`services/public_gateway_service.py:843`), template sample upload (`services/template_management_service.py:287`).

### Change

1. WhatsApp `send` and `upload_media` classify a rate limit as retryable: HTTP 429, or Meta `error.code` in the extended set {4, 17, 32, 613, 80007, 130429, 131056}. One named constant in `meta_graph.py`; Messenger keeps its behaviour.
2. 131048 (spam rate limit) stays permanent: retrying a number Meta flags for spam lowers its quality further. (Card Q-A1.)
3. A rate-limited send gets its own retry schedule: up to 4 retries at 15, 60, 180, 600 s (plus up to 20% jitter), about 14 min in all. A `Retry-After` header, when Meta sends one, raises the next delay up to 600 s. Other transient errors keep today's schedule. (Card Q-A2.)
4. When the budget runs out the row ends FAILED with Meta's code kept, and the consumer `message.status` FAILED webhook goes out as today (`send_runner.py:69-107`). Retries in progress send no webhook (as today).
5. Sync key routes (read receipt, reaction) answer HTTP 429 with code `meta_rate_limited` and a `Retry-After` header when Meta rate-limits them, instead of today's generic refusal. No in-request retry. (Card Q-A3.)
6. Guide: `documentation/omnichannel/consumer-integration-guide.md` errors section and changelog row.

### Not in A

Per-workspace outbound concurrency (BL-SS-338 is about workflow `http.request`, not Meta sends), a send queue per number, eager-mode local retry.

## B. Meta pricing per message (size M)

### Today

- `adapters/whatsapp_cloud.py:949-958` keeps only `id`, `status` and `errors[0]` from each `statuses[]` entry; `pricing`, `conversation`, `timestamp` are dropped. No `.py` file under `modules/omnichannel` reads `pricing`.
- Raw webhook payloads are never stored (`routers/webhooks.py:55-70` queues them; `services/inbound_service.py:74`).
- `_handle_status` / `_apply_receipt` (`services/inbound_service.py:642,709`) overwrite `delivery_status`, `error_code`, `error_message`, forward only (`_STATUS_RANK`, `:65`).
- `ConversationMessage.metadata_json` (`models.py:560`) is free-form; helper to add one key at `repositories/contact_repository.py:310-316`.
- Consumer `message.status` payload built at `services/inbound_service.py:767-781` and `services/send_runner.py:69-103`. `MessageItem` at `schemas.py:643-684`, built by `services/conversation_service.py:314`. Rio shape `schemas.py:1715-1730`, mapper `services/public_gateway_service.py:439-532`.
- GET /templates already returns `category` (`schemas.py:1477-1483`, `?category=` filter `routers/api_v1.py:196`, guide `:326-343`). Partner ask 3 is already met.
- Dev data: 0 rows contain "pricing" in `foundryx_service` and `foundryx_service_ssfujireadiness` (every text and json column searched).

### Change (recommendations, pending card Q-B1..Q-B4)

1. Parse `statuses[].pricing` into a normalised object `{billable: bool, pricingModel: str, category: str, type: str | null}`. Strings are Meta input: lower-case, capped at 40 chars, `[a-z0-9_]` only, else dropped. Unknown keys dropped.
2. Store on the message as `metadata_json["pricing"]` (fresh dict, reassigned). The latest non-null object wins. Stored even when the status itself does not move forward (a late `sent` after `delivered`).
3. Wire: `pricing` (object or null) on the `message.status` webhook data and on `MessageItem` (default shape). Rio shape unchanged.
4. No backfill is possible: Meta's data was never stored. Older messages answer `pricing: null`; the guide says so.
5. Usage per number per month and payment method status stay in BL-106 (D5 ruling). FujiAire can sum per-message pricing itself.

## C. Contact erase for PDPA (size L)

### Today

- No route deletes a contact, a conversation or a message (`routers/contacts.py:63-204`, `routers/conversations.py:91-860`; api_v1 DELETE only for webhooks `:633` and workflows `:849`). BL-SS-073 (`documentation/backlogs/backlog.md:216`) parks contact delete / merge / block; plan 26 D-A2-15.
- A thread is the contact row itself (`models.py:196-265`). No foreign key to `contacts.id` cascades (`models.py`, `alembic/versions/*`; comment `services/channel_service.py:181-186`). Children: `contact_channel_identities` `:273`, `contact_tag_links` `:364`, `conversation_events` `:504`, `conversation_messages` `:532` (and `message_reactions` `:601-603` on messages), `workflow_waits` `:1030`, ideation `ideas.submitter_contact_id` (`modules/ideation/models.py:169-171`).
- Soft references: `broadcast_recipients` `:733-734`, `broadcasts.audience_contact_ids_json` `:671`, `workflow_contact_fires` `:960`, `migration_refs` `:992`, `webhook_deliveries.payload_json` `:844` (never pruned; deleted only with the endpoint, `services/webhook_service.py:562-565`).
- Core copies: `workflow_runs.trigger_payload_json` (`app/models/workflow.py:141`) and `integration_activity.request_summary_json` (`app/models/integration_activity.py:93`), both kept 30 days (`app/config.py:203,344`).
- Stored files: inbound `services/inbound_service.py:566-592`, outbound `services/message_service.py:503,626,771`, migration `services/migration_media.py:246-247`. The voice transcode replaces `media_key` with the ogg (`services/send_runner.py:459-463`); the original upload is not reachable from the row. `TenantStorage.delete` (`app/services/storage.py:495-503`) skips a key whose connection is gone.
- Inbound from the same number recreates a contact by phone (`services/inbound_service.py:466-489`).
- Dev examples (`foundryx_service`, read-only counts): contact `cnt-003` 14 messages, 4 with media, 1 event, 1 identity; `d7fa2243` 12 messages, named in 8 workflow run payloads; `84e6050c` 7 messages, 9 run payloads. 37 contacts in all.

### Change (recommendations, pending card Q-C1..Q-C5)

1. Hard erase, one transaction for rows, fixed order: cancel parked waits (as `bootstrap.py:886`), reactions, messages, events, identities, tag links, waits, workflow contact fires, broadcast recipient rows, migration refs, ideation submitter set NULL, then the contact.
2. Stored files deleted after commit as a `background_jobs` job that retries; every key collected before the delete, including the voice original once the transcode keeps it findable.
3. `webhook_deliveries` rows for the contact keep id and status; `payload_json` becomes ids only.
4. API key: `DELETE /api/v1/omnichannel/contacts/{identifier}` in the key's own workspace (gap 7 precedent: every key has full power in its own workspace). Staff: typed-confirm action under a new permission `contacts.erase` with an Admin grant sweep, UI after a mock.
5. New webhook event `contact.erased` (ids only, opt-in per endpoint).
6. The guide states what SS cannot erase: the chat on the customer's phone, media Meta still holds, copies FujiAire keeps, and exports already downloaded.

## Order and gates

A: tester red, coder, kill, reviewer. B: card answers, UAC final, tester red, coder, kill, reviewer + security-reviewer (public webhook payload), guide-writer. C: card answers, mock for the staff action, UAC final, tester red, coder, kill, reviewer + security-reviewer, browser 1280/375, guide-writer, user guide under `documentation/user-guides/`.

## Definition of Done

Per PRINCIPLES.md and the crew contract: red-first commit, kill proof, reviewer READY (plus security-reviewer for B and C), guide and changelog in the same PR, backfill or a stated reason none applies, grant sweep for any new permission, browser pass at 375 and 1280 for any UI.
