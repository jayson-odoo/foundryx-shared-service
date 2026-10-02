# 32 - Omnichannel channel adapters: Facebook Messenger + Instagram DM (A7a)

> **Contract:** `32-omnichannel-channels-messenger-instagram-acceptance-criteria.md` (63 ACs).
> This plan fulfils it.
> **Program:** slice **A7a** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G20,
> roadmap row A7, Q1 = "the customer uses all of them", order decided 2026-09-05).
> **Depends on:** plan 25 / A1 and plan 26 / A2 (merged at `c25a97ff`). **Branch AFTER plan 31 / A5
> merges** - A7a edits `modules/omnichannel/workflow_nodes.py` and `service_frontend/lib/workflow-
> catalog.ts`, both of which plan 31 rewrites wholesale (section 7, R1).
> **Branch:** `sprint-4/32-channels-messenger-instagram`, worktree `.claude/worktrees/s32` off
> `main` AFTER that merge. Lane: backend `:8010` on DB `foundryx_service_s32`, frontend `:3009`,
> `agent-browser --session s32`. Each worktree gets its OWN `npm ci` (never a shared
> `node_modules`).
> **Code read at:** `origin/main` `c25a97ff` (all `file:line` references in section 6 are pinned
> there).

## 1. Why

The customer runs WhatsApp, Messenger, Instagram, Telegram, web chat, email and SMS on respond.io
(Q1). Messenger and Instagram go first because they are the ONLY two that need no new transport,
no new credential model and no new webhook infrastructure: they ride the same Meta app, the same
`X-Hub-Signature-256` verification, the same fast-ACK-to-Celery pipeline, the same Fernet channel
credentials and the same Graph telemetry recorder that WhatsApp already uses. Building them first
also forces the two generalizations every later channel needs and that today are hardcoded to
WhatsApp:

1. **the messaging window** - five call sites currently ask `_window_open(contact)` against a single
   `contacts.csw_expires_at` column and a 24h constant, and the only re-engagement mode they know
   is "approved WhatsApp template";
2. **addressing** - `send_runner` sends to `digits(contact.phone)` from `channel.phone_number_id`,
   which is meaningless for a PSID on a Page.

A7a turns both into per-channel-type policy objects with WhatsApp as one row. Telegram, web chat,
email and SMS then become adapter plus policy row plus connect step, not another refactor.

## 2. Architecture

```
Meta app (ONE, already configured: META_APP_ID / META_APP_SECRET / META_GRAPH_VERSION)
  |
  |  products:  WhatsApp        Messenger        Instagram
  |  webhook:   ONE app-level callback per product, ALL pointed at
  |             POST /omnichannel/webhooks/meta   (public, signature-verified, fast-ACK)
  v
routers/webhooks.py  --unchanged--> worker.process_inbound_webhook --> InboundService.process_payload
                                                                          |
                          _resolve_channel dispatches on payload["object"]:
                            whatsapp_business_account | (absent) -> metadata.phone_number_id (today)
                            page                              -> channels.external_account_id, FACEBOOK
                            instagram                         -> channels.external_account_id, INSTAGRAM
                                                                          |
                                            get_adapter(channel.channel_type).parse_inbound(payload)
                                                                          |
                            canonical events (message | status | reaction | template_*) - UNCHANGED shape
                                                                          |
                    _handle_message -> _resolve_contact (identity -> [phone stitch: WhatsApp only] -> create)
                                    -> messaging_policy.stamp_inbound_window(identity, contact, channel)
                                    -> realtime + consumer webhook + workflow trigger (unchanged)

OUTBOUND (one path, unchanged in shape)
  MessageService.<send_*>  -> messaging_policy.authorize(contact, channel, kind, actor) -> SendDecision
                           -> row.metadata_json["metaSend"] = {messagingType, tag}
                           -> send_runner.run_send
                                -> channel_addressing.sender_ref(channel) / recipient_ref(db, channel, contact)
                                -> get_adapter(channel.channel_type).send(...)
```

One rule holds the slice together: **nothing branches on `channel_type` outside three files** -
`adapters/` (how to talk to the provider), `services/messaging_policy.py` (what may be sent and
when) and `services/channel_addressing.py` (who the parties are). Every other file stays type-blind.

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Shared Meta plumbing | `modules/omnichannel/adapters/meta_graph.py` (new) | `GraphCall`, `GraphRecorder`, `_meta_error_detail`, `MetaGraphMixin` (`_graph_call`, `_configured`, `_http`, `_base`) moved OUT of `whatsapp_cloud.py` verbatim; `whatsapp_cloud.py` re-imports them so its behaviour is byte-identical |
| Adapter registry | `modules/omnichannel/adapters/__init__.py` | `ADAPTERS = {"WHATSAPP": ..., "FACEBOOK": ..., "INSTAGRAM": ...}` + `get_adapter(type, client=None, recorder=None)`; `whatsapp_cloud.get_adapter` becomes a thin re-export so the eight existing import sites do not churn (D-A7-7) |
| Messenger adapter | `modules/omnichannel/adapters/messenger.py` (new) | `channel_type = "FACEBOOK"`; `parse_inbound` over `entry[].messaging[]`; `send`; `upload_attachment`; `fetch_media_url`; `list_pages`; `subscribe_page`; `test_connection`; dev-stubbed throughout |
| Instagram adapter | `modules/omnichannel/adapters/instagram.py` (new) | subclasses the Messenger adapter; overrides `channel_type`, the `object` it accepts, the IG-only inbound kinds and `list_pages` (page -> linked IG account). Shared code inherited, never copied |
| Window policy | `modules/omnichannel/services/messaging_policy.py` (new) | `POLICIES: Dict[str, WindowPolicy]`, `CAPABILITIES: Dict[str, ChannelCapabilities]`, `authorize(...) -> SendDecision`, `stamp_inbound_window(...)`, `assert_kind_supported(...)`. The ONLY module that knows a window length |
| Addressing | `modules/omnichannel/services/channel_addressing.py` (new) | `sender_ref(channel)`, `recipient_ref(db, channel, contact) -> str` (raises `NoChannelIdentity`) |
| Connect service | `modules/omnichannel/services/meta_connect_service.py` (new) | code exchange, page / IG-account listing, connect-session create + consume + sweep, channel creation, `subscribed_apps` subscription |
| Connect sessions | `modules/omnichannel/models.py` `MetaConnectSession` | id, tenant_id, user_id, channel_type, credentials_json (Fernet), created_at, expires_at. Single-use, 5 minute TTL |
| Channel columns | `modules/omnichannel/models.py` `Channel` | `external_account_id` (indexed + partial unique among live rows), `external_account_name` |
| Identity columns | `modules/omnichannel/models.py` `ContactChannelIdentity` | `window_expires_at`, `human_agent_expires_at`, `last_inbound_at` (all `UTCDateTime`) |
| Migration | `modules/omnichannel/alembic/versions/0015_omni_meta_channels.py` | two channel columns + one partial unique index + three identity columns + one table + the WhatsApp window BACKFILL; inspector-guarded, Postgres-only, no-op under pytest; mirrored by `ADD COLUMN IF NOT EXISTS` in `create_schema_and_tables`. **Re-check the head + manifest version at branch time** (section 8, F1) |
| Webhook dispatch | `modules/omnichannel/services/inbound_service.py` | `_resolve_channel` gains the `object` switch; `_store_media` gains the URL branch; `_handle_watermark` (new) for Messenger receipts. Everything else untouched |
| Send path | `modules/omnichannel/services/message_service.py`, `send_runner.py` | five CSW branches -> one `messaging_policy.authorize` call; `run_send` uses `channel_addressing` + the persisted `metaSend` params. No second path |
| Onboarding routes | `modules/omnichannel/routers/onboarding.py` | `POST /meta/pages`, `POST /meta/connect` (both `channels.manage`). The WhatsApp `oauth-callback` + `manual-connect` routes are untouched |
| Schemas | `modules/omnichannel/schemas.py` | `ChannelItem` += `externalAccountId`, `externalAccountName`; `MetaPagesRequest/Response`, `MetaConnectRequest`, `MetaPageOption` |
| Gateway | `modules/omnichannel/services/public_gateway_service.py`, `routers/api_v1.py` | `_workspace_channel` prefers WHATSAPP + optional explicit selector; `to` gains `psid:` / `igsid:` / `id:` prefixes; new error code |
| **Guide** | `documentation/omnichannel/consumer-integration-guide.md` | changelog row + channel-selection rule + `to` prefixes + error code + widened `channelType`. **Same slice as the gateway diff - non-negotiable** |
| Workflow | `modules/omnichannel/workflow_nodes.py` | trigger gains an optional `channelType` filter field + the payload carries `channelType` |
| Dev seed | `modules/omnichannel/bootstrap.py` `seed_demo_conversations` | one sandbox Messenger channel + one sandbox Instagram channel, two threads each |
| Manifest | `modules/omnichannel/manifest.json` | version bump only (no new router entry - both new routes hang off the existing `onboarding` prefix). NO new permission key |

Reused unchanged: `routers/webhooks.py` (signature, cap, fast-ACK), `worker.py`, `security.py`
(Fernet), `services/realtime.py`, `services/webhook_delivery.py`, `services/event_service.py`,
`services/lifecycle_service.py`, `services/storage.py` + core `storage_for_tenant`,
`services/activity.py` (the Graph recorder), `services/structured.py`, `app/jobs/*`.

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Capability record | `service_frontend/lib/channel-capabilities.ts` (new) - per `ChannelType`: label, icon, window hours, human-agent hours, and the sendable kinds. Parity-pinned to `messaging_policy.CAPABILITIES` by a golden test |
| Types | `types/omnichannel.ts` - `ChannelType` pruned to `'WHATSAPP' \| 'FACEBOOK' \| 'INSTAGRAM'`; `Channel` += `externalAccountId`, `externalAccountName`; `MetaPageOption`; `ConnectChannelInput` gains `channelType` |
| Connect wizard | `components/platform/channel-connect-wizard/channel-connect-wizard.tsx` - a channel-type step and a page-selection step added to the EXISTING state machine; both pickers are `SearchSelect`; the two bare `<Select>` usages are replaced in the same pass |
| Simulated dialog | `components/platform/channel-connect-wizard/mock-embedded-signup-dialog.tsx` - extended with a `channelType` prop driving a type-aware option list |
| Connect hook | `hooks/use-connect-channel.ts` - states `selecting-type -> authorizing -> picking-page -> exchanging -> connected \| failed`; the WhatsApp path keeps its exact current transitions |
| Signup helper | `lib/embedded-signup.ts` - `launchEmbeddedSignup(product)` picks the config id per product; ONE popup implementation |
| Channel list | `app/(protected)/omnichannel/settings/channels/components/use-channels-list-config.tsx` - a Type column (`StatusBadge`-style registry in a new `channel-type.ts`) + a Type filter |
| Channel form | `.../components/use-channel-form.tsx` - filter Templates + Profile out of the `tabs` array for non-WhatsApp; `channel-form-fields.tsx` renders the page / account identity block by type |
| Composer | `components/platform/conversation-drawer/composer.tsx` - new `capabilities` prop (defaulted to the WhatsApp record) gating affordances; the CSW banner becomes the neutral window marker for non-WhatsApp types |
| Drawer | `components/platform/conversation-drawer/conversation-drawer.tsx` - window state derived from the thread's channel type through the capability record instead of the hardcoded `cswExpiresAt` boolean |
| Channel icons | `app/(protected)/omnichannel/contacts/components/contact-channels-cell.tsx` + `inbox/components/thread-list.tsx` - a shared type-to-icon lookup from `channel-capabilities.ts` |
| Services | `services/onboarding-service.{ts,mock,real}.ts` (existing trio) += `listMetaPages`, `connectMetaChannel` |
| Workflow catalog | `lib/workflow-catalog.ts` - the trigger gains a `channelType` field of a new `omnichannelChannelType` drawer type |

Reused unchanged: `components/platform/{resource-list,resource-form,search-select,status-badge,
overflow-pills,clamped-text}`, `hooks/use-can.ts`, `hooks/use-datetime.ts`.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A7-1 | Messenger and Instagram use the SAME Meta app and the SAME `META_APP_ID` / `META_APP_SECRET` / `META_GRAPH_VERSION` settings as WhatsApp. No `connections` row. Only the OAuth **config id** is per product (`META_MESSENGER_ES_CONFIG_ID`, `META_INSTAGRAM_ES_CONFIG_ID`, each falling back to `META_ES_CONFIG_ID`) | These are three products of one Meta app, not three integrations. A `connections` row would fork the credential model, the Fernet path and the dev-safe rule for no gain. Per-CHANNEL credentials stay exactly where they are: the page access token, Fernet-encrypted in `channels.credentials_json` |
| D-A7-2 | ONE webhook ingress. Meta's three product callbacks all point at `POST /omnichannel/webhooks/meta`; `InboundService._resolve_channel` dispatches on the payload's `object` field before falling back to the URL's channel id | Meta already fans every number of every tenant into one app-level callback - that is exactly why `_resolve_channel` prefers `metadata.phone_number_id` today. The URL id is decorative; making the payload authoritative for all three products is the same lesson applied once. `meta` is not a valid uuid, so the existing `{channel_id}` route captures it with zero new routes and zero manifest change, and every already-configured per-channel URL keeps working |
| D-A7-3 | `channels.external_account_id` (PAGE_ID / IG account id) is the routing key, indexed, with a PARTIAL UNIQUE index over live rows | Byte-for-byte the `phone_number_id` design from migration `0002`: O(1) inbound routing and a race-proof "this page is already connected" backstop behind the service-level 409 |
| D-A7-4 | **No cross-channel contact auto-merge.** A PSID or IGSID inbound with no identity creates a NEW contact; the phone stitch runs ONLY for phone-bearing channel types and only with a non-empty digit string | A PSID carries no phone, no email and no stable name. Merging on a display name would silently fuse two customers - unrecoverable data corruption on a shared inbox. The existing `find_by_phone_in_workspace(digits, ...)` with an empty `digits` would match phone-less contacts, so the guard is mandatory, not defensive. Manual merge is B2 / G24 (BL-SS-156) |
| D-A7-5 | The messaging window becomes a per-channel-type **policy** (`messaging_policy.POLICIES`) and the window instant moves to `contact_channel_identities` (`window_expires_at`, `human_agent_expires_at`, `last_inbound_at`); `contacts.csw_expires_at` keeps being dual-written for WhatsApp | One contact can now be reachable on three channels with three independent windows - a single column on the contact cannot express that. But `cswExpiresAt` is a DOCUMENTED gateway field (guide section 9.1 and 9.2) and the composer reads it, so it must not change meaning. Dual write is the only option that is both correct and non-breaking |
| D-A7-6 | Outside the 24h window, Messenger and Instagram allow a **human agent** to reply for 7 days under the `HUMAN_AGENT` tag; an AUTOMATED send (workflow action, public gateway, broadcast) is REJECTED outside 24h | Meta's policy is explicit that the human-agent tag is for a human answering a support conversation and must not be used by automation; misuse is detected and penalized. Encoding it as `actor_is_human = bool(actor_user_id or external_agent_id)` puts the compliance rule in the one place that can enforce it rather than in a reviewer's memory |
| D-A7-7 | NO message tags other than `HUMAN_AGENT`, and no one-time notifications / sponsored messages / recurring notifications | They are approval-gated, policy-risky, unavailable on Instagram, and Meta has been retiring the tag set. The customer's migration need is a shared inbox, not outbound marketing on Messenger. BL-SS-157 |
| D-A7-8 | The send decision (`messagingType`, `tag`) is computed at ENQUEUE and PERSISTED on the message row; `send_runner` uses it verbatim and never re-derives it | The window is time-dependent and the worker runs later. Re-deriving would let a message authorized inside the window get rejected (or, worse, silently re-tagged) by the worker. It also matches today's WhatsApp semantics exactly: the CSW is checked once, at enqueue |
| D-A7-9 | `get_adapter` moves into an `adapters/__init__.py` REGISTRY; `adapters.whatsapp_cloud.get_adapter` stays as a thin re-export | Eight modules import it from `whatsapp_cloud`. Rewriting those imports inside a slice that is already refactoring the send path is pure risk for zero behaviour. The re-export is one line and the follow-up import sweep is BL-SS-158 |
| D-A7-10 | Composer capabilities are a **parity-pinned pair**: `messaging_policy.CAPABILITIES` (authoritative, enforced server-side) and `lib/channel-capabilities.ts` (UX), locked by a golden test. NOT a new wire field | Adding a `capabilities` object to `ThreadItem` would extend the public gateway contract forever for a purely presentational need. The house already solves this twice (`verticals.py` / `lib/whatsapp-verticals.ts`, `template_schemas.py` / `lib/whatsapp-template.ts`) |
| D-A7-11 | Outbound media on Messenger / Instagram uses Meta's **attachment upload** endpoint (upload by id), never a public URL for Meta to fetch | The Send API accepts `payload.url`, which would mean minting a public link to a tenant's private media and putting it in Meta's logs. Upload-by-id is also exactly the contract `send_runner` already implements for WhatsApp, so the media branch generalizes instead of forking |
| D-A7-12 | INBOUND attachments arrive as a short-lived CDN URL, so the adapter protocol gains `fetch_media_url(credentials, url)` beside `fetch_media(credentials, media_id)`; the URL is validated (HTTPS, Meta CDN host allowlist, the shared SSRF host guard, capped read, bounded redirects) before any fetch | A URL taken from a payload and fetched server-side is an SSRF primitive. The payload is signature-verified, which makes forgery hard but not the security boundary - the house rule from `webhook_delivery.assert_deliverable` is "re-validate before every delivery", and the same applies to every fetch |
| D-A7-13 | A structured INTERACTIVE (button) message maps onto Meta **quick replies** for Messenger / Instagram, reusing the existing `structured.py` definition; LIST, LOCATION and CONTACTS are refused for those types at the service layer | The composer already produces button definitions; a second authoring surface for the same concept would be a parallel component. Refusing at the service layer (not only hiding in the UI) is what makes the frontend gating honestly "UX only" |
| D-A7-14 | Instagram v1 supports ONLY the Facebook-Page-linked topology (page access token, page-linked messaging endpoint). Instagram Login / IG-direct is out of scope | It is one OAuth, one token type and one adapter family, which is exactly why Instagram can be a small slice on top of Messenger. IG-direct is a second credential model. BL-SS-159 |
| D-A7-15 | The connect flow is TWO calls (`/meta/pages` then `/meta/connect`) with a short-lived, single-use, tenant-and-user-bound **connect session** holding the exchanged token Fernet-encrypted server-side | The user must choose a page, and an OAuth code is single-use, so the token has to survive between the two calls. It must never reach the browser. A 5 minute single-use row that is consumed on connect and swept on every `/pages` call is the smallest honest mechanism |
| D-A7-16 | NO new permission keys. `channels.read` / `channels.manage` / `conversations.*` cover everything | A new channel type is not a new resource. This also means no grant sweep and no silent 403 for existing tenants - the cheapest possible answer to DoD gate item 4 |
| D-A7-17 | Templates and Business Profile are refused with a typed 409 on non-WhatsApp channels (server) and their tabs are filtered out (client) | Foolproof-UI: a tab that can only fail is worse than an absent tab. The server refusal keeps the API honest for the gateway and for scripts |
| D-A7-18 | The public gateway's implicit channel choice PREFERS `WHATSAPP`, then falls back to the oldest active channel; an explicit selector is optional and a bad one is a typed error, never a silent fallback | `_workspace_channel` currently returns the oldest active channel. The moment a tenant connects a Messenger channel that could silently re-point every existing consumer's sends. Preference-for-WhatsApp makes the upgrade a no-op for every deployed integration, which is the whole point of the guide being a contract |
| D-A7-19 | `csw_window_closed` keeps its exact meaning (WhatsApp) and Messenger / Instagram refusals get a NEW code | Never redefine a documented error code. A consumer branching on `csw_window_closed` to send a template would do exactly the wrong thing on a Messenger refusal |
| D-A7-20 | The `ChannelType` frontend union is PRUNED to the three implemented types (`DOUYIN` / `XIAOHONGSHU` are removed) | They were aspirational placeholders with no adapter, no policy row and no capability record. Leaving them lets a future picker offer a type that cannot send. Foolproof-UI |
| D-A7-21 | Broadcasts (A4) are unchanged and remain WhatsApp-template-only; a phone-less Messenger contact simply resolves as `skipped/no_identity` for a WhatsApp broadcast | A4 resolves recipients through `contact_channel_identities` on the CHOSEN channel, so it is already channel-correct. Messenger broadcasts would need Meta's tag policy, which D-A7-7 rules out. BL-SS-160 |
| D-A7-22 | Messenger delivery / read receipts are applied by `mids[]` when present and otherwise by the **watermark** timestamp over that thread's outbound rows; receipts still only ever move forward | Meta's receipts are watermark-based, not per-message. Ignoring the watermark would leave every Messenger message stuck at `SENT` forever; applying it naively backwards would let a late `SENT` overwrite a `READ`, which the existing `_STATUS_RANK` guard already prevents and this slice must keep |
| D-A7-23 | `message_echoes` is NOT subscribed, and an echo that arrives anyway is dropped in the parser | An echo of our own send would create a duplicate inbound bubble and a spurious workflow trigger. Dropping it in the parser (not downstream) means no other layer has to know echoes exist |
| D-A7-24 | Meta rate-limit / throttling errors are classified TRANSIENT so the existing bounded backoff handles them; no new limiter in A7a | `send_runner` already distinguishes transient from permanent and `Channel.broadcast_rate_per_second` (A4) is the per-channel pacing knob if pacing is ever needed. A per-channel token bucket is already BL-SS-082 |

## 4. Slices (build order)

Each slice is sized for ONE Sonnet coder in the `s32` lane, sequential on the same branch.
Thinnest end-to-end first: Messenger text in and out before Instagram, before media and receipts.

| Slice | Content | Size | ACs |
|---|---|---|---|
| **S0 FE mock** | `ChannelType` prune, `lib/channel-capabilities.ts`, wizard channel-type + page-selection steps (both `SearchSelect`, replacing the two bare `<Select>`), simulated dialog extension, connect-hook states, channel list Type column + filter, channel form tab filtering, composer `capabilities` prop + the three window states, channel-type icons in the thread list and contacts cell, `onboarding-service` mock, vitest, agent-browser smoke at 375 + 1280 | L | 01-12 |
| **S1 BE Messenger inbound** | `meta_graph.py` extraction (pure move, WhatsApp behaviour byte-identical), adapter registry, `MessengerAdapter.parse_inbound` (+ echo drop), model columns + migration `0015` + the WhatsApp window backfill, `create_schema_and_tables` mirrors, webhook `object` dispatch, PSID stitch + the no-phone-stitch guard, `messaging_policy.stamp_inbound_window`, pytest | L | 13-21 |
| **S2 BE outbound + window policy** | `messaging_policy` (POLICIES, CAPABILITIES, `authorize`, `assert_kind_supported`), the five CSW call sites collapsed to one, persisted `metaSend` params, `channel_addressing`, `send_runner` generalization, `MessengerAdapter.send` (text, quick replies, reply-to), human-agent rule, dev stubs, pytest | L | 22-31 |
| **S3 BE connect flow** | `MetaConnectSession`, `/onboarding/meta/pages` + `/meta/connect`, page uniqueness 409 + partial unique index, `subscribed_apps` subscription, `ChannelItem` fields, non-WhatsApp 409s for templates / profile, type-aware `test_connection`, dev seed `chn-demo-fb`, manifest bump, pytest | M | 32-39 |
| **S4 BE Instagram** | `InstagramAdapter` (subclass), `object: instagram` dispatch, IG-only inbound kinds as `UNSUPPORTED` placeholders, IG capability + policy rows, page-linked IG account listing, IGSID stitch, dev seed `chn-demo-ig`, pytest | M | 40-45 |
| **S5 BE media, receipts, reactions** | `fetch_media_url` + URL allowlist / SSRF guard / cap, attachment upload-by-id outbound, `message_deliveries` / `message_reads` watermark + mids mapping, `message_reactions` onto the existing reaction path, transient classification of rate-limit errors, Graph telemetry rows, pytest | M | 46-52 |
| **S6 Gateway, guide, workflow, wire-up, E2E** | gateway channel preference + optional selector, `to` prefixes, new error code, **the consumer-guide diff**, workflow trigger `channelType` filter (backend + catalog), mock-to-real swap at the one service boundary, vitest completion, recorded agent-browser evidence at 375 + 1280, Test Execution Report | M | 53-63 |
| **Review** | `reviewer` agent on **Opus** (external ingest, a new webhook surface, an SSRF fetch path, a compliance rule encoded in code, a public gateway contract change) then `/codex-review` | - | - |

S1 and S2 are the load-bearing ones. If S2 needs splitting: **S2a** = `messaging_policy` + the five
call sites + persisted params (ACs 22-25), **S2b** = addressing + adapter send + quick replies +
dev stubs (ACs 26-31).

## 5. Contracts

### 5.1 Internal API (camelCase; datetimes Z-suffixed via `ApiModel`)

```
POST /omnichannel/onboarding/meta/pages                                   channels.manage
       { channelType: 'FACEBOOK'|'INSTAGRAM', code, redirectUri? }
       -> { sessionId, expiresAt, pages: MetaPageOption[] }
POST /omnichannel/onboarding/meta/connect                                 channels.manage
       { sessionId, workspaceId, channelType, pageId, igAccountId? }
       -> 201 ChannelItem     409 external_account_in_use | 400 connect_session_expired

(unchanged) POST /omnichannel/onboarding/oauth-callback, /manual-connect  (WhatsApp)
(unchanged) GET/PATCH /omnichannel/channels...,  POST .../test-connection
(refused 409 channel_type_unsupported on FACEBOOK/INSTAGRAM)
            GET/POST /omnichannel/channels/{id}/templates..., .../profile
```

```
MetaPageOption = { id, name, connected: boolean,
                   igAccountId?: string, igUsername?: string }
ChannelItem   += { externalAccountId: string|null, externalAccountName: string|null }
```

Typed 409 reasons: `external_account_in_use`, `channel_type_unsupported`.
Typed 400: `connect_session_expired`, `connect_session_consumed`.
422 bodies keep the house `{fieldErrors: {path: message}}` shape.

### 5.2 Public gateway diff (guide MUST change in the same slice - AC-CHN-57)

```
POST /api/v1/omnichannel/messages
  body += channelId?: string          (optional; must be an ACTIVE channel of THIS workspace)
  to    : "+60123456789"              unchanged - a bare value is still a phone
        | "phone:+60123456789"        unchanged
        | "id:<contactId>"            NEW
        | "psid:<PSID>"               NEW - resolves an EXISTING identity only
        | "igsid:<IGSID>"             NEW - resolves an EXISTING identity only

implicit channel choice: prefer an ACTIVE WHATSAPP channel, else the oldest ACTIVE channel
new error code: messaging_window_closed        409   (Messenger / Instagram)
kept verbatim : csw_window_closed              409   (WhatsApp only, unchanged meaning)
new error code: channel_not_available_for_contact 422 (no identity on the chosen channel)
read shapes   : channelType now also carries FACEBOOK | INSTAGRAM on BOTH shapes.
                No field added, renamed or dropped. One data path, as today.
```

Guide edits: a changelog row dated at merge; section 2 "a workspace must have one active channel"
becomes the preference rule; section 4 documents `channelId` and the `to` prefixes; section 9
notes the widened `channelType` vocabulary on both shapes; section 10 adds the two new codes.

### 5.3 Tables and columns

```
channels                += external_account_id   String NULL, index
                                                  + PARTIAL UNIQUE (external_account_id)
                                                    WHERE external_account_id IS NOT NULL
                                                      AND is_trashed = false
                        += external_account_name String NULL

contact_channel_identities
                        += window_expires_at        UTCDateTime NULL
                        += human_agent_expires_at   UTCDateTime NULL
                        += last_inbound_at          UTCDateTime NULL

meta_connect_sessions(  id pk, tenant_id idx, user_id, channel_type,
                        credentials_json Text (Fernet), created_at, expires_at idx )
```

Backfill (AC-CHN-14), in the migration, Postgres only, batched:
`UPDATE contact_channel_identities i SET window_expires_at = c.csw_expires_at,
 last_inbound_at = c.last_incoming_message_at FROM contacts c, channels ch
 WHERE i.contact_id = c.id AND i.channel_id = ch.id AND ch.channel_type = 'WHATSAPP'
 AND i.window_expires_at IS NULL`.

### 5.4 The window policy

```python
@dataclass(frozen=True)
class WindowPolicy:
    channel_type: str
    window_hours: int                    # standard messaging window
    human_agent_hours: Optional[int]     # None = no human-agent extension
    reengage_mode: str                   # "template" (WhatsApp) | "human_agent" | "none"

POLICIES = {
  "WHATSAPP":  WindowPolicy("WHATSAPP",  24, None, "template"),
  "FACEBOOK":  WindowPolicy("FACEBOOK",  24, 168,  "human_agent"),
  "INSTAGRAM": WindowPolicy("INSTAGRAM", 24, 168,  "human_agent"),
}

authorize(db, contact, channel, *, kind, actor_is_human, now) -> SendDecision
  SendDecision = { allowed, messaging_type, tag, reason }
  WHATSAPP  : kind == TEMPLATE                      -> allowed, no Meta send params
              inside window                          -> allowed
              else                                   -> refused, CSW_CLOSED_MESSAGE (verbatim)
  FACEBOOK / INSTAGRAM
            : inside window                          -> allowed, messaging_type=RESPONSE
              inside human-agent window AND human    -> allowed, messaging_type=MESSAGE_TAG,
                                                        tag=HUMAN_AGENT
              inside human-agent window AND NOT human-> refused, automation_outside_window
              else                                   -> refused, messaging_window_closed
```

`messaging_type` / `tag` enum spellings are pinned against the live Graph version at
implementation time (section 7, R5) and asserted by one adapter test - the documentation pages
render them inconsistently.

`actor_is_human = bool(actor_user_id or external_agent_id)`. The workflow action, the public
gateway and any future broadcast pass neither, so they are automation by construction.

### 5.5 Capability table (backend authoritative, frontend parity-pinned)

| Capability | WHATSAPP | FACEBOOK | INSTAGRAM |
|---|---|---|---|
| text | yes | yes | yes |
| image / video / audio | yes | yes | yes |
| voice note | yes | as audio | as audio |
| document / file | yes | yes | **no** |
| sticker (outbound) | yes | no | no |
| template | yes | no | no |
| interactive buttons | yes (3) | as quick replies (13) | as quick replies (13) |
| interactive list | yes | no | no |
| location | yes | no | no |
| contacts | yes | no | no |
| reaction (outbound) | yes | no | no |
| reaction (inbound) | yes | yes | yes |
| reply to a message | yes | yes | yes |

### 5.6 Inbound event mapping (Messenger / Instagram -> the existing canonical events)

```
entry[].messaging[]
  message.text                            -> kind=message, message_type=TEXT
  message.attachments[image|video|audio]  -> IMAGE | VIDEO | AUDIO      (+ media_url)
  message.attachments[file]               -> DOCUMENT                   (Messenger only)
  message.quick_reply.payload             -> INTERACTIVE_REPLY, payload {kind:'quick_reply',id,title}
  postback.payload                        -> INTERACTIVE_REPLY, payload {kind:'postback',id,title}
  message.reply_to.mid                    -> reply_to_external_id
  message.is_echo == true                 -> NO EVENT (dropped in the parser, D-A7-23)
  reaction {action: react|unreact}        -> kind=reaction (the existing path)
  delivery {mids?, watermark}             -> kind=status, status=DELIVERED  (+ watermark)
  read {watermark}                        -> kind=status, status=READ       (+ watermark)
  IG story_reply | story_mention | share  -> UNSUPPORTED placeholder, payload preserved
  anything else                           -> UNSUPPORTED placeholder
sender.id  = PSID | IGSID  -> contact_channel_identities.external_user_id
entry[].id = PAGE_ID | IG account id -> channels.external_account_id
```

### 5.7 Seams touched in existing files

See section 6 for the pinned `file:line`. The behaviour contract per file:

| File | Change | Invariant that must survive |
|---|---|---|
| `adapters/whatsapp_cloud.py` | shared plumbing moved out and re-imported; `get_adapter` becomes a re-export | its existing tests pass with NO edits |
| `services/inbound_service.py` | `_resolve_channel` object switch; `_store_media` URL branch; `_handle_watermark`; window stamping | a broken new branch never drops a WhatsApp message; the workflow-trigger dispatch stays inside its own try / except |
| `services/message_service.py` | five window guards -> one `authorize` call; `metaSend` persisted | the WhatsApp rejection message and template exemption are byte-identical |
| `services/send_runner.py` | addressing helper + persisted send params | the QUEUED -> SENDING claim, the transient / permanent split and the double-send guard are untouched |
| `services/public_gateway_service.py` | channel preference + `to` prefixes + new codes | both read shapes stay lossless and derived from the same internal objects |
| `routers/webhooks.py` | **no change** | signature, cap and fast-ACK unchanged - the dispatch lives in the service |
| `bootstrap.py` | `create_schema_and_tables` column mirrors; `seed_demo_conversations` extra channels | `install_tenant` / `update_tenant` stay idempotent and self-healing |
| `workflow_nodes.py` + `lib/workflow-catalog.ts` | one optional trigger field | **rebase onto plan 31 first** (section 7, R1) |
| `documentation/omnichannel/consumer-integration-guide.md` | the section 5.2 diff | changed in the SAME commit range as `api_v1.py` |

## 6. Seam paths verified at `c25a97ff` (origin/main)

Backend (`service_backend/modules/omnichannel/`):

- `adapters/base.py:33` `ChannelAdapter` Protocol, `:53` `send(credentials, phone_number_id, to, ...)`,
  `:20` `SendError(transient=)`
- `adapters/whatsapp_cloud.py:24` `GraphCall`, `:45` `_meta_error_detail`, `:68` class, `:69`
  `channel_type = "WHATSAPP"`, `:82` `self._base`, `:84` `_graph_call`, `:136` `_configured`,
  `:139` `_http`, `:290` `upload_media`, `:328` `send`, `:365` `_send_impl`, `:699` `fetch_media`,
  `:720` `parse_inbound`, `:875` `test_connection`, `:903` `get_adapter` (WhatsApp only, raises
  otherwise)
- `routers/webhooks.py:24` `verify_handshake`, `:37` `_signature_valid` (fail-open only in
  development with no secret), `:54` `receive_webhook` (1MB cap, fast-ACK)
- `services/inbound_service.py:28` `_payload_phone_number_id`, `:44` `_STATUS_RANK`, `:53`
  `process_payload`, `:74` `get_adapter(channel.channel_type)`, `:103` `_resolve_channel`, `:121`
  `_handle_message`, `:198` CSW re-open block, `:213` `csw_expires_at = now + CSW_WINDOW`, `:293`
  `_handle_reaction`, `:337` `_resolve_contact`, `:349` `digits_only(wa_id)` + phone stitch, `:380`
  identity insert, `:392` `_store_media`, `:422` `_handle_status`
- `services/message_service.py:64` `CSW_CLOSED_MESSAGE`, `:75` `_window_open`, `:166`
  `_channel_for_contact`, `:278` `send_message`, `:382` / `:442` / `:506` / `:567` / `:679` the five
  window guards, `:697` `adapter.send(credentials, channel.phone_number_id or "", digits...)`,
  `:832` `_sync_templates`
- `services/send_runner.py:94` `run_send`, `:121` the not-QUEUED no-op, `:149` the SENDING claim,
  `:179` `get_adapter(channel.channel_type, recorder=...)`, `:183` `phone_id`, `:184` `to`, `:188`
  the TEMPLATE / media / structured / text branches, `:270` transient vs permanent
- `services/channel_service.py:43` `_items`, `:126` `test_connection`, `:156` `remove` (detaches
  identities and templates)
- `services/onboarding_service.py:48` `_assert_phone_available` (deliberately NOT tenant-scoped),
  `:66` `_persist_channel` (IntegrityError -> 409), `:80` `complete`, `:145` `manual_connect`
- `services/public_gateway_service.py:106` `_workspace_channel` (oldest active), `:125`
  `_resolve_contact` (`phone:` / `id:` / bare), `:509` `_resolve_or_create_contact` (phone only,
  `422 invalid_recipient`)
- `models.py:99` `Channel`, `:105` `channel_type` (plain String, default WHATSAPP, no enum), `:112`
  `phone_number_id` (partial unique via migration `0002`), `:138` `Contact`, `:149` `phone`, `:156`
  `phone_digits`, `:181` `csw_expires_at`, `:182` `last_incoming_message_at`, `:198`
  `ContactChannelIdentity`, `:205` `external_user_id`, `:209` `UNIQUE(channel_id, external_user_id)`
- `bootstrap.py:54` `register_engine_entities`, `:111` `create_schema_and_tables` (the
  `ADD COLUMN IF NOT EXISTS` block), `:414` `install`, `:424` `install_tenant`, `:469`
  `update_tenant`, `:527` `uninstall_tenant`, `:560` `seed_demo_conversations`
- `worker.py:34` `process_inbound_webhook`, `:55` `omnichannel_send_message`
- `workflow_nodes.py:116` `register_omnichannel_workflow_nodes`, `:119` the
  `omnichannel.message_received` trigger, `:131` the `channelId` field
- `schemas.py:85` `ChannelItem`, `:145` `ChannelUpdate`, `:157` `OnboardingCallbackRequest`, `:174`
  `ManualConnectRequest`
- `manifest.json` version `0.4.0`; alembic head `alembic/versions/0010_omni_contacts_module.py`
- `permissions/permissions.csv` - `channels.read` / `channels.manage` / `conversations.*` already
  present; A7a adds no row

Frontend (`service_frontend/`):

- `types/omnichannel.ts:14` `ChannelType` (already carries `FACEBOOK` / `INSTAGRAM` plus two
  unimplemented values), `:56` `Channel`, `:223` `channelType` on the thread, `:225` `cswExpiresAt`
- `components/platform/channel-connect-wizard/channel-connect-wizard.tsx:53` component, `:76`
  `configured`, `:135` the simulated-popup branch, `:219` and `:281` the two bare `<Select>` usages
  this slice replaces with `SearchSelect`
- `components/platform/channel-connect-wizard/mock-embedded-signup-dialog.tsx`
- `lib/embedded-signup.ts:36` `isEmbeddedSignupConfigured`, `:59` `launchEmbeddedSignup` (the
  self-hosted redirect popup, NOT `FB.login`)
- `hooks/use-connect-channel.ts:48` the wizard state machine
- `components/platform/conversation-drawer/composer.tsx:85` `windowOpen` prop, `:357` `locked`,
  `:499` the CSW banner, `:505` the "Choose template" affordance
- `components/platform/conversation-drawer/conversation-drawer.tsx:223` the `windowOpen` derivation
- `app/(protected)/omnichannel/settings/channels/components/use-channel-form.tsx:163` the `tabs`
  array (Configuration / Templates / Profile + the conditional Webhooks tab)
- `app/(protected)/omnichannel/contacts/components/contact-channels-cell.tsx:1` the hardcoded
  `MessageCircle` icon
- `lib/workflow-catalog.ts:149` the `omnichannel.message_received` entry, `:155` its `channelId`
  field

Cross-lane state read on 2026-09-06: `s28` (teams) and `s29` (broadcasts) BOTH took module Alembic
`0011` and manifest `0.5.0`; `s31` (workflow parity) took `0013` + `0014` and manifest `0.4.5`;
`s30` (dashboard / reports) took no migration. A7a therefore plans `0015` and manifest `0.8.0` as
LABELS, not facts (section 8, F1).

## 7. Risks and mitigations

- **R1 - plan 31 owns the two files A7a needs.** `workflow_nodes.py` (+736 lines on `s31`) and
  `lib/workflow-catalog.ts` (+656) are rewritten there. A7a must branch AFTER plan 31 merges and add
  its one optional trigger field on top. If A7a must start earlier, S6's workflow item is deferred
  to a follow-up commit rather than merged into a conflict.
- **R2 - migration number and manifest version collide across five in-flight lanes.** The coder
  re-reads `modules/omnichannel/alembic/versions/` and `manifest.json` at branch time and takes the
  next free number and the next minor version. `update_tenant` gates must be `from_version <`
  comparisons, never equality (plan 27 D-A3-16).
- **R3 - the SSRF fetch path is the security-critical new surface.** An inbound attachment URL is
  fetched server-side. Mitigations: HTTPS only, a Meta CDN host allowlist, the shared
  `assert_deliverable` host guard, a capped read, bounded redirects, and a failure that skips the
  media rather than dropping the message. Tests assert both the pass and the fail branch.
- **R4 - the human-agent tag is a compliance rule, not a feature flag.** Meta detects and penalizes
  automated use. It is enforced in ONE place (`messaging_policy.authorize`) from a value the caller
  cannot spoof (the presence of an actor id), and a test asserts the workflow action and the public
  gateway are refused outside 24h.
- **R5 - Meta's own docs render the send enums inconsistently** (`messaging_type` appears as both
  `RESPONSE / UPDATE / MESSAGE_TAG` and as prose "Response / Updates / Tagged Message"). The coder
  pins the exact spellings against the deployed Graph version before S2 lands and encodes them as
  module constants with one adapter test.
- **R6 - a duplicated inbound bubble is the most visible possible bug.** Echo suppression is in the
  parser, and the existing wamid / mid idempotency check in `_handle_message` still guards the
  persist path.
- **R7 - the window column split can regress WhatsApp.** `contacts.csw_expires_at` keeps being
  written on every WhatsApp inbound (dual write) and the WhatsApp branch of `authorize` still reads
  the contact column, so `cswExpiresAt` on the wire and the composer lock are provably unchanged;
  the existing CSW tests run unedited as the proof.
- **R8 - "the workspace's active channel" is load-bearing for every deployed consumer.** Preference
  for WhatsApp plus an explicit optional selector keeps every existing integration byte-identical;
  a contract-drift test asserts the preference.
- **R9 - Instagram policy diverges from Messenger without notice.** The two are separate policy and
  capability rows precisely so a divergence is a one-row change, and the IG adapter subclasses
  rather than copies.
- **R10 - new columns on existing tables.** `create_all` never ALTERs, so every new column is
  mirrored in `create_schema_and_tables` with `ADD COLUMN IF NOT EXISTS` and the deploy path is
  `bootstrap_db`, never `init_db`.
- **R11 - a dev machine with `META_APP_ID` SET will hit Graph for real on a non-dev channel.** The
  E2E journey runs exclusively against the seeded sandbox channels (`chn-demo`, `chn-demo-fb`,
  `chn-demo-ig`), which carry `dev` credentials and are stubbed regardless of the environment.

## 8. Backlog candidates (registered as BL-SS-153..165)

| Id | Title | Priority |
|---|---|---|
| BL-SS-153 | Messenger / Instagram message templates (generic, button, receipt, media templates) as a first-class composer + workflow surface | Medium |
| BL-SS-154 | Persistent menu, ice breakers and greeting text per Messenger / Instagram channel (a Profile-tab equivalent for these types) | Medium |
| BL-SS-155 | Handover protocol (pass thread control to or from the Page inbox / another app) | Low |
| BL-SS-156 | Cross-channel contact merge: fuse a WhatsApp contact and a Messenger / Instagram contact into one profile, moving identities (pairs with G24 / B2) | High |
| BL-SS-157 | Message tags beyond `HUMAN_AGENT` (`CONFIRMED_EVENT_UPDATE`, `POST_PURCHASE_UPDATE`, `ACCOUNT_UPDATE`) and one-time notifications, if and when Meta's roadmap settles | Low |
| BL-SS-158 | Import sweep: point the eight `from ..adapters.whatsapp_cloud import get_adapter` sites at `adapters/__init__.py` and drop the re-export | Low |
| BL-SS-159 | Instagram Login (IG-direct, no linked Facebook Page) as a second connect topology | Medium |
| BL-SS-160 | Broadcasts on Messenger / Instagram once a compliant outbound mode exists (pairs with BL-SS-157) | Low |
| BL-SS-161 | Instagram story replies, story mentions and media shares as first-class message types instead of `UNSUPPORTED` placeholders | Medium |
| BL-SS-162 | Outbound reactions on Messenger / Instagram (inbound already lands on the existing reaction path) | Low |
| BL-SS-163 | Per-page rate-limit awareness (Meta's calls-per-page budget) surfaced in the channel Configuration tab, pairing with BL-SS-082 | Low |
| BL-SS-164 | A channel CATALOG screen (respond.io's card grid) once more than three types ship - A7a deliberately uses a `SearchSelect` step instead | Low |
| BL-SS-165 | `channel_type` as a DB-level enum plus a migration for the pruned `DOUYIN` / `XIAOHONGSHU` values, should any row ever carry them | Low |

## 9. Flagged for the user

- **F1 - the migration number and the manifest version are labels, not facts.** `0015` and `0.8.0`
  assume `s28`, `s29`, `s30` and `s31` all merge first, and `s28` + `s29` currently BOTH claim
  `0011` / `0.5.0`, so one of them will renumber anyway. The coder takes the next free values at
  branch time.
- **F2 - an AUTOMATED reply is refused on Messenger / Instagram once the 24h window closes
  (D-A7-6).** That is Meta's rule, not a product choice, and it means a workflow that answers late
  will fail the node rather than send. If the customer expects automated late replies, the honest
  answer is a template (BL-SS-153), not the human-agent tag.
- **F3 - no cross-channel merge (D-A7-4).** The same person on WhatsApp and on Messenger is two
  contacts until BL-SS-156 ships. This is visible in the Contacts list, in segments and in the
  dashboard counts. Flagging the consequence, not asking to change it - auto-merging is
  unrecoverable if wrong.
- **F4 - `contacts.csw_expires_at` is now a WhatsApp-only mirror (D-A7-5).** The gateway field
  `cswExpiresAt` keeps its documented meaning, which is deliberately NOT "the window on whatever
  channel this thread is on". A consumer reading it for a Messenger contact will see `null`. The
  guide says so explicitly after S6.
- **F5 - the connect wizard gains a `SearchSelect` step, not respond.io's card catalog** (BL-SS-164).
  With three implemented types a catalog grid would be a new surface for no user gain; it earns its
  place at seven or eight types.
- **F6 - `DOUYIN` and `XIAOHONGSHU` are removed from the frontend `ChannelType` union** (D-A7-20).
  They have no adapter and no capability record, so leaving them lets a picker offer a dead type. If
  any stored row somehow carries one it renders as an unknown type; BL-SS-165 covers the enum.
- **F7 - the E2E journey runs on seeded sandbox channels** (`chn-demo-fb`, `chn-demo-ig`), not on a
  freshly provisioned tenant: a new tenant has no channel and no threads, so the journey would not
  exist. Every created name is timestamped and the tenant-isolation probe still provisions its own
  tenant.
- **F8 - the shared-plumbing extraction touches the WhatsApp adapter.** It is a pure move and its
  existing tests must pass with zero edits; if a coder finds itself editing a WhatsApp test, the
  move stopped being pure and the slice should stop and re-plan.

## 10. Sources

- Messenger Platform webhooks (object `page`, `entry[].messaging[]`, subscribed fields,
  `X-Hub-Signature-256`): https://developers.facebook.com/docs/messenger-platform/webhooks
- Messenger Send API (`POST /{PAGE_ID}/messages`, `recipient.id`, `messaging_type`, `tag`,
  attachments, quick replies, response `message_id`):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- Messenger and Instagram messaging policy (24h standard messaging, the Human Agent 7-day window and
  its human-only restriction, tag availability differences on Instagram):
  https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
- Instagram messaging webhooks (object `instagram`, IGSID, subscribed fields):
  https://developers.facebook.com/docs/messenger-platform/instagram/features/webhook
- Instagram send (page-linked endpoint, supported media kinds, IGSID recipient):
  https://developers.facebook.com/docs/messenger-platform/instagram/features/send-message
- respond.io channel catalog (the parity target for the connect surface):
  `documentation/plans/sprint-4/24-evidence/respondio-survey/set-channels.png`
