# Plan 56 acceptance criteria (partner inbox D5)

Plan: `56-partner-d5-pricing-erase-retry.md`. Sections A and B are final (crew rulings A1a A2a A3a B1a B2a B3a B4a, 4 Nov). Section C is final (owner rulings C1a C2a C3a C4b C5a, 4 Nov).

## A. Meta rate-limit retry on WhatsApp sends

- AC-56-01: A WhatsApp text send that Meta answers with HTTP 429 is retried, not failed: the row goes back to QUEUED and the send task is re-queued.
- AC-56-02: The same holds for a Meta error body with code 130429, 131056, 80007, 4, 17, 32 or 613, whatever the HTTP status.
- AC-56-03: A WhatsApp media upload that Meta rate-limits (same rule as AC-56-01 and AC-56-02) is retried the same way.
- AC-56-04: Meta code 131048 ends the send FAILED on the first attempt with code `131048` kept, and no retry.
- AC-56-05: A rate-limited send is retried at most 4 times, with delays of 15, 60, 180 and 600 s each plus at most 20% jitter. Other transient errors (HTTP 5xx, network) keep today's schedule and count.
- AC-56-06: When Meta sends a `Retry-After` header larger than the next scheduled delay, the next delay is that value, capped at 600 s.
- AC-56-07: After the last rate-limited attempt fails, the row ends FAILED with Meta's code, and exactly one consumer `message.status` webhook with `deliveryStatus` FAILED goes out. No webhook goes out while retries are still pending.
- AC-56-08: A retry never sends the message twice: a second worker that picks up the same message after it left QUEUED does not call Meta.
- AC-56-09: A permanent Meta error (for example code 100 or 131026) still fails on the first attempt, as today.
- AC-56-10: Messenger and Instagram keep today's rate-limit behaviour and schedule.
- AC-56-11: `POST /api/v1/omnichannel/contacts/{id}/read` and the API key reaction send answer HTTP 429 with code `meta_rate_limited` and a `Retry-After` header when Meta rate-limits the call, and the per-key request limit's own 429 code stays distinct.
- AC-56-12: The consumer guide lists the retried codes, the schedule, the FAILED outcome and `meta_rate_limited`, with a changelog row.

## B. Meta pricing per message

Code today: parse `adapters/whatsapp_cloud.py:949-958`; apply `services/inbound_service.py:642-800` (`_apply_receipt` returns early at the rank guard, before the commit); send-side events `services/send_runner.py:69-107`; `MessageItem` `schemas.py:643-684` built at `services/conversation_service.py:314`; rio `schemas.py:1715-1730` unchanged.

- AC-56-20: A WhatsApp status webhook entry with `pricing` `{billable, pricing_model, category, type}` stores `{billable, pricingModel, category, type}` under `metadata_json["pricing"]` of the message it targets. `billable` is a bool; the other three are strings or null. Other metadata keys (`reply_to`, `broadcast`, `message_tag`) are kept.
- AC-56-21: The consumer `message.status` webhook for that receipt carries `data.pricing` with the same object. Every `message.status` webhook, including the send-side `SENT` and `FAILED` events from `send_runner.py`, carries the message's stored pricing at that moment (null when none).
- AC-56-22: GET `/api/v1/omnichannel/contacts/{id}/messages` and GET of one message return `pricing` on every `MessageItem` (object or null). The `?format=rio` shape has no `pricing` key.
- AC-56-23: A receipt that does not move the status forward (a `sent` after `delivered`) still stores its pricing and commits it, sends no `message.status` webhook, and the next GET shows it.
- AC-56-24: The latest non-null pricing wins; a later status with no pricing never clears a stored one.
- AC-56-25: Meta strings are untrusted: each of `pricing_model`, `category`, `type` is lower-cased and kept only if it is a string of 1 to 40 chars in `[a-z0-9_]`, else that field is null. `billable` that is not a JSON bool is null. A `pricing` value that is not an object stores nothing. Unknown keys are dropped. None of this ever fails the webhook.
- AC-56-26: An inbound message, and messages older than this change, answer `pricing: null`. No backfill (Meta's data was never stored).
- AC-56-27: Tenant and workspace scoping are unchanged: a status webhook on channel X never writes pricing on a message of another tenant (same `external_message_id` in a foreign tenant).
- AC-56-28: Guide: `message.status` payload section (`consumer-integration-guide.md:847-854`), MessageItem section 9.1 (`:1029-1060`), field map 9.3 (`:1193-1199`, rio has none), a note that GET /templates already returns `category`, and a changelog row.

## C. Contact erase for PDPA

Owner rulings C1a C2a C3a C4b C5a (4 Nov). Code pointers in plan section C.

### API key route

- AC-56-40: `DELETE /api/v1/omnichannel/contacts/{identifier}` (`id:<contactId>`, `phone:<number>` or a bare id, the resolver at `services/public_gateway_service.py:338`) erases the contact of the key's own workspace and answers `200` with `{contactId, erasedAt, messages, files}` (counts of what was erased). A contact of another workspace or tenant, an unknown one, and a second call for the same contact answer `404 contact_not_found`. Every API key can call it (gap 7 precedent, no per-key scope).
- AC-56-41: In one transaction, after cancelling the contact's parked workflow waits (their runs end cancelled, as `bootstrap.py:886` does), the erase deletes: message reactions on the contact's messages, the messages (internal notes included), conversation events, channel identities, tag links, workflow waits, workflow contact fires, broadcast recipient rows, and the contact. `broadcasts.audience_contact_ids_json` drops the id (fresh list). Ideation `ideas.submitter_contact_id` is set to NULL. Nothing else of other contacts changes. A failure anywhere rolls the whole erase back and the contact stays as it was.
- AC-56-42: After commit, every stored file of the erased messages (`media_key`, a legacy `media_url` that points at local storage, and the original upload of a transcoded voice note) is deleted by a retrying Celery task. A file that is already gone counts as deleted. A file delete that keeps failing never undoes the erase, and the log line carries the storage key's connection id only, never the file name or contact data.
- AC-56-43: The voice transcode (`services/send_runner.py:459-463`) deletes the original upload once the converted file is stored, so no unreachable original remains for new sends.
- AC-56-44: `webhook_deliveries` rows whose payload names the contact keep their id, event type, status and attempt fields; `payload_json` becomes ids only (`id`, `type`, `workspaceId`, `channelId`, `occurredAt`, `data.contactId`, `data.messageId` when present).
- AC-56-45: Respond.io: the contact's migration ref of type `contact` is kept and re-keyed to `entity_type = "contact_erased"`, `local_id = "erased"`; its other refs (identities, messages, events) are deleted. A later one-off import or continuous sync pass that meets that respond.io contact id writes nothing for it: no contact, identity, message, media or event (`MigrationWriter._find_existing`, main `services/migration_writer.py:504-552`).
- AC-56-46: After the erase, an inbound message from the same number, or `POST /messages` to `phone:<number>`, creates a new contact with a new id and no link to the erased one.
- AC-56-47: New consumer webhook event `contact.erased`, opt-in per endpoint like every event type: `data` is `{contactId, erasedAt}` and nothing else; sent once per erase to the workspace's subscribed endpoints (`enqueue_workspace_event`), under the existing gateway-key and endpoint-status rules.
- AC-56-48: Staff inboxes get a realtime `contact.erased` event; an open thread or list row for that contact closes or disappears without a reload.
- AC-56-49: A queued or retrying send of an erased message ends quietly: the send task finds no row, calls nothing at Meta and raises nothing.

### Staff

- AC-56-50: New permission `contacts.erase` (module CSV row). Existing tenants' Admin role gets it by a one-shot sweep when the key is first created (`PermissionRepository.sync()` created-keys pattern, `modules/connector/bootstrap.py:37-81`); no other role gets it. The key does not collide with a core key.
- AC-56-51: Staff route `DELETE /api/omnichannel/contacts/{id}` needs `contacts.erase` plus access to the contact's workspace; it runs the same erase as AC-56-41 to AC-56-49 and answers the same body. A contact of another tenant or of a workspace the user cannot see answers 404.
- AC-56-52: "Erase contact" appears in the contacts list row menu (one row at a time, never bulk) and the contact detail menu, only for users with `contacts.erase`. It opens the typed-confirm dialog (`ConfirmActionDialog`, the tenant purge pattern) showing the contact's name and the counts that will go (messages, files); the confirm button stays disabled until the user types `ERASE`. After success the detail view returns to the list and a toast says the contact was erased.
- AC-56-53: The menu, dialog and toast work at 375 px and 1280 px (browser pass on the crew test copy).

### Contract and docs

- AC-56-54: Consumer guide: the route, the response, `404` cases, the `contact.erased` event, the re-contact rule, the respond.io rule, and what SS cannot erase (the chat on the customer's phone, media Meta still holds, copies the consumer keeps, exports already downloaded, and core logs, which are purged after 30 days); changelog row. `documentation/engineering/omnichannel-service.md` gets the erase order.
