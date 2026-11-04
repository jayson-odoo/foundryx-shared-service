# Plan 56 acceptance criteria (partner inbox D5)

Plan: `56-partner-d5-pricing-erase-retry.md`. Sections A and B are final (crew rulings A1a A2a A3a B1a B2a B3a B4a, 4 Nov). Section C is a draft until the owner answers card C1..C5.

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

- AC-56-20: A Meta status webhook carrying `pricing` stores `{billable, pricingModel, category, type}` on the message.
- AC-56-21: The consumer `message.status` webhook carries `pricing` (object or null).
- AC-56-22: `MessageItem` carries `pricing` on GET messages (default shape); the rio shape is unchanged.
- AC-56-23: A status that does not move the message forward still records its pricing.
- AC-56-24: Out-of-range pricing strings (wrong type, too long, characters outside `[a-z0-9_]`) are dropped, never stored.
- AC-56-25: Messages without Meta pricing answer `pricing: null`; tenant and workspace scoping as every other message read.

## C. Contact erase (draft)

- AC-56-40: `DELETE /api/v1/omnichannel/contacts/{identifier}` erases the contact and every row in plan section C.1 in one transaction, in the key's own workspace only; a contact of another workspace or tenant answers 404.
- AC-56-41: Stored files of the erased messages are deleted after commit by a retrying background job.
- AC-56-42: Webhook delivery rows for the contact keep id and status; their payload becomes ids only.
- AC-56-43: Subscribed endpoints receive one `contact.erased` event with ids only.
- AC-56-44: Staff erase needs `contacts.erase`; existing tenants' Admin role gets it by a grant sweep.
