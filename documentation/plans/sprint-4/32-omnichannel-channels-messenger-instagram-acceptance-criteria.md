# 32 - Omnichannel channel adapters: Facebook Messenger + Instagram DM - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/32-omnichannel-channels-messenger-instagram.md`.
> **Program:** slice **A7a** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G20,
> roadmap row A7, Q1 answered "all of them", order decided 2026-09-05: Messenger + Instagram first).
> **Depends on:** plan 25 / A1 and plan 26 / A2 merged (they are, at `c25a97ff`). Branch AFTER
> plan 31 / A5 merges - A7a edits `workflow_nodes.py` and `lib/workflow-catalog.ts`, which plan 31
> rewrites wholesale.
> **Out of scope (later slices / backlog):** Telegram (A7c), website chat (A7b), email (A7d), SMS
> (A7e), TikTok / Viber / LINE / WeChat, Messenger or Instagram message TEMPLATES (generic /
> product / receipt templates), Instagram Login (IG-direct, no linked Facebook Page), persistent
> menus, ice breakers, handover protocol, one-time notifications, sponsored messages, recurring
> notifications, message tags other than `HUMAN_AGENT`, outbound reactions on Messenger / Instagram,
> outbound stickers, cross-channel contact merge (B2 / G24), broadcasts on Messenger / Instagram
> (A4 is WhatsApp template only by construction).

IDs: `AC-CHN-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Channel type** - the value of `channels.channel_type`. After this slice the implemented
  vocabulary is exactly `WHATSAPP | FACEBOOK | INSTAGRAM`; nothing else is offered by any picker or
  accepted by any writer.
- **PSID** - a Page-Scoped ID: the opaque per-page identifier Messenger gives a person. **IGSID** -
  the Instagram-scoped ID. Both are stored verbatim in
  `contact_channel_identities.external_user_id`, which already carries the WhatsApp `wa_id`.
- **External account id** - `channels.external_account_id`: the Facebook PAGE_ID for a `FACEBOOK`
  channel and the Instagram professional account id for an `INSTAGRAM` channel. It is to
  Messenger / Instagram what `phone_number_id` is to WhatsApp: the routing key for inbound and the
  sender ref for outbound.
- **Messaging window** - the period during which a business may send a free-form message. WhatsApp
  calls it the customer service window (24h, re-engagement by approved template only). Messenger
  and Instagram call it standard messaging (24h from the person's last interaction), extendable to
  7 days by the `HUMAN_AGENT` tag for messages a HUMAN agent sends for support. In this slice all
  three are ONE per-channel-type policy object, never a hardcoded WhatsApp branch.
- **Window policy** - `services/messaging_policy.py`: the single place that answers "may this
  message be sent on this channel to this contact right now, and with what Meta send parameters".
- **Capabilities** - what a channel type can carry (text, media kinds, quick replies, reply-to,
  reactions, templates, location, contacts). Declared ONCE on the backend and mirrored by a
  parity-pinned frontend constant, the `verticals.py` / `lib/whatsapp-verticals.ts` precedent.
- **Send path** - the ONE `MessageService` enqueue plus the ONE `send_runner.run_send` dispatcher.
  This slice adds no second outbound path.
- **Dev-safe** - the existing rule `not settings.meta_app_id OR credentials.get("dev")`: every
  Graph call is stubbed, so the whole feature is exercisable, testable and demoable with no Meta
  app and no network.

---

## Slice S0 - Frontend on the mock service

- **AC-CHN-01 [FE]** Given the channel connect wizard is opened from Omnichannel > Settings >
  Channels, then its first step offers a **channel type** chosen from a `SearchSelect` listing
  exactly WhatsApp, Facebook Messenger and Instagram (foolproof-UI: no unimplemented type is ever
  offered), and the existing "Attach to workspace" control is also a `SearchSelect` (the bare
  shadcn `<Select>` at `channel-connect-wizard.tsx:219` / `:281` is replaced, not duplicated).
- **AC-CHN-02 [FE]** Given channel type Facebook Messenger or Instagram and a configured Meta app,
  then "Continue" launches the Meta OAuth popup through the EXISTING `lib/embedded-signup.ts`
  helper parameterized by product (no second popup implementation), and the wizard then shows a
  **page / account selection** step listing the connectable pages (Messenger) or the Instagram
  professional accounts linked to those pages (Instagram) in a `SearchSelect`; a page that is
  already connected to a live channel is not offered.
- **AC-CHN-03 [FE]** Given the Meta app is NOT configured (`NEXT_PUBLIC_META_APP_ID` unset), then
  the wizard falls back to the simulated dialog for Messenger and Instagram exactly as it does for
  WhatsApp today - the SAME `MockEmbeddedSignupDialog` extended with a type-aware option list, never
  a parallel dialog - and the created channel is labelled as a sandbox channel.
- **AC-CHN-04 [FE]** Given the Channels list, then a **Type** column renders a per-type badge with
  its own icon and label; the list, its filters and its actions are the unchanged Resource shell
  (no hand-rolled table), and the Type value is also offered as a list filter.
- **AC-CHN-05 [FE]** Given a `FACEBOOK` or `INSTAGRAM` channel's detail form, then the
  **Templates** and **Profile** tabs are absent (they are WhatsApp / WABA concepts) - filtered out
  of the existing `tabs` array in `use-channel-form.tsx:163` the same way `webhooks` already is -
  the **Configuration** tab shows the page or account identity block instead of the WABA block, and
  the **Webhooks** tab is unchanged.
- **AC-CHN-06 [FE]** Given `lib/channel-capabilities.ts`, then each channel type declares its
  capabilities and window hours in ONE exported record, and the conversation composer receives them
  through a new `capabilities` prop on the EXISTING `Composer` (default = the WhatsApp record, so
  every current caller is unchanged).
- **AC-CHN-07 [FE]** Given a Messenger or Instagram thread inside its messaging window, then the
  composer offers text, image, video, audio and (Messenger only) file attachments and quick replies,
  and does NOT offer template send, list messages, location, contacts, outbound reactions or
  (Instagram) file attachments - a control that cannot work is absent, never present-and-disabled
  with an explanation.
- **AC-CHN-08 [FE]** Given a Messenger or Instagram thread whose 24h window has closed but whose
  7-day human-agent window is still open, then the composer stays enabled for a human agent and the
  thread carries a neutral state marker; once the 7-day window has also closed the composer input
  and send control are disabled with the same neutral marker and NO instructional copy, and the
  WhatsApp "choose a template" affordance is NOT rendered (there are no templates on these types).
- **AC-CHN-09 [FE]** Given the thread list and the Contacts list Channels column, then a channel
  identity renders its own channel-type icon; `contact-channels-cell.tsx` is extended with a
  type-to-icon lookup rather than replaced, and `OverflowPills` still owns the truncation.
- **AC-CHN-10 [FE]** Given the mock service, then the whole surface is exercisable with no backend:
  connect wizard for all three types (success, already-connected 409, failure, cancel), a Messenger
  thread inside the window, one outside 24h but inside 7 days, one outside both, an Instagram
  thread, and a channel list mixing all three types.
- **AC-CHN-11 [FE]** Given `useCan()`, then the connect wizard and every channel write control
  require `channels.manage` and the list requires `channels.read` (this slice adds NO new permission
  key); a user without the key sees no control and the backend remains the real gate.
- **AC-CHN-12 [FE]** Given every new or changed surface (wizard steps, channel list, channel form
  tabs, composer states, thread list) at ~375px AND ~1280px, then nothing clips or overlaps, there
  is no horizontal page scroll, every action stays reachable, and no tenant-facing copy says
  "Dreamz" or "Foundryx" or teaches the user how to use the screen.

## Slice S1 - Backend: Messenger inbound (webhook, routing, stitch)

- **AC-CHN-13 [BE]** Given the module migration runs on Postgres, then `channels` gains
  `external_account_id` (indexed, plus a PARTIAL UNIQUE index over live rows mirroring the
  `phone_number_id` index from migration `0002`) and `external_account_name`, and
  `contact_channel_identities` gains `window_expires_at`, `human_agent_expires_at` and
  `last_inbound_at` (all `UTCDateTime`); the revision is inspector-guarded and idempotent, its id is
  <= 32 chars, it is a no-op under pytest, and `bootstrap.create_schema_and_tables` mirrors every
  new column with `ADD COLUMN IF NOT EXISTS` (because `create_all` never ALTERs an existing table).
- **AC-CHN-14 [BE]** Given tenants that already have WhatsApp identities, then the migration
  BACKFILLS `contact_channel_identities.window_expires_at` from `contacts.csw_expires_at` and
  `last_inbound_at` from `contacts.last_incoming_message_at` for every WhatsApp identity, so no
  pre-existing thread loses its open window; re-running the migration or `update_tenant` changes
  nothing further.
- **AC-CHN-15 [BE]** Given the adapter layer, then `get_adapter(channel_type)` resolves from a
  REGISTRY covering `WHATSAPP`, `FACEBOOK` and `INSTAGRAM` (an unknown type still raises), the Meta
  Graph plumbing shared by all three (`GraphCall`, the recorder, `_graph_call`, error extraction,
  `_configured`, the HTTP client) lives in ONE shared module, and the WhatsApp adapter's observable
  behaviour is byte-identical to `c25a97ff` (its existing tests pass unchanged).
- **AC-CHN-16 [BE]** Given a POST to `/omnichannel/webhooks/{anything}` carrying a valid
  `X-Hub-Signature-256`, then the channel is resolved by the payload's `object` field:
  `whatsapp_business_account` (or absent) keeps today's `metadata.phone_number_id` path, `page`
  resolves a live `FACEBOOK` channel by `external_account_id == entry[].id`, and `instagram`
  resolves a live `INSTAGRAM` channel the same way; the URL path id remains the last-resort
  fallback; an unresolvable payload is dropped with a log line and a 200, never a 5xx.
- **AC-CHN-17 [BE]** Given the same endpoint, then signature verification, the 1MB body cap, the
  fast-ACK-then-Celery contract and the `hub.challenge` handshake are unchanged and apply to all
  three products; a forged or unsigned Messenger payload is rejected 403 outside development.
- **AC-CHN-18 [BE]** Given a Messenger `messages` webhook, then the adapter normalizes
  `entry[].messaging[]` (NOT `entry[].changes[]`) into the existing canonical event dicts: text ->
  `TEXT`; an image / video / audio / file attachment -> `IMAGE` / `VIDEO` / `AUDIO` / `DOCUMENT`
  carrying the attachment URL; a `quick_reply` reply and a `messaging_postbacks` event ->
  `INTERACTIVE_REPLY` with `payload_json {kind, id, title}`; `message.reply_to.mid` ->
  `reply_to_external_id`; anything else -> the `UNSUPPORTED` placeholder that is stored, never
  dropped. A malformed payload yields zero events and never raises.
- **AC-CHN-19 [BE]** Given a Messenger event whose `message.is_echo` is true, then it produces NO
  event at all - our own outbound must never come back as a second inbound bubble - and the module
  does not subscribe to `message_echoes`.
- **AC-CHN-20 [BE]** Given an inbound Messenger message from a PSID with no existing identity, then
  a NEW contact is created in that channel's workspace with the PSID stored in
  `contact_channel_identities.external_user_id`, `phone` and `phone_digits` left NULL, the display
  name taken from the Graph user profile when available, the thread opened, the lifecycle initial
  stage stamped and an `opened` conversation event written - and the WhatsApp phone stitch is NOT
  attempted (an empty digits string must never match a phone-less contact). A second message from
  the same PSID reuses the same contact, and the same PSID on a DIFFERENT channel is a separate
  identity.
- **AC-CHN-21 [BE]** Given an inbound message on any channel type, then the identity's
  `window_expires_at` is set to now + the channel type's window, `human_agent_expires_at` to now +
  its human-agent window (null where the type has none), and `last_inbound_at` to now; for a
  WhatsApp channel `contacts.csw_expires_at` and `contacts.last_incoming_message_at` keep being
  written exactly as today (dual write - the gateway wire and the composer must not change
  meaning), and the thread reopen / `reopened` / `unsnoozed` event behaviour is unchanged for every
  type.

## Slice S2 - Backend: outbound send + the per-channel-type window policy

- **AC-CHN-22 [BE]** Given `services/messaging_policy.py`, then every channel type declares one
  policy row (window hours, human-agent window hours or none, re-engagement mode) and ONE function
  answers "can this send happen" - the five hardcoded `if not _window_open(contact): raise
  SendRejected(CSW_CLOSED_MESSAGE)` sites in `message_service.py` (`:382`, `:442`, `:506`, `:567`,
  `:679`) are replaced by a call to it, and a test asserts no `_window_open` call survives outside
  that module.
- **AC-CHN-23 [BE]** Given a WhatsApp send, then behaviour is IDENTICAL to `c25a97ff`: free-form
  inside 24h, outside it only an approved template, the same rejection message, and templates
  exempt from the window; the existing WhatsApp send / CSW tests pass unchanged.
- **AC-CHN-24 [BE]** Given a Messenger or Instagram send inside the 24h window, then it is
  authorized with `messaging_type = RESPONSE` and no tag; given a send outside 24h but inside 7 days
  BY A HUMAN AGENT (`actor_user_id` or `external_agent_id` present), then it is authorized with the
  `HUMAN_AGENT` tag; given the SAME send by an automation (a workflow action, the public gateway, a
  broadcast - no human actor), then it is REJECTED with a typed reason and nothing is enqueued;
  given a send outside 7 days, then it is rejected for everyone.
- **AC-CHN-25 [BE]** Given a send is authorized, then the resolved Meta send parameters
  (`messaging_type`, `tag`) are PERSISTED on the queued message row and used verbatim by
  `send_runner`; a message that ages past its window while queued still dispatches under the
  parameters it was authorized with, and the worker never re-derives the decision.
- **AC-CHN-26 [BE]** Given `send_runner.run_send`, then the recipient ref and the sender ref are
  resolved by ONE channel-addressing helper - WhatsApp keeps `digits(contact.phone)` and
  `channel.phone_number_id`; Messenger and Instagram use that contact's
  `contact_channel_identities.external_user_id` for THAT channel and `channel.external_account_id` -
  and a contact with no identity on the chosen channel fails the send cleanly with a typed reason
  rather than sending to an empty recipient. The QUEUED -> SENDING claim, the transient-vs-permanent
  split, the FAILED stamp and the realtime `message.status` publish are unchanged.
- **AC-CHN-27 [BE]** Given a Messenger or Instagram text send, then the adapter POSTs to
  `/{external_account_id}/messages` with `recipient.id`, `messaging_type`, optional `tag` and
  `message.text`, and maps the response `message_id` into `external_message_id`; a Meta 5xx or a
  transport error is `transient=True` (bounded retry) and a 4xx rejection is permanent with Meta's
  own reason surfaced.
- **AC-CHN-28 [BE]** Given a structured INTERACTIVE (button) message on a Messenger or Instagram
  channel, then it is sent as Meta **quick replies** built from the SAME `structured.py` definition
  the composer already produces, capped and truncated to the platform's limits; a LIST-type
  structured message, a location message and a contacts message are rejected at the service layer
  for these channel types with a typed reason (the composer already does not offer them).
- **AC-CHN-29 [BE]** Given `services/messaging_policy.py` capabilities, then the server rejects any
  message kind the target channel type cannot carry, whatever the caller (inbox, workflow action,
  public gateway, embed) - the frontend gating is UX only.
- **AC-CHN-30 [BE]** Given the dev-safe rule (`META_APP_ID` unset OR the channel carries `dev`
  credentials), then every Messenger and Instagram Graph call is stubbed: sends return a
  deterministic fake message id, no network call is made, and the entire suite runs with no Meta
  environment configured.
- **AC-CHN-31 [BE]** Given a caller from tenant B using any tenant A id (channel, contact, identity,
  message), then every route touched by this slice returns a uniform 404 - never 403, never data -
  and every stored user, channel and contact id resolved on a read path is resolved TENANT-SCOPED.

## Slice S3 - Backend: connect flow, channel service, dev seed

- **AC-CHN-32 [BE]** Given `POST /omnichannel/onboarding/meta/pages {code, redirectUri, channelType}`
  by a user holding `channels.manage`, then the auth code is exchanged server-side, the connectable
  pages (and, for `INSTAGRAM`, each page's linked Instagram professional account) are returned, and
  the exchanged token NEVER reaches the browser: it is stored Fernet-encrypted in a short-lived,
  tenant-and-user-bound connect session whose opaque id is returned instead.
- **AC-CHN-33 [BE]** Given `POST /omnichannel/onboarding/meta/connect {sessionId, workspaceId,
  channelType, pageId | igAccountId}`, then a channel is created for that tenant and workspace with
  `channel_type`, `external_account_id`, `external_account_name`, the page access token
  Fernet-encrypted in `credentials_json` and the ACTIVE channel status; the page is subscribed to
  the app's webhook fields best-effort (a subscription failure never blocks the connect); the
  connect session is consumed (single use) and expired sessions are refused and swept.
- **AC-CHN-34 [BE]** Given an `external_account_id` already bound to a LIVE channel anywhere in the
  service, then the connect returns 409 with a clear reason - the same service-wide uniqueness rule
  and the same partial-unique-index backstop that `phone_number_id` already has - so inbound routing
  stays O(1) and unambiguous.
- **AC-CHN-35 [BE]** Given the Meta app is unconfigured or the connect session carries dev
  credentials, then `/meta/pages` returns a deterministic simulated page list and `/meta/connect`
  creates a sandbox channel with `dev` credentials - the whole connect flow works end to end with no
  Meta app.
- **AC-CHN-36 [BE]** Given `ChannelItem`, then it carries `externalAccountId` and
  `externalAccountName` alongside the existing WABA fields, every field stays camelCase, datetimes
  stay Z-suffixed through `ApiModel`, and no existing field changes meaning or disappears.
- **AC-CHN-37 [BE]** Given a `FACEBOOK` or `INSTAGRAM` channel, then the WhatsApp-only routes
  (templates list / create / submit / sync, business profile read / write) return a typed 409 rather
  than attempting a Graph call, and `test_connection` pings the page or account instead of a phone
  number id.
- **AC-CHN-38 [BE]** Given `ENVIRONMENT=development`, then the dev seed creates ONE sandbox
  Messenger channel and (after S4) ONE sandbox Instagram channel in the demo workspace, each with
  two seeded threads whose identities carry a PSID / IGSID and an open window, alongside the
  existing `chn-demo` WhatsApp channel - so the E2E journey exists without a Meta app. Re-running the
  seed is idempotent.
- **AC-CHN-39 [BE]** Given `uninstall_tenant`, then the new columns and rows are removed with their
  owning tables by the generic loop and another tenant's channels are untouched; given the manifest
  version bump, then `AppStoreService.update()` re-grants the module's EXISTING keys and this slice
  introduces no new permission key and therefore needs no grant sweep.

## Slice S4 - Backend: Instagram

- **AC-CHN-40 [BE]** Given an Instagram webhook (`object: "instagram"`), then it is routed to the
  Instagram adapter, which reuses the Messenger normalizer for text, media, quick replies, postbacks
  and reactions and differs ONLY where Instagram differs; the shared code is inherited, not copied.
- **AC-CHN-41 [BE]** Given an Instagram-specific inbound kind not modelled by this slice (story
  reply, story mention, media share, unsend), then it is stored as the `UNSUPPORTED` placeholder
  with its payload preserved and logged, never dropped and never crashing the pipeline.
- **AC-CHN-42 [BE]** Given Instagram capabilities, then text, image, video, audio and quick replies
  are sendable and file / document attachments, templates, list messages, location, contacts and
  outbound reactions are not; the policy row declares the 24h window and the human-agent extension
  independently of Messenger, so a Meta policy divergence is a one-row change.
- **AC-CHN-43 [BE]** Given an inbound Instagram message from an IGSID with no identity, then a new
  contact is created exactly as for Messenger (no phone, IGSID identity, lifecycle stamped, `opened`
  event) and the same person messaging the linked Facebook Page creates a SEPARATE contact - this
  slice performs NO cross-channel auto-merge, by decision.
- **AC-CHN-44 [BE]** Given the Instagram connect flow, then only Instagram professional accounts
  LINKED to a Facebook Page the user administers are offered (the Instagram-Login / IG-direct path
  is out of scope), and a page whose linked account is missing is not offered at all.
- **AC-CHN-45 [BE]** Given an Instagram channel, then its `external_account_id` is the Instagram
  account id used for inbound routing, and outbound sends address the page-linked messages endpoint
  with the page access token; a test pins that inbound routing and outbound addressing use the
  values the connect flow stored.

## Slice S5 - Backend: media, receipts, reactions

- **AC-CHN-46 [BE]** Given an inbound Messenger or Instagram attachment (which arrives as a
  short-lived CDN **URL**, not a media id), then the blob is downloaded with the page token and
  stored through the EXISTING `storage_for_tenant` path with the same best-effort contract as
  WhatsApp media (a storage hiccup loses the media, never the message).
- **AC-CHN-47 [BE]** Given that attachment URL comes from an external payload, then it is validated
  before fetch: HTTPS only, host on a Meta CDN allowlist, the shared SSRF host guard applied, a
  capped read, redirects bounded - a URL failing any check is skipped and the message still lands.
- **AC-CHN-48 [BE]** Given an outbound Messenger or Instagram media message, then the blob is
  uploaded to Meta's attachment upload endpoint and sent BY ID (the same upload-by-id contract the
  WhatsApp path uses); the stored blob is never exposed as a public URL for Meta to fetch.
- **AC-CHN-49 [BE]** Given a `message_deliveries` or `message_reads` webhook, then the matching
  outbound rows advance to `DELIVERED` / `READ`: by `mids[]` when present, otherwise by applying the
  `watermark` timestamp to that thread's outbound messages created at or before it; receipts only
  ever move FORWARD (a late `SENT` after `READ` is ignored), and the realtime + consumer-webhook
  fan-out is the existing one.
- **AC-CHN-50 [BE]** Given a `message_reactions` webhook (react and unreact), then it flows through
  the EXISTING inbound reaction path (upsert on react, delete on unreact, keyed to the target
  message) and never creates a message bubble; an unknown target is dropped with a log line.
- **AC-CHN-51 [BE]** Given a Meta rate-limit or throttling error on a Messenger / Instagram send,
  then it is classified TRANSIENT so the existing bounded backoff applies, and the failure surfaces
  Meta's own reason on the message row.
- **AC-CHN-52 [BE]** Given the Developers > Logs console, then every Messenger and Instagram Graph
  call produces an `outbound_meta` activity row on the same trace as its inbound leg, through the
  EXISTING recorder seam (no second telemetry path).

## Slice S6 - Gateway, guide, workflow, wire-up and evidence

- **AC-CHN-53 [BE]** Given a workspace with more than one active channel, then the public gateway's
  implicit channel choice PREFERS a `WHATSAPP` channel (so every existing consumer keeps its exact
  behaviour) and falls back to the oldest active channel; `POST /api/v1/omnichannel/messages`
  additionally accepts an OPTIONAL explicit channel selector, and an unknown or foreign one is a
  typed 4xx, never a silent fallback to another channel.
- **AC-CHN-54 [BE]** Given the gateway send `to` field, then a bare value is still a phone number
  (unchanged), and the new prefixes `psid:` / `igsid:` / `id:` resolve an EXISTING contact identity
  in that workspace; a `psid:` / `igsid:` that resolves nothing is `422 invalid_recipient` and never
  creates a contact (we cannot fabricate an identity Meta will accept).
- **AC-CHN-55 [BE]** Given a gateway send refused by the window policy, then WhatsApp keeps
  returning the documented `csw_window_closed` code verbatim and Messenger / Instagram return a NEW
  distinct code; no existing error code changes meaning.
- **AC-CHN-56 [BE]** Given the gateway read shapes, then `channelType` on both the default and the
  `?format=rio` shapes now carries `FACEBOOK` / `INSTAGRAM` values, both shapes stay LOSSLESS versus
  the internal items, no field is dropped or renamed, and both are still derived from the SAME
  internal objects (one data path).
- **AC-CHN-57 [BE]** Given ANY change in this slice to `routers/api_v1.py` or the `Rio*` schemas,
  then `documentation/omnichannel/consumer-integration-guide.md` is updated in the SAME slice: a
  changelog row, the multi-channel channel-selection rule, the `to` identifier prefixes, the new
  error code and the widened `channelType` vocabulary. A gateway diff without a guide diff is a
  review reject, and the existing gateway contract-drift tests stay green.
- **AC-CHN-58 [BE]** Given the workflow trigger `omnichannel.message_received`, then it gains an
  optional **channel type** filter (unset = any type) alongside the existing channel filter, the
  trigger payload exposes the channel type, and the existing per-channel refine behaviour is
  unchanged; the frontend catalog entry renders the filter as a `SearchSelect` with an explicit
  "All types" option.
- **AC-CHN-59 [FE]** Given wire-up, then the mock service is swapped for the real one at the ONE
  service-boundary line, the connect wizard, channel list, channel form and composer all run against
  the real backend, and no "done" surface is still served by a mock.
- **AC-CHN-60 [T]** pytest covers: webhook object dispatch for all three products, signature
  rejection, PSID and IGSID stitch including the no-phone-stitch guard and the same-PSID-different-
  channel case, echo suppression, every inbound type mapping including the unsupported placeholder,
  the window policy matrix (WhatsApp unchanged; Messenger and Instagram inside 24h, inside 7 days by
  human vs by automation, outside 7 days), persisted send parameters, channel addressing including
  the missing-identity case, quick-reply mapping and the rejected kinds, attachment URL validation
  (allowlist pass and fail, non-HTTPS, oversize), upload-by-id outbound media, watermark and mid
  receipts, reaction react and unreact, connect flow including page uniqueness 409 and session
  expiry and single use, dev-safe stubs with no Meta env, the migration backfill, tenant isolation
  per route, and a parity test pinning the backend capability table to
  `lib/channel-capabilities.ts`.
- **AC-CHN-61 [T]** vitest covers: the wizard channel-type and page-selection steps (including the
  already-connected exclusion), the capabilities record driving composer affordances per type, the
  three window states, the channel-type badge and icon lookup, the channel form tab filtering, and
  the mock service states.
- **AC-CHN-62 [E2E]** Recorded `agent-browser --session s32` run (real clicks from `/`, never a
  typed URL; evidence at 375px AND 1280px under
  `documentation/plans/sprint-4/32-evidence/<slice>/` with a README run log), against the dev
  tenant's SANDBOX channels so no Meta app is needed: sidebar -> Omnichannel -> Settings -> Channels
  -> Connect -> type Facebook Messenger -> simulated authorize -> pick a page -> the channel appears
  in the list with a Messenger type badge -> open it and confirm no Templates and no Profile tab ->
  repeat for Instagram -> Inbox -> open a seeded Messenger thread -> send a text -> the bubble
  appears -> open the thread whose window has closed and confirm the composer is locked with no
  template affordance -> a user without `channels.manage` sees no Connect control.
- **AC-CHN-63 [T]** A Test Execution Report
  (`32-omnichannel-channels-messenger-instagram-test-report.md`,
  `AI_Agent_Orchestration_Guide.md` section 6 format) records PASS / FAIL / DEFERRED per AC id and
  cites the evidence run for every `[E2E]` id; deferred items are registered in
  `documentation/backlogs/backlog.md` with a link back to the plan.
