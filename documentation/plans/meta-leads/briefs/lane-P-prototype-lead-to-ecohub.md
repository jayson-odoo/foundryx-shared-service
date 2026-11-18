# Lane P brief: prototype, one Foundryx Page lead lands in EcoHub today (plan 64 release 1)

Owner 15/11/2026 ~15:35: "i need the prototype working". The goal is a Meta test lead on the Foundryx Page
(id in `S-META-result.md`) arriving in EcoHub end to end, at Standard access (app-role users only). Size M, backend
only.

This is NOT throwaway work. It builds the backend spine of lanes 3 (L1), 4 (L4) and 6 (L3) against their plan 64
acceptance criteria. Lanes 3, 4, 5 and 6 then add the UI, wizard and remaining ACs on top. Branch from #237's head
(`crew/meta-l2-plumbing`) until #237 merges, then rebase-free merge main.

## Read first

- `documentation/plans/sprint-5/64-lead-capture.md` and `64-lead-capture-acceptance-criteria.md` (on PR #236)
- `documentation/plans/meta-leads/S-META-result.md` and `fixtures/` (on PR #238). These are real payload shapes:
  use them as test fixtures.
- `PRINCIPLES.md`, `CLAUDE.md`, `service_backend/CLAUDE.md`

## In scope (ACs, partially where noted)

**1. Module skeleton** (AC-64-01, 02, 03; L1 subset):

- `modules/lead_capture/`: manifest with `optional: ["omnichannel"]`, schema `app_lead_capture`, own Alembic `0001`
  (revision id at most 32 chars).
- Permissions CSV `lead_capture.view` / `.manage` / `.keys.manage`, with an install grant to Admin.
- No frontend.

**2. Tables:**

- `lc_source` with the partial unique index `(tenant_id, platform, account_ref)` over live rows (D13).
- `lc_settings`.
- `lc_lead` with `fields_json` and `raw_json` Fernet-encrypted (AC-64-55), unique `(source_id, platform_lead_id)`.
- `lc_webhook_endpoint` and `lc_delivery`.

**3. Staff connect API, no wizard yet.** `POST /lead-capture/sources/facebook` (`lead_capture.manage`), body
`{pageId, systemUserToken, formsMode:"all"}`:

- Derives the Page token from the system-user token, per S-META F4: `GET /{page}?fields=access_token`.
- Stores the Page token Fernet-encrypted.
- Subscribes `leadgen` through #237's `subscribe_page_fields` (union).
- Applies the D13 sharing rule (AC-64-25/36) under an advisory lock.
- The token is never logged or echoed (AC-64-71).

The hosted wizard (lane 5) later calls the same service function.

**4. Leadgen handler** (AC-64-26, 27):

- Registers (`page`, `leadgen`) via #237's `register_meta_change_handler`.
- The handler only enqueues a Celery task.
- The task resolves ALL live sources for `page_id` (AC-64-37), then `GET /{leadgen_id}` with the Page token, stores,
  maps and queues delivery.
- Field map: standard Meta keys (`full_name`, `email`, `phone_number`) map by name; everything else goes to `notes`
  (AC-64-24 default and AC-64-35, notice data only).
- `is_test` is true when the lead came from `test_leads` (see `fixtures/`).

**5. Delivery** (AC-64-60, 62, 63, 64):

- Gateway key `fxl_live_` (AC-64-72) plus `POST /api/v1/lead-capture/webhooks` to register EcoHub's endpoint.
- Signed `lead.created` push, headers per AC-64-62, retry ladder per AC-64-63.
- Per-attempt `url_guard.assert_deliverable`.
- Reuse omnichannel's sender (`modules/omnichannel/services/webhook_delivery.py`) through ONE shared function (R5),
  not a copy.
- Write the consumer guide stub `documentation/lead-capture/consumer-integration-guide.md` with the exact body
  shape (AC-64-66). EcoHub builds against it.

**6. Pull** `GET /api/v1/lead-capture/leads?since=&cursor=` (AC-64-65).

## Out of scope here (later lanes)

Wizard and all UI (lane 5), Sources/Leads lists (lane 3), backfill, token health and Reconnect (lane 6), purge task
(lane 4), sharing-settings API surface beyond the stored flag.

## Tests (tester red first, httpx MockTransport, never real Graph)

- The S-META fixture webhook enqueues and produces one lead; a replay produces no second lead.
- A tampered signature returns 403.
- Two tenants share a Page: each gets its own lead only when both allow sharing. A second connect is refused
  otherwise.
- The token never appears in caplog.
- Delivery: signature verifies; a 500 retries; an internal URL is refused.
- Cross-tenant: tenant A's key cannot read B's leads.

## Definition of Done

- The DoD gate in `CLAUDE.md` applies: no mock, grant sweep for existing tenants, migration verified on live Postgres.
- reviewer + security-reviewer run in parallel (secrets, webhooks, gateway).

## Live prototype run (crew, with the owner for Facebook-side clicks only)

1. Deploy this branch to the Shared Service test copy behind a public tunnel. The owner allows crew to own SS
   releases.
2. Set the app's `page` webhook object to `https://<test-copy>/be/omnichannel/webhooks/lead` via
   `POST /{app}/subscriptions` with the app token, field `leadgen`. No Page webhook exists today (S-META F2), so
   Messenger is unaffected.
3. Install Lead Capture for the EcoHub test company. Create a gateway key. Register EcoHub's receiver URL.
4. `POST /lead-capture/sources/facebook` with the system-user token for the Foundryx Page. The system user already
   has the Page asset (S-META, owner's step A).
5. Fire a test lead: `POST /{form}/test_leads` on "S-META test 1", or the owner uses the Lead Ads Testing Tool.
   Delete the old test lead first (S-META F7 quirk).
6. Expected: an `lc_lead` row with `is_test=true`, a signed delivery 2xx, and a Lead with status New in EcoHub.
