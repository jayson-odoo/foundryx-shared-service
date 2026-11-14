# Plan 64: Lead Capture Service (social and web lead ads into any client CRM)

Module `lead_capture`, size XL, three phases, branch per lane `sprint-5/lead-capture-<lane>`. UAC:
`64-lead-capture-acceptance-criteria.md`. Mock (behaviour + copy reference):
https://claude.ai/artifact/WjRzMUCjX7uPaYLHtQhZPA. First consumer: EcoHub (Leads > Lead Capture, Company Settings >
Lead Capture).

## 1. Why (owner, 14 Nov 2026)

"develop a lead capture module in my CRM to integrate facebook/instagram/whatsapp lead gen to flow into my CRM ... a
module to be used by different clients (like a middleware, in Foundryx Shared Service)." / "a wizard to guide user how
to set up on their own in the simplest way possible (automated if possible, if not an animation in every steps)" /
"it should be able to be configured in Settings, or the Leads page (Lead Capture)".

Grill (14 Nov): wizard hosted in Shared Service; delivery = signed webhook push + pull API; one Foundryx Meta app;
channels = Facebook + Instagram Instant Forms, Click-to-WhatsApp, Google Ads, website form, TikTok, "and all other
common platforms that can support integration".

## 2. Facts (main at branch point; OC = `service_backend/modules/omnichannel`)

- F1 Omnichannel owns the app's ONE Meta webhook ingress (`OC/routers/webhooks.py`, `X-Hub-Signature-256` check at
  :37). It dispatches on `payload["object"]` (`page` / `instagram` / `whatsapp_business_account`) and resolves the
  tenant from the account id GLOBALLY (`OC/services/inbound_service.py`; doc `omnichannel-service.md:63`). A Meta app
  has one callback URL per object, so a `page` `leadgen` change arrives at this same endpoint. It ignores `changes[]`
  fields it does not know today.
- F2 Omnichannel already does Facebook Login for Pages: `MetaConnectSession` (`meta_connect_sessions`, 5 min TTL,
  single use, Fernet token, only an opaque id on the wire), `MessengerAdapter.exchange_code`,
  `exchange_long_lived_token`, `list_pages` (`GET /me/accounts`) (`OC/adapters/messenger.py`, doc :71). Dev-safe stubs
  when `META_APP_ID` is unset.
- F3 Omnichannel parses WhatsApp inbound messages but stores no CTWA `referral` (grep: no `referral` under OC).
- F4 Core `app/services/url_guard.py:140 assert_deliverable` is the per-attempt SSRF guard (omnichannel keeps its own
  copy at `OC/services/webhook_service.py:105`).
- F5 Embed-token precedent: omnichannel `POST /embed/session` mints a scoped embed access token
  (`OC/routers/embed.py`, `OC/embed_auth.py`, plan 11H).
- F6 Gateway key precedents: omnichannel `WorkspaceApiKey` (Bearer `fxw_live_`), autocount `AcPullApiKey`
  (`X-API-Key` `fxa_live_`, throttle + audit table); duplication tracked as BL-SS-210 (module-platform doc table).
- F7 Capabilities: `register_capability` / `resolve_capability(db, tenant_id, key, version)` returns None when the
  provider is not ACTIVE for the tenant (module-platform doc D5). Manifest `optional` deps supported (D4).
- F8 No `lead` permission key exists in any `permissions.csv` (grep 14 Nov). No `lead_capture` code exists.
- F9 EcoHub (consumer, other repos): Next.js app is a thin caller of ecohub-backend (FastAPI); Lead statuses
  New/Proposal/Won/Lost (`lib/constants/filter-options.ts:1`); Company Settings tabs in
  `components/company-settings-form.tsx:724-739` (has "Leads Settings"); menu `config/menu.ts` (Sales Lifecycle >
  Leads, Settings > Company Settings). EcoHub already consumes the omnichannel gateway with a workspace key.
- F10 UNVERIFIED (to confirm in spike S-META before D4 is final): exact current Meta permission names and whether
  `ads_read` is needed to name campaigns; test-lead edge availability for a dev-mode app; Login for Business config id
  requirement. Facts on TikTok, LinkedIn, Snapchat and Pinterest delivery are UNVERIFIED until their spikes.

## 3. Decisions

- D1 **New module `lead_capture`**, schema `app_lead_capture`, own Alembic (rev 0001), `optional: ["omnichannel"]`.
  Not part of omnichannel: Google, website and TikTok sources do not need WhatsApp, and tenants may buy one without
  the other.
- D2 **Hosted wizard** in the Shared Service frontend at `/lead-capture/connect` (tenant host). Two ways in: a staff
  user from Lead Capture > Sources, or a consumer CRM via `POST /api/v1/lead-capture/connect-sessions` (gateway key)
  which returns a single-use URL that swaps for a scoped embed token (F5 pattern, new `typ`). The page talks back to
  the opener with `postMessage` to the session's `returnOrigin` only.
- D3 **Meta plumbing moves to core** `app/integrations/meta/` (code exchange, long-lived token, `/me/accounts`,
  `subscribed_apps`, signature check, Graph error classification). Pure move first (slice S0): omnichannel imports it,
  its suites pass UNEDITED. Lead Capture uses it directly; no cross-module import.
- D4 **One Foundryx Meta app.** Scopes requested by Lead Capture's login config (owner 14 Nov, D4 = b):
  `pages_show_list`, `pages_manage_metadata`, `pages_read_engagement`, `leads_retrieval`, `pages_manage_ads`
  (Meta's retrieving-leads page lists it for full lead data). `business_management` only if S-META shows the
  system-user login needs it. `ads_management` (campaign and ad names) is deferred to a later release. Token type
  (owner D2 = b): business system-user token via Login for Business when S-META confirms it covers Pages and leads,
  else the long-lived user/Page token; Reconnect (AC-64-29) stays in both cases. App name shown on Facebook's consent screen must be neutral
  (white-label, O-2).
- D5 **Meta webhook field registry in core** `app/integrations/meta/webhook_registry.py`:
  `register_meta_change_handler(object, field, provider_module, handler)` at boot, one owner per (object, field), a
  second claimant is a loud boot error (same shape as `register_public_cors_prefix`). Omnichannel's ingress, BEFORE its
  own channel lookup and module-active check (`OC/services/inbound_service.py:81-93`, which would otherwise drop a
  lead-only Page), hands each `changes[]` entry whose (object, field) has an owner to that handler (sync, fast, the handler
  only enqueues). Lead Capture registers (`page`, `leadgen`). Without Lead Capture installed nothing changes.
- D6 **Provider contract** `modules/lead_capture/providers/base.py`: `key`, `phase`, `mode` (auto | guided),
  `is_configured()` (env present), `wizard_steps`, `parse_inbound(request) -> list[RawLead]`, `fetch(raw) -> RawLead`
  (auto only), `backfill(source, since)`, `test(source)`. Registry dict, one file per platform. Adding a platform =
  one file + its UAC addendum.
- D7 **Delivery**: own endpoint + delivery tables and Celery task modelled on omnichannel's consumer webhooks
  (retry ladder, per-attempt `url_guard.assert_deliverable`, HMAC signature with timestamp). Pull API reads the same
  rows. No shared core webhook engine yet (BL-SS-210 class; promote when a third copy appears).
- D8 **Gateway key** `LcApiKey` (`fxl_live_`, Bearer), mirrors `WorkspaceApiKey` + autocount's throttle/audit. One
  more copy of the BL-SS-210 pattern; noted there.
- D9 **Look**: the wizard keeps the mock's behaviour (one step at a time, folded answers, animated guides, blocked
  actions with reasons, test before live, done screen) and uses this repo's design system (`docs/reference/design-language.md`,
  Resource shell, `SearchSelect`) with tenant branding. The mock's Playbook UIUX look (red action, Geist, Slate) is not
  applied here (O-1).
- D10 **CTWA via capability**: omnichannel calls `lead_capture.ad_referral@1` (provided by Lead Capture) after it stores
  an inbound message with a `referral`; omnichannel stores the referral on the message (new nullable JSON column on its
  OWN message table + backfill no-op since old rows have none). Lead Capture never reads omnichannel tables.
- D11 **Lead store is a buffer, not a CRM**: no statuses, owners or pipelines here; the consumer owns the lead's life.
  Raw + personal fields purged after 180 days (AC-64-54).
- D13 **Page sharing is a per-product toggle** (owner 14 Nov: "it should be toggleable per product"). Setting
  `allow_shared_pages` per tenant, default OFF, in Lead Capture > Settings and `GET|PUT /api/v1/lead-capture/settings`
  (so EcoHub can show it in its own Company Settings > Lead Capture tab). A Page may be live under several tenants only
  when every tenant on it allows sharing; else `PAGE_IN_USE`, worded the same either way (AC-64-36). A shared Page's
  lead is fetched once and stored + delivered once per live source with that source's own map (AC-64-37). The Page is
  unsubscribed only when its last live source goes.
- D14 **New forms deliver at once** (owner D3 = a): unmapped answers go to Lead notes and the source shows "Map
  fields" (AC-64-35); in All-forms mode the backfill re-reads the form list each run (AC-64-28).
- D15 **One Page-subscribe function** in core `app/integrations/meta/` (lane S0) reads the app's current fields on the
  Page and posts the union, used by both omnichannel (Messenger fields, today `OC/adapters/messenger.py:94,311`) and
  Lead Capture (`leadgen`), so neither switches the other off.
- D12 **Animated guides** are data (frames of schematic screens + target + caption), one JSON per platform step,
  rendered by one `GuidePlayer` component. A platform UI change = edit the JSON.

## 4. Data model (`app_lead_capture`)

- `lc_source` id, tenant_id, platform, mode, name, status (DRAFT | WAITING_FOR_TEST | LIVE | NEEDS_RECONNECT |
  DISCONNECTED), account_ref (page id / channel id / null), account_name, config_json (forms mode + ids, rule, IG
  account), field_map_json, credentials_json (Fernet: page token / source key hash), source_key (guided, unique),
  cursor_at, created_by, created_at, updated_at, last_lead_at. Partial unique index (tenant_id, platform, account_ref) over live
  rows (one live source per Page per tenant). The cross-tenant rule is NOT an index any more (D13): the connect
  service takes a Postgres advisory lock on hash(platform, account_ref), reads the live sources on that Page and
  applies AC-64-36. Ingest resolves `page_id` to ALL live sources.
- `lc_settings` tenant_id (pk), allow_shared_pages bool default false, updated_by, updated_at.
- `lc_connect_session` id, tenant_id, key_id, user_id null, return_origin, token_hash, expires_at, consumed_at,
  meta_session_json (Fernet).
- `lc_lead` id, tenant_id, source_id, platform, platform_lead_id, received_at, fields_json (Fernet), raw_json (Fernet), attribution_json,
  phone_e164, email, duplicate_of null, is_test, purged_at. Unique (source_id, platform_lead_id).
- `lc_webhook_endpoint` id, tenant_id, url, events, secret (Fernet), active. `lc_delivery` id, tenant_id, endpoint_id,
  lead_id null, event, body_json, attempt, next_at, status, last_code, last_error.
- `lc_consumer_field` tenant_id, key, label, type, sort. `lc_api_key` + `lc_api_audit` (D8).

## 5. Wire (gateway `/api/v1/lead-capture`, Bearer `fxl_live_...`; contract of record = the consumer guide)

`POST /connect-sessions {returnOrigin}` -> `{url, expiresAt}` · `GET /sources` · `DELETE /sources/{id}` ·
`PUT /fields [{key,label,type}]` · `GET|POST|DELETE /webhooks` · `GET /leads?since&cursor&source` ·
`POST /deliveries/{id}/redeliver`. Events `lead.created`, `lead.updated` (duplicate resolved, backfill enrich),
`source.updated`. Headers and retry ladder per AC-64-62/63. Inbound: Meta via omnichannel ingress (D5);
guided sources `POST /public/lead-capture/in/{sourceKey}`.

## 6. Phases and lanes (order is the dependency order)

Release 1 (owner 14 Nov, D5 = b): S-META, S0, L1, L4, L2 (Facebook + Instagram channels only), L3, L-ECO, OPS.
Release 2: L5 (Google Ads, website form), L6 (Click-to-WhatsApp). Then L7 TikTok (after S-TT) and one lane per further
platform after its spike. Release 1 lane detail: `documentation/plans/meta-leads/PLAN-meta-lead-ads-14nov.md` section 9.

| Lane | Scope | UAC | Depends |
|---|---|---|---|
| S0 | Move Meta plumbing to `app/integrations/meta/` + webhook field registry (D3, D5). Omnichannel suites pass unedited | 20 (dev stub), 26 (dispatch) | - |
| S-META | Spike, 1 day: on the Foundryx Page in dev mode confirm scopes, test-lead edge, leadgen payload, token lifetimes, Login for Business config; record real payloads as fixtures; finalise D4 | F10 | - |
| L1 | Module skeleton: manifest, schema, Alembic 0001, permissions + grant, menu, gateway key + audit, consumer fields, staff Sources/Leads lists (FE mock first) | 01-05, 53, 61, 70-72 | S0 |
| L2 | Hosted wizard shell: connect sessions, embed token, postMessage, step engine, GuidePlayer + guide JSON, done screen, white-label (FE mock first, all channels simulated) | 06-08, 11-18 | L1 |
| L3 | Facebook + Instagram: login, pages, IG check, forms, map, subscribe, leadgen handler, fetch, backfill, token health, test lead | 20-30 | L2, S-META |
| L4 | Delivery: endpoints, signed push, retry, redeliver, pull, purge task, consumer guide | 50-52, 54, 60, 62-66 | L1 |
| L5 | Guided sources: Google Ads, website form + embed snippet, key rotation | 40-42, 44, 73 | L2, L4 |
| L6 | CTWA: omnichannel referral column + capability call; Lead Capture rule + dedupe window | 31-34 | L3, L4 |
| L-ECO | EcoHub (other repos): Leads toggle + Settings tab, popup, source list, ecohub-backend webhook receiver + lead create | 10, 67 | L2, L4 |
| S-TT / L7 | TikTok spike then provider | 43 | L5 |
| S-xx / L8+ | LinkedIn, Messenger + IG Direct ads (reuses omnichannel Messenger), Snapchat, Pinterest: spike, UAC addendum, provider | 45 | L5 |
| OPS | Env wiring, Meta App Review + Business Verification runbook, prod callback field subscription | 80-81 | S-META |

Each lane follows `/feature`: tester red tests from the UAC first, one coder per lane, reviewer + security-reviewer +
agent-browser verification in parallel, DoD gate. security-reviewer is mandatory on S0, L2, L3, L4, L5, L6 (OAuth,
embed tokens, public ingress, webhooks out, secrets).

## 7. Tests (beyond the per-AC tests)

- Real recorded payloads from S-META as fixtures for leadgen webhook, `/{leadgen_id}`, `/{form_id}/leads`, Graph errors.
- Cross-tenant suite: Page id owned by tenant B never lands in A; embed token of A cannot read B; pull cursor scoped.
- Omnichannel regression: its webhook, inbound and Meta connect suites unedited after S0 and L6.
- Contract test: gateway schemas vs the consumer guide example bodies (fails on drift).

## 8. Rollout

1. S0 merged and deployed alone (behaviour unchanged). 2. Meta app: add the lead scopes and `leadgen` field in dev
mode; owner tests on the Foundryx Page. 3. Phase A behind module install (only tenants that install it see it).
4. App Review + Business Verification (runbook) before any non-Foundryx tenant connects a Page they do not admin in
the app. 5. EcoHub lane ships after L4 is on production.

## 9. Open questions (owner)

Decided 14 Nov ~22:45 (owner: "for meta, 1 it should be toggleable per product, 2b, 3a, 4b, 5b"): D13, D2/D4, D14,
D4, release split above. Still open:

- O-1 Look of the hosted wizard: this repo's design system + tenant branding (D9, recommended, required for
  white-label) or the Playbook UIUX look from the mock?
- O-2 The Meta app's display name is shown on Facebook's consent screen to every client's users. The existing app
  (App ID 1425562942670564, Live, owner screenshot 14 Nov) is named "Foundryx WA App", which misnames a leads
  connection. Recommendation: rename it before App Review is submitted, to "Foundryx" (covers every channel on the
  app), or to a neutral name if the consent screen must stay unbranded. Owner to choose the name.
- O-3 Pricing/entitlement per tenant (number of sources, leads per month) - none in phase A unless decided.
- O-4 Conversions API write-back (send CRM outcome back to Meta with `lead_id` / `ctwa_clid`) - deferred to backlog;
  confirm it is phase D, not A.

## 10. Backlog (to `documentation/backlogs/backlog.md` when the plan is approved)

- Conversions API (CRM stage -> Meta / Google offline conversions) using stored `leadgen_id`, `ctwa_clid`, `gclid`.
- Promote gateway key + consumer webhook delivery to core (third copy, BL-SS-210).
- Per-tenant lead routing rules (assign by source/form) if a consumer asks for it in the payload.
