# 68a - Google Ads lead form receiver + guided paste path (behaviour card)

Lane META-LEADS-R2-GOOGLE, part 1 (L5-GOOGLE). Crew ruling 18 Nov: order (a), receiver + guided paste path first,
built against Google's documented lead form webhook, simulated; Google sign-in (plan 68) after the S-GOOGLE spike.
ACs: AC-64-40, AC-64-41, AC-64-44 (plan 64 section F) + AC-68a-* below. Needs no Google account: Google only ever
POSTs to us on this path.

Google's contract (cited, not guessed):
- Webhook format and fields: https://developers.google.com/google-ads/webhook/docs/implementation
- Lead form webhook overview: https://developers.google.com/google-ads/webhook/docs/overview
- Where the customer pastes URL + key: https://support.google.com/google-ads/answer/9423234 (lead form asset,
  "Lead delivery option" > webhook integration, "Send test data").

## Rules

R1. Source. A Google source is an `lc_source` with `platform = "google"`, `mode = "guided"`, created by the wizard
(Channel = Google), a staff user (Sources list "Create"), or the gateway (`POST /api/v1/lead-capture/sources/google`).
All three call ONE function `source_service.create_guided_source`. On create it gets:
- `source_key`: 32 random url-safe characters (column already exists, `models.py:93`, unique);
- the Google key: 32 random url-safe characters, stored Fernet in `credentials_encrypted` as `{"googleKey": ...}`;
- status `WAITING_FOR_TEST`; name "Google Ads" (editable later like any source).
No migration: every column is already there.

R2. Inbound URL. `POST /public/lead-capture/in/{sourceKey}` (wizard router, public, no auth header). Accepts
Google's JSON body. Answers:
- right key, routing source -> `200 {}` and the lead is stored once (R4);
- `google_key` missing or wrong, or `sourceKey` unknown -> `403 {"error":{"code":"invalid_key"}}`, same body
  both ways (no source enumeration), nothing stored; key compared with `hmac.compare_digest`;
- source DISCONNECTED -> `410`, nothing stored (Google shows the form's webhook as failing; the customer sees why);
- source NEEDS_RECONNECT does not apply to Google (no token to expire);
- Lead Capture not active for the tenant / tenant suspended -> `403 service_not_enabled`, nothing stored;
- body not JSON, over 64 KB, or no `lead_id` -> `400 invalid_body`.
Every 403 counts on a per-IP throttle (same `ThrottleService` as the gateway bad-key 401s, `gateway_auth.py:62`); over it = `429` with
`Retry-After`. A right key is never throttled (Google's bursts must not lose leads).

R3. Payload -> answers. Each `user_column_data[]` item `{column_id, column_name, string_value}` becomes one answer
`{key: column_id or column_name, label: column_name, value: string_value}`. Attribution keeps what Google sends:
`formId` (form_id), `campaignId` (campaign_id), `adgroupId` (adgroup_id), `creativeId` (creative_id), `gclid`
(gcl_id). `platform_lead_id = lead_id`. `platform_created_at` = `lead_submit_time` when Google sends it, else null.
The raw body is stored Fernet with the `google_key` removed.

R4. Store. The per-source store loop in `leadgen_service.store_lead` (`leadgen_service.py:259-319`: map with the source's own map,
encrypt, insert idempotent on (source, platform lead id), LIVE on first test, "Map fields" notice, queue
`lead.created`) is moved into ONE shared function `store_for_sources(...)` with `platform` as an argument. Meta's
`store_lead` and the Google receiver both call it. No second store path. Meta's suites pass unedited.

R5. Test. `is_test: true` is a test lead: stored and delivered with `isTest: true` (same as a Meta test lead), and
the first one flips WAITING_FOR_TEST -> LIVE. A real lead before any test lead is stored and delivered too and also
flips to LIVE (Google's form may go live without the customer pressing "Send test data").

R6. Repeat. Google re-sending the same `lead_id` answers `200` and stores nothing new.

R7. Field map. Standard Google columns are matched automatically: `FULL_NAME` -> full name, `EMAIL`/`WORK_EMAIL` ->
email, `PHONE_NUMBER`/`WORK_PHONE` -> phone, `FIRST_NAME`/`LAST_NAME`, `POSTAL_CODE`, `CITY`, `COMPANY_NAME`,
`JOB_TITLE` to the consumer field of the same type when the consumer has one; anything else -> "Lead notes"
(AC-64-24 rule, ONE matcher in `mapping.py` extended with a Google alias table). The map is per form, like Meta.
Questions are learned from received leads: the Fields step lists the columns seen on that form's last lead.

R8. Rotate key (AC-64-44). "Rotate key" (Sources list right-click and the source "..." menu, staff; gateway
`POST /sources/{id}/rotate-key`) makes a new Google key; the old one answers 403 from that moment. The URL stays.
The new key is shown once with the copy step again. History tab records "Key rotated" (who, when).

R9. Wizard, guided path. Channel = Google -> **Copy** (inbound URL and key, each with a copy button; Continue is
blocked until both are copied, AC-64-40; the key is shown only in this session) -> **Test** (guide player for
"Send test data"; passes when the test lead arrives, polling the existing last-test-lead route) -> **Fields** (R7)
-> Done. Fields come after Test because Google's questions are known only from a received lead.

R10. Lists. Sources list shows Google rows with Channel "Google", account column = the source name; Leads list and
lead detail show Google leads with the same columns (form name = form id until a name is known).

## Examples

- Copy step shows `https://<host>/public/lead-capture/in/Ab3...` and a key. Customer pastes both into the Google Ads
  lead form, presses "Send test data". Google POSTs `{"lead_id":"TeSter-123","is_test":true,"google_key":"<key>",
  "form_id":40000000001,"user_column_data":[{"column_id":"FULL_NAME","column_name":"Full Name",
  "string_value":"Test User"},{"column_id":"EMAIL","column_name":"User Email","string_value":"test@example.com"}]}`.
  -> 200, one lead, isTest true, delivered; source LIVE; Test step ticks; Fields lists Full Name and User Email,
  both auto-matched.
- Same body with `google_key: "wrong"` -> 403 invalid_key, no lead, the IP's failure count goes up.
- Same `lead_id` posted twice -> second answer 200, still one lead.
- Staff rotates the key; Google's next POST with the old key -> 403; with the new key -> 200.

## Edge cases

- A custom question (`column_id` absent or not standard) -> answer key = `column_name`, mapped to Lead notes.
- `string_value` missing -> the answer is kept with an empty value, never dropped.
- Numeric ids arrive as numbers or strings; both are stored as strings.
- One tenant can hold several Google sources (one per form group); each has its own URL and key.

## Questions (each with a recommendation)

- Q1. A disconnected source: 410 (recommended, Google shows the webhook failing so the customer notices) or 200 and
  drop (Google stays quiet, leads silently lost)?
- Q2. Gateway create for a product's own wizard (`POST /sources/google` -> `{sourceId, url, key}`): ship it in this
  part (recommended, EcoHub can build its own Google step) or later?
