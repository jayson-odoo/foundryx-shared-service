# Plan 56 acceptance criteria (partner inbox D5)

Plan: `56-partner-d5-pricing-erase-retry.md`. Sections A and B are final (crew rulings A1a A2a A3a B1a B2a B3a B4a, 4 Nov). Section C is a draft: the owner ruled C1a C2a C3a C4b C5a (4 Nov); it is completed when C starts, after A and B.

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

## C. Contact erase (draft)

- AC-56-40: `DELETE /api/v1/omnichannel/contacts/{identifier}` erases the contact and every row in plan section C.1 in one transaction, in the key's own workspace only; a contact of another workspace or tenant answers 404.
- AC-56-41: Stored files of the erased messages are deleted after commit by a retrying background job.
- AC-56-42: Webhook delivery rows for the contact keep id and status; their payload becomes ids only.
- AC-56-43: Subscribed endpoints receive one `contact.erased` event with ids only.
- AC-56-44: Staff erase needs `contacts.erase`; existing tenants' Admin role gets it by a grant sweep.
