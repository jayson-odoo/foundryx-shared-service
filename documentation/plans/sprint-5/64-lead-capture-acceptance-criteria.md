# Plan 64 UAC: Lead Capture Service (social and web lead ads into any client CRM)

Plan: `64-lead-capture.md`. New module `lead_capture`. Every AC is a pytest (httpx MockTransport for Meta, Google,
TikTok and the consumer endpoint; never a real Graph call) unless marked [FE] (vitest), [B] (agent-browser run, real
clicks from the sidebar or from the consumer's button, 375px AND 1280px) or [ECOHUB] (built and verified in the EcoHub
repos against this contract; listed here so the contract is complete, tested there).

Clickable reference for every screen and step: https://claude.ai/artifact/WjRzMUCjX7uPaYLHtQhZPA (behaviour and copy
only; the look comes from this repo's design system and the tenant's branding, plan D9).

Grill answers (owner, 14 Nov 2026): wizard hosted in Shared Service and opened from the client CRM; delivery by signed
webhook push plus a pull API; one Foundryx Meta app for every tenant; every common platform that supports an
integration, released in phases (plan section 6).

Owner decisions 14 Nov 2026 (~22:45): D1 Page sharing = per-product toggle (AC-64-36/37); D2 = system-user token if
S-META confirms (AC-64-20); D3 = deliver at once + "Map fields" (AC-64-35); D4 = + `pages_manage_ads`, no
`ads_management` yet; D5 = release 1 is Facebook + Instagram + delivery + EcoHub. Release 1 ACs: A, B, C, D, H, I,
J, K. Release 2: E (WhatsApp ads) and F (Google Ads, website form). Review: `documentation/plans/meta-leads/PLAN-meta-lead-ads-14nov.md`.

## A. Module, install, permissions
- AC-64-01 `modules/lead_capture/manifest.json` declares the module (title "Lead Capture"), its routers (staff router
  gated by `require_module`, a `"public": true` gateway at `/api/v1/lead-capture`, the public webhook ingress), its
  own Alembic history and schema `app_lead_capture`. `optional: ["omnichannel"]`. Installing it creates no table in
  `public` and alters none.
- AC-64-02 Permissions from `modules/lead_capture/permissions/permissions.csv`: `lead_capture.view`,
  `lead_capture.manage` (connect, edit, disconnect sources, field maps, endpoints), `lead_capture.keys.manage`
  (gateway keys). No key collides with a core or other-module key (test greps every `permissions.csv`).
- AC-64-03 Install grants all three keys to the tenant's Admin role; an already-provisioned tenant that installs it
  gets them the same way; an update re-grants (App Store lifecycle). Uninstall wipes only that tenant's rows and revokes
  the keys from every role.
- AC-64-04 [FE][B] With the module ACTIVE a "Lead Capture" menu entry (children only, no clickable parent) shows for a
  user holding `lead_capture.view`; INACTIVE hides it and every staff route answers 403 "Module not installed".

## B. Where setup is done (two entry points, one wizard)
- AC-64-05 [B] Inside Shared Service, Lead Capture > Sources lists the tenant's connected sources (Resource shell list:
  source logo + name, account, status, leads in the last 7 days, last lead time) with one Main Action "Connect a
  source" that opens the wizard. Empty state says what will appear; no second copy of the action.
- AC-64-06 `POST /api/v1/lead-capture/connect-sessions` (gateway key) answers `{url, expiresAt}`: a single-use hosted
  wizard URL on the tenant's own host, valid 10 minutes, bound to tenant + key + optional `returnOrigin` (must be on
  the key's allowed-origin list, else 422 `ORIGIN_NOT_ALLOWED`). A second open of a used or expired URL shows an
  expired page with no wizard and no tenant data.
- AC-64-07 The hosted wizard opened from that URL runs with a scoped embed token (`typ="lead_capture_embed"`, 30
  minute lifetime, scope = this tenant's sources only): it can do everything the wizard does and nothing else (any
  other staff route answers 401/403).
- AC-64-08 On finish or close the hosted page posts `{type: "lead-capture:done" | "lead-capture:closed", sourceId?}`
  to `window.opener` with `targetOrigin` = the session's `returnOrigin` only (never `*`), then closes.
- AC-64-09 `GET /api/v1/lead-capture/sources` (gateway key) returns the same list as AC-64-05 so the consumer can show
  it; `DELETE /api/v1/lead-capture/sources/{id}` disconnects (unsubscribes the Page or revokes the source's webhook
  key, keeps already captured leads).
- AC-64-10 [ECOHUB] EcoHub Leads page has an "All leads | Lead Capture" toggle; Lead Capture shows the source list
  from AC-64-09 with Main Action "Connect a source". Company Settings has a "Lead Capture" tab with the same list and
  action. Both open the hosted wizard (AC-64-06) in a popup and refresh the list on `lead-capture:done`.
- AC-64-11 White-label: no tenant-facing screen, hosted page, email or error says "Foundryx". The hosted wizard shows
  the tenant's name and logo (tenant branding), or the name alone when no logo is set.

## C. Wizard behaviour (all channels)
- AC-64-12 [FE][B] One question per step; a step appears only after the one before is answered; answered steps fold to
  one line (question + answer chip) and reopen on click; answers survive reopening. A progress bar names every step of
  the chosen channel.
- AC-64-13 [FE][B] Step 1 offers only channels that work for this tenant right now (a channel whose platform app is
  not configured on the server, or whose phase is not released, is not offered). Each option shows the real brand logo
  and whether setup is Automatic or Guided.
- AC-64-14 [FE][B] Where the platform allows an API, the step is automatic (no copying). Where it does not, the step
  shows a looping animated guide (play/pause, step dots, caption per frame), a link that opens the platform's own page
  in a new tab, and a "Check again" action that re-reads the platform and moves on only when the prerequisite is met.
- AC-64-15 [FE] A blocked Next/Continue is disabled with its reason under it and pulses what it waits for (e.g.
  "Tick at least one form.", "Copy both values first.").
- AC-64-16 Every wizard ends with a test: the source is saved as `LIVE` only after a test lead (real or the
  platform's test tool) has been received and parsed; a source that has not passed its test is `WAITING_FOR_TEST` and
  can be resumed from the list.
- AC-64-17 [B] The done screen says what was connected, by whom and when, shows the test lead, and names the one thing
  still open ("Waiting for the first real lead").
- AC-64-18 [B] The whole wizard is usable without horizontal scroll at 375px and 1280px, light and dark.

## D. Facebook and Instagram Instant Forms (automatic)
- AC-64-20 "Continue with Facebook" opens Facebook Login for Business for the Foundryx Meta app with the lead scopes
  (plan D4: `pages_show_list`, `pages_manage_metadata`, `pages_read_engagement`, `leads_retrieval`, `pages_manage_ads`;
  `ads_management` is NOT requested in release 1). The login config issues a business system-user token when spike
  S-META confirms it covers Pages and leads (owner D2 = b); otherwise a long-lived user token as below, and the
  Reconnect path (AC-64-29) applies either way. The code is exchanged server-side for a long-lived user token; only an opaque session id crosses the wire
  (same rule as omnichannel's Meta connect session). Without `META_APP_ID` the flow is simulated (dev + tests).
- AC-64-21 The Page step lists only Pages the user granted. One granted Page is chosen automatically and shown folded
  as "(the only Page you shared)".
- AC-64-22 Instagram path: the Page's linked Instagram business account is read; none linked = warning + animated
  guide + "Check again"; linked = the account is shown and chosen.
- AC-64-23 Forms step reads the Page's lead forms. None = warning + animated "Create an Instant Form" guide + "Check
  again". Some = "All forms, including new ones" (default) or "Only the forms I tick" (blocked until one is ticked).
- AC-64-24 Field map: each form question is listed with a target lead field (searchable dropdown). Standard questions
  (full name, phone, email) are matched automatically; custom questions default to "Lead notes". Targets come from the
  consumer's field list (AC-64-61), never a hardcoded CRM field set.
- AC-64-25 Connect subscribes the Page to the app's `leadgen` field and stores a long-lived Page token Fernet-encrypted.
  The subscribe call ADDS `leadgen` to the fields the app already holds on that Page (read first, then post the union);
  it never removes omnichannel's Messenger fields, and omnichannel's own subscribe never removes `leadgen` (one shared
  core function, lane S0). The same tenant reconnecting replaces the token in place. A Page already live under
  ANOTHER tenant follows the Page-sharing rule (AC-64-36): refused with `PAGE_IN_USE` (no data of the other tenant
  shown) unless sharing is allowed on both sides.
- AC-64-26 A `leadgen` webhook (signature checked with the app secret, invalid = 403 and nothing stored) is
  acknowledged 200 within 2 s and processed in the background: fetch `/{leadgen_id}` with that Page's token, store the
  raw answer, map it, deliver it. The tenant(s) are resolved from `page_id` against live sources only. The hand-off from the omnichannel ingress to
  Lead Capture runs BEFORE omnichannel's own channel lookup and module-active check, so a Page with no Messenger
  channel, or a tenant without omnichannel, still gets its leads.
- AC-64-27 Idempotent by `leadgen_id`: the same webhook delivered twice creates one lead and one delivery.
- AC-64-28 Backfill: every 15 minutes, and on demand from the source, each LIVE form is read for leads created since
  its cursor (cap 90 days). In "All forms" mode each run first re-reads the Page's form list (`GET /{page_id}/leadgen_forms`),
  so a form created after setup is included from its first lead (a new form starts at its own creation time); leads the webhook missed are created through the same path (idempotent with AC-64-27).
- AC-64-29 Token health: a Graph answer meaning the token is invalid or the permission was removed sets the source to
  `NEEDS_RECONNECT` (list badge, consumer webhook `source.updated`, one email to `lead_capture.manage` holders); the
  wizard's reconnect path keeps the source id, field map and leads.
- AC-64-30 The test step can fire Meta's test lead (Lead Ads Testing Tool equivalent via the Graph test-lead endpoint,
  or the user's own submission); the received test lead is marked `isTest: true` everywhere, including deliveries.

- AC-64-35 New form found (owner D3 = a): a lead from a form the source has no field map for is delivered at once
  (standard name / phone / email matched by type from that form's questions, every other answer to Lead notes) and
  the source shows a "Map fields" notice naming the form and how many answers go to Lead notes, in the Shared
  Service list, in `GET /api/v1/lead-capture/sources` (`needsMapping: [{formId, formName, unmappedCount}]`) and as a
  `source.updated` event. "Map fields" reopens the Fields step for that form only; saving clears the notice. Leads
  never wait for mapping.
- AC-64-36 Page sharing is a per-product setting (owner D1): "Allow a Facebook Page that another product also uses",
  default OFF, stored per tenant (`lc_settings.allow_shared_pages`), changed by `lead_capture.manage` in Lead Capture >
  Settings or by the consumer through `GET|PUT /api/v1/lead-capture/settings`. Connecting a Page already live under
  another tenant succeeds only when the connecting tenant AND every tenant already live on that Page allow sharing;
  otherwise `PAGE_IN_USE`, worded the same in every case (it never says whether the other side allows sharing).
  Turning the setting OFF blocks new joins only; Pages already shared stay connected and the settings screen shows
  how many. The check runs under a lock on (platform, Page id), so two tenants connecting at the same moment cannot
  both slip past it.
- AC-64-37 Shared Page delivery: a `leadgen` webhook for a Page live under several tenants fetches the lead once
  (with the first healthy token) and creates one `lc_lead` per live source, each mapped with that source's own field
  map and delivered to that tenant only. One tenant disconnecting or going `NEEDS_RECONNECT` never unsubscribes the
  Page or stops the others; the Page is unsubscribed only when its last live source goes.
- AC-64-38 [B] Every source has a History tab (shared history component): connected, reconnected, forms changed,
  fields mapped, sharing setting changed, disconnected, with who, on behalf of, when, and old -> new.

## E. Click-to-WhatsApp (needs omnichannel)
- AC-64-31 Offered only when omnichannel is ACTIVE for the tenant. Number step lists the tenant's connected WhatsApp
  channels; "Connect a new number" runs omnichannel's existing Embedded Signup (no second implementation).
- AC-64-32 Rule step: "Chats that start from an ad" (default), "Every new chat", "After a few questions" (a WhatsApp
  Flow named by the tenant; lead created when it completes).
- AC-64-33 When omnichannel stores an inbound message carrying a CTWA `referral`, it calls capability
  `lead_capture.ad_referral@1` with the message, contact and referral (source_id, source_url, headline, body,
  media_type, ctwa_clid). With Lead Capture not ACTIVE the capability resolves to None and omnichannel behaves exactly
  as today (its existing suites pass unedited).
- AC-64-34 One lead per contact per ad per 7 days (later chats from the same ad add a note, not a lead); `ctwa_clid`,
  ad id and headline are stored on the lead.

## F. Guided webhook sources (Google Ads, website form, TikTok)
- AC-64-40 Each guided source gets its own inbound URL `https://<host>/public/lead-capture/in/{sourceKey}` and a
  secret key, shown once with copy buttons; Continue is blocked until both are copied.
- AC-64-41 Google Ads: a POST in Google's lead form webhook format with the matching `google_key` creates a lead;
  a wrong key is 403 and stores nothing; Google's "Send test data" body (`is_test: true`) passes the source's test.
- AC-64-42 Website form: an embed snippet (one script line) renders a form posting to the source URL, and a plain JSON
  POST with the key in `X-Lead-Key` also works; fields map like AC-64-24. Per-source rate limit (60/min/IP, 429).
- AC-64-43 TikTok: built only after the plan's TikTok spike (S-TT) confirms the delivery method; until then TikTok is
  not offered (AC-64-13).
- AC-64-44 Rotating a source key invalidates the old one at once; the guide and copy step are shown again.

## G. Further platforms (phase C, each behind its own spike)
- AC-64-45 Each further platform (LinkedIn Lead Gen Forms, Messenger and Instagram Direct click-to-message ads,
  Snapchat Lead Ads, Pinterest Lead Ads) is added as one provider implementing the provider contract (plan D6) with
  its own UAC addendum written after its spike; none is offered before its addendum's ACs pass.

## H. Leads: normalise, dedupe, keep
- AC-64-50 Every captured lead is stored once with: tenant, source, platform, platform lead id, received_at (UTC),
  mapped fields, raw payload (JSON), attribution (campaign, ad set, ad, form ids and names when the platform gives them,
  `ctwa_clid` / `gclid` / `ttclid`), `isTest`.
- AC-64-51 Phone numbers are normalised to E.164 (default country from tenant settings); emails lower-cased.
- AC-64-52 Duplicate rule: same tenant + same E.164 phone (or same email when no phone) within 30 days = the lead is
  stored with `duplicateOf` set and still delivered with that flag; the consumer decides.
- AC-64-53 Staff list Lead Capture > Leads (Resource shell): filter by source, platform, date, test; detail shows mapped
  fields, attribution, raw payload and every delivery attempt.
- AC-64-54 Raw payloads and personal fields are deleted 180 days after capture (nightly task); the lead row keeps ids,
  source, timestamps and delivery status only.
- AC-64-55 `fields_json` and `raw_json` are Fernet-encrypted at rest (core `app/secrets.py`); `phone_e164` and
  `email` stay plain only so duplicate checks and search work. The purge (AC-64-54) and the 15-minute backfill are
  listed on Scheduled Tasks with last run, last error and Run now.

## I. Delivery to the client CRM
- AC-64-60 Webhook endpoints are managed per tenant (`/api/v1/lead-capture/webhooks`, gateway key, max 5): URL, events
  (`lead.created`, `lead.updated`, `source.updated`), secret shown once.
- AC-64-61 `PUT /api/v1/lead-capture/fields` lets the consumer publish its lead field list (key, label, type) used as
  map targets (AC-64-24). Without one, the targets are name, phone, email, notes.
- AC-64-62 Each event is POSTed with headers `X-Lead-Capture-Event`, `X-Lead-Capture-Delivery` (id) and
  `X-Lead-Capture-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, t + "." + body)>`; the body is the documented lead
  shape (camelCase, ISO-Z times).
- AC-64-63 Any non-2xx or timeout (10 s) is retried at 1 min, 5 min, 30 min, 2 h, 6 h, 24 h, then marked FAILED and
  shown in the lead detail; "Redeliver" (staff, `lead_capture.manage`) and `POST /api/v1/lead-capture/deliveries/{id}/redeliver`
  resend the same body with a new signature.
- AC-64-64 The callback URL is re-validated before EVERY attempt with core `url_guard.assert_deliverable`; an internal
  or unresolvable target fails the attempt and never sends.
- AC-64-65 Pull: `GET /api/v1/lead-capture/leads?since=&cursor=&source=` returns leads in `received_at, id` order with a
  cursor, same shape as the webhook body.
- AC-64-66 The consumer guide `documentation/lead-capture/consumer-integration-guide.md` documents every gateway route,
  event, header, body field and error code; a diff touching the gateway schemas without a guide diff fails review.
- AC-64-67 [ECOHUB] EcoHub (via ecohub-backend) verifies the signature, creates a Lead per `lead.created` (status New,
  source = platform, mapped fields), is idempotent on the lead id, and answers 2xx only after commit.

## J. Security and tenancy
- AC-64-70 Every staff and gateway query is tenant-scoped from the JWT, embed token or key; every stored source, page,
  form and endpoint id is resolved WITH tenant at use time. Cross-tenant tests for sources, leads, deliveries, sessions.
- AC-64-71 No token, secret, key or full payload appears in any log line (caplog DEBUG), error text or API answer; the
  source GET shows only `****` + last 4 of a key.
- AC-64-72 Gateway keys: hashed at rest, prefix `fxl_live_`, revocable, per-IP and per-key throttle (429), every call
  audited (tenant, key, route, status).
- AC-64-73 Inbound ingress endpoints answer within 2 s, never 500 on a malformed body (400 and nothing stored), and are
  throttled per source.

## K. Operations
- AC-64-80 Env: `META_APP_ID`, `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN` (already used by omnichannel),
  `LEAD_CAPTURE_LOGIN_CONFIG_ID`, `TIKTOK_APP_ID`/`TIKTOK_APP_SECRET` (phase B) in `docker-compose.yml` x-backend-env and
  `deploy.yml` ENV_CONTENT; missing values only hide the channels that need them (AC-64-13).
- AC-64-81 A runbook `documentation/lead-capture/meta-app-review-runbook.md` lists the Meta app settings, permissions,
  App Review screencast script (recorded on the Foundryx Page in dev mode) and Business Verification steps.
