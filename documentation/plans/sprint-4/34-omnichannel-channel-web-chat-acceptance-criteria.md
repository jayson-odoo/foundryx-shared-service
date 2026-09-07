# 34 - Omnichannel channel: website chat (embeddable widget + visitor identity) - User Acceptance Criteria

> **Status:** DRAFT - contract for `documentation/plans/sprint-4/34-omnichannel-channel-web-chat.md`.
> **Program:** slice **A7b** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G20,
> roadmap row A7 "A7b web chat (drives A6 identity mapping)", order decided 2026-09-05).
> **Depends on (merged to `main` before A7b branches):** plan 32 / A7a (the `ChannelAdapter`
> registry, `messaging_policy.POLICIES`/`CAPABILITIES`/`authorize`, `channel_addressing`, the
> per-identity window columns, `lib/channel-capabilities.ts`, the gateway `to` prefixes and the
> guide-diff rule), plan 31 / A5 (`BusinessHoursService`, the workflow `channelType` filter), plan
> 27 / A3 (`conversation_events`), plan 25 / A1 and plan 26 / A2 (contacts). Plan 33 / A6 consumes
> one row from this slice (`SOURCE_TO_CHANNEL_TYPE`) and may land in either order.
> **Out of scope (stated, never silently missing):** visitor file/image uploads (agent to visitor
> media IS in scope), voice or video calling, co-browsing, a transcript email to the visitor,
> multi-channel "growth widget" launchers (WhatsApp/Messenger buttons inside the same bubble),
> QR / chat-link generation (G21 / C2), wildcard-subdomain allowed origins, an authorable pre-chat
> form built on the form engine, visitor-side typing indicators from the agent side, canned
> "offline form" as a separate entity, contact merge (B2 / G24), Telegram (A7c), email (A7d),
> SMS (A7e).

IDs: `AC-WEB-##`. Tags: `[BE]` `[FE]` `[E2E]` `[T]`.

## Definitions

- **Web chat channel** - a `channels` row with `channel_type = "WEBCHAT"`. It has no external
  provider: the only party on the far side is a browser talking to THIS backend. Everything that
  makes a channel a channel on the A7a spine (adapter row, window policy row, capability row,
  addressing branch) still applies.
- **Widget key** - `channels.widget_key`: a 32-character opaque, machine-minted, globally unique
  identifier for one web chat channel. It is the only channel-identifying value that appears in a
  customer's public website source. It is NOT a secret (it is readable by anyone who views the
  page source) and it is NOT an authorization token.
- **Widget secret** - a per-channel HMAC secret stored Fernet-encrypted in the channel's existing
  `credentials_json`. Revealed exactly once at connect and once per rotation; never echoed on any
  read. It signs **host identity assertions** only.
- **Loader** - the vanilla-JavaScript file a customer pastes into their website
  (`<script src=".../omnichannel/widget/<widgetKey>.js" async></script>`). It contains no secret,
  no tenant name and no branding; its entire job is to create ONE iframe and relay resize / open /
  close messages.
- **Panel** - the Next.js public route the iframe loads. This is the actual chat UI (greeting,
  pre-chat, transcript, composer), built from the house design system.
- **Visitor** - an anonymous browser session on a customer's website. Identified by a **visitor
  token**.
- **Visitor token** - a signed, opaque JWT (`typ="webchat"`) bound to one tenant, one channel and
  one visitor id, held in the PANEL's own `localStorage` and presented as a Bearer header. There is
  no cookie anywhere in this feature.
- **Host identity assertion** - an optional `{ userRef, hash }` pair the customer's website passes
  to the loader, where `hash` is HMAC-SHA256 of `userRef` keyed by the channel's widget secret. A
  VALID assertion is the ONLY way a web chat session ever attaches to a pre-existing contact.
- **Allowed origins** - the per-channel list of website origins that may run this widget. Enforced
  SERVER-SIDE on every session start and as `frame-ancestors` on the panel document.
- **Visitor projection** - the fail-closed, allowlisted re-shaping of an internal `MessageItem` or
  realtime frame into the small object a visitor may see. It is the only thing that ever reaches a
  visitor.
- **Uniform 404** - one identical `404 {"detail": "Not found."}` for an unknown widget key, a
  trashed / inactive channel, an uninstalled module, a suspended tenant and a disallowed origin. No
  response distinguishes those cases.

---

## Slice S0 - Frontend on the mock service

- **AC-WEB-01 [FE]** Given the channel connect wizard, then its channel-type `SearchSelect` offers
  **Web chat** alongside WhatsApp, Facebook Messenger and Instagram, sourced from the SAME
  `CHANNEL_TYPES` array in `lib/channel-capabilities.ts` (no second list); selecting it skips the
  Meta OAuth and page-selection steps entirely and asks only for a channel name, a workspace and at
  least one website origin.
- **AC-WEB-02 [FE]** Given the Web chat connect step, then the origins control is the EXISTING
  `origins-editor.tsx` from `app/(protected)/omnichannel/settings/embed/` (reused, not cloned);
  "Connect" stays disabled until at least one valid origin is present, and an invalid origin
  surfaces the same field-level message the embed screen already produces.
- **AC-WEB-03 [FE]** Given a `WEBCHAT` channel's detail form, then the tabs are Configuration,
  **Widget** and Webhooks; Templates and Profile are absent (filtered out of the existing `tabs`
  array the same way A7a filters them for Messenger / Instagram), and Configuration shows the
  widget key and origins block instead of the WABA block.
- **AC-WEB-04 [FE]** Given the Widget tab, then it renders on the resource-form section pattern
  with grouped fields for appearance (accent colour, launcher position left/right, header title,
  agent display name), greeting text, offline greeting text, and pre-chat toggles (ask name, ask
  email, ask phone); every dropdown is a `SearchSelect`; no instructional or how-to copy appears
  anywhere on the tab.
- **AC-WEB-05 [FE]** Given the Widget tab, then the install snippet renders through the EXISTING
  `snippet-card.tsx` / `copy-field.tsx` components from the embed settings screen (reused, not
  re-implemented), and the snippet shown is exactly the string the backend serves for this channel.
- **AC-WEB-06 [FE]** Given the Widget tab, then a "Rotate widget secret" action exists behind the
  standard `ActionMenu`, reveals the new secret exactly once in a dialog, and the tab never
  displays a previously-stored secret on load.
- **AC-WEB-07 [FE]** Given `lib/channel-capabilities.ts`, then a `WEBCHAT` record exists declaring
  `reengageMode: 'none'`, `template: false`, `list: false`, `location: false`, `contacts: false`,
  `outboundReaction: false`, `quickReplies: true` and outbound media image/video/audio/document
  true, sticker false; the frontend union `ChannelType` gains `'WEBCHAT'` and nothing else.
- **AC-WEB-08 [FE]** Given a `WEBCHAT` thread in the conversation drawer, then the composer is
  NEVER locked and no messaging-window banner or "Choose template" affordance renders, whatever the
  thread's timestamps; the attach menu offers image, video, audio and file and does not offer
  stickers, location, contacts or reactions.
- **AC-WEB-09 [FE]** Given the Channels list and the inbox thread list and the contacts channels
  cell, then a `WEBCHAT` channel renders its own badge, label and icon from the ONE
  `CHANNEL_CAPABILITIES` lookup (no per-surface hardcoded icon), and "Web chat" is offered as a
  Type filter value on the Channels list.
- **AC-WEB-10 [FE]** Given the service trio `services/webchat-service.{ts,mock,real}.ts` (admin
  side) and `services/webchat-visitor-service.{ts,mock,real}.ts` (visitor side), then every surface
  in S0 and S4 renders correctly against the mock for loading, empty, populated, sending, failed
  and offline states; no component calls `fetch`/`axios` directly and no `any` type appears.
- **AC-WEB-11 [FE]** Every surface in this slice is usable and non-clipped at 375px and at 1280px;
  no tenant-facing string anywhere in the widget, the panel, the snippet or the settings tab says
  "Foundryx".

## Slice S1 - Backend: the channel type, its config, and the loader asset

- **AC-WEB-12 [BE]** Given `adapters/__init__.py`, then `ADAPTERS` gains a `"WEBCHAT"` row bound to
  a `WebChatAdapter` implementing the existing `ChannelAdapter` protocol; `get_adapter("WEBCHAT")`
  returns it and an unknown type still raises `ValueError`.
- **AC-WEB-13 [BE]** Given `messaging_policy`, then `POLICIES["WEBCHAT"]` declares
  `reengage_mode = "none"` and `CAPABILITIES["WEBCHAT"]` declares document true, sticker false,
  template false, interactive_list false, location false, contacts false, reaction_outbound false;
  `authorize` gains exactly ONE new branch (`reengage_mode == "none"` returns an allowed
  `SendDecision()` with no Meta send parameters) and `stamp_inbound_window` leaves
  `window_expires_at` / `human_agent_expires_at` NULL for a `WEBCHAT` identity.
- **AC-WEB-14 [T]** Given the full pre-existing WhatsApp / Messenger / Instagram send and window
  test suites, then they pass with ZERO edits after the `"none"` branch lands - in particular a
  WhatsApp free-form send outside the 24h window still raises `csw_window_closed` with the
  byte-identical `CSW_CLOSED_MESSAGE`.
- **AC-WEB-15 [BE]** Given `channel_addressing`, then `sender_ref` returns the channel's
  `widget_key` for `WEBCHAT` and `recipient_ref` returns the contact's `external_user_id` on that
  channel, raising `NoChannelIdentity` when there is none (no empty recipient is ever addressed).
- **AC-WEB-16 [BE]** Given the model + migration, then `channels` gains `widget_key`
  (indexed, PARTIAL UNIQUE over live rows), `widget_config_json` and `widget_token_epoch` (int,
  default 0), and `contact_channel_identities` gains `last_seen_at`; the module Alembic revision is
  inspector-guarded, Postgres-only, a no-op under pytest, and every new column is mirrored by an
  `ADD COLUMN IF NOT EXISTS` in `bootstrap.create_schema_and_tables`.
- **AC-WEB-17 [BE]** Given origin validation, then `_validate_origin` / `_validate_origins` are
  MOVED verbatim out of `services/embed_config_service.py` into a shared module and re-imported
  there (a pure move: the plan-11H embed tests pass with zero edits), and the web chat channel
  reuses the same function - there is exactly one origin validator in the module.
- **AC-WEB-18 [BE]** Given `POST /omnichannel/onboarding/webchat/connect` with `channels.manage`,
  then it creates an ACTIVE `WEBCHAT` channel in the caller's tenant, mints a widget key and a
  widget secret, stores the secret Fernet-encrypted in `credentials_json`, returns the secret
  exactly once in the 201 body, and never returns it again on any subsequent read.
- **AC-WEB-19 [BE]** Given `POST /omnichannel/channels/{id}/widget/rotate-secret` with
  `channels.manage`, then a new secret is minted and revealed once, the previous secret stops
  verifying immediately, and `widget_token_epoch` is left unchanged (rotating the signing secret
  must not sign every live visitor out).
- **AC-WEB-20 [BE]** Given `GET /omnichannel/widget/{widgetKey}.js` (public, unauthenticated), then
  it serves the loader with `Content-Type: application/javascript; charset=utf-8`,
  `X-Content-Type-Options: nosniff`, `Cache-Control: public, max-age=300` and an ETag; the body
  contains the widget key and the panel origin and NOTHING else that is tenant-identifying - no
  tenant slug, no tenant name, no secret, no origin list, no branding.
- **AC-WEB-21 [BE]** Given a widget key that does not exist, belongs to a trashed or inactive
  channel, belongs to a tenant whose module is not ACTIVE, or belongs to a tenant that cannot sign
  in, then `GET /omnichannel/widget/{widgetKey}.js` returns the uniform 404 - byte-identical in all
  five cases.
- **AC-WEB-22 [BE]** Given no new rows in `permissions/permissions.csv`, then every new endpoint in
  this slice is gated by an EXISTING key (`channels.read` / `channels.manage`), so no grant sweep
  is required for already-provisioned tenants.

## Slice S2 - Backend: the public visitor API and inbound

- **AC-WEB-23 [BE]** Given `POST /public/omnichannel/webchat/{widgetKey}/session` with an `Origin`
  header on the channel's allowed list, then it returns the widget configuration a panel needs
  (appearance, greeting, offline greeting, pre-chat toggles, agent display name, branding token
  diff, tenant display name, `online` boolean) plus a visitor token; the response carries
  `Access-Control-Allow-Origin: <the exact allowlisted origin>` (never `*`),
  `Access-Control-Allow-Credentials` absent, and `Vary: Origin`.
- **AC-WEB-24 [BE]** Given the same request with an `Origin` that is NOT on the channel's list, or
  with no `Origin` header at all, then the response is the uniform 404 - identical to the unknown
  key case, so an off-list website cannot even learn that the channel exists.
- **AC-WEB-25 [BE]** Given a session start, then NO `contacts` row and NO
  `contact_channel_identities` row is created: a visitor id is minted into the token only. A
  thousand page views produce zero database rows in either table.
- **AC-WEB-26 [BE]** Given `POST /public/omnichannel/webchat/{widgetKey}/messages` with a valid
  visitor token and a text body, then on the FIRST such message the contact and its
  `ContactChannelIdentity(channel_type WEBCHAT, external_user_id = "visitor:<visitorId>")` are
  created, the message is persisted through the ONE existing `InboundService` path (idempotency,
  contact stitch, unread bump, `conversation_events`, realtime publish, consumer-webhook fan-out
  and the `omnichannel.message_received` workflow trigger all behave exactly as for WhatsApp), and
  the visitor projection of the stored message is returned.
- **AC-WEB-27 [BE]** Given a visitor token, then every query on the public path derives
  `tenant_id`, `channel_id` and `contact_id` from the TOKEN and the widget key, never from any
  request body field; a token minted for channel A can neither read nor write anything on channel
  B, and a forged, expired, wrong-`typ` or wrong-signature token yields 401 with no detail that
  distinguishes the four cases.
- **AC-WEB-28 [BE]** Given `channels.widget_token_epoch` is incremented (an admin "sign out all
  visitors" action), then every previously issued visitor token for that channel is refused on its
  next use, and a fresh session start immediately succeeds.
- **AC-WEB-29 [BE]** Given a visitor token within 7 days of expiry presented at session start, then
  the response carries a renewed token bound to the SAME visitor id and contact; a token more than
  7 days from expiry is returned unchanged.
- **AC-WEB-30 [BE]** Given the public web chat endpoints, then they use their OWN throttle bucket
  (never the login, form, doc-share, portal or embed bucket) with two independent key namespaces -
  per client IP and per visitor id - and the throttle is enforced BEFORE any database work on both
  the session and the message endpoint.
- **AC-WEB-31 [BE]** Given a visitor text longer than the configured cap (4096 characters), then
  the request is refused with a typed 422 and nothing is stored; the server never silently
  truncates. A body larger than the endpoint's read cap is refused without being buffered.
- **AC-WEB-32 [BE]** Given a pre-chat submission whose honeypot field is non-empty, then the
  endpoint returns the normal success shape and stores NOTHING - no contact, no identity, no
  message, no event (the form-engine precedent: never tip off the bot).
- **AC-WEB-33 [BE]** Given the public web chat surface, then there is NO upload endpoint of any
  kind: a multipart request to the message endpoint is refused, and a message body carrying a media
  reference is refused with a typed 422.
- **AC-WEB-34 [BE]** Given `GET /public/omnichannel/webchat/{widgetKey}/messages?after=<id>`, then
  it returns this visitor's thread history through the visitor projection only, oldest to newest,
  page-capped; internal notes, agent user names, agent emails, assignee, tags, lifecycle, custom
  fields, close reasons, internal ids other than the message id, and any other contact's messages
  are ABSENT from every response.
- **AC-WEB-35 [T]** Given the visitor projection, then it is fail-closed: a message kind, a sender
  source or a realtime frame type it does not explicitly allow is DROPPED, and a test asserts that
  adding an unknown value produces no visitor-visible output rather than passing it through.

## Slice S3 - Backend: outbound to the visitor and realtime

- **AC-WEB-36 [BE]** Given an agent reply on a `WEBCHAT` thread, then it flows through the
  UNCHANGED `MessageService` enqueue and `send_runner.run_send` dispatcher; `WebChatAdapter.send`
  performs no network call, returns a locally generated external message id, and the row reaches
  `SENT` in the same run.
- **AC-WEB-37 [BE]** Given any `WEBCHAT` mutation (agent message, agent media, status change,
  workflow-sent message, broadcast skip), then it publishes to the existing workspace realtime room
  exactly as WhatsApp does - there is no second publish path and no mutation path that skips the
  publish.
- **AC-WEB-38 [BE]** Given the EXISTING conversation WebSocket endpoint, then it accepts a third
  principal type resolved from a visitor token (`typ="webchat"`), scoped to that visitor's single
  contact; the frames it relays to that principal are passed through the visitor projection and a
  frame for any other contact is never relayed.
- **AC-WEB-39 [T]** Given a visitor socket and a second visitor on the same channel, then a message
  sent by visitor B produces no frame on visitor A's socket, and an internal note added by an agent
  on visitor A's own thread produces no frame on visitor A's socket.
- **AC-WEB-40 [BE]** Given a visitor whose WebSocket cannot open or drops, then
  `GET .../messages?after=<lastSeenId>` returns exactly the messages the socket would have
  delivered, so polling is a complete fallback and is served by the SAME endpoint that serves
  history (no third transport exists).
- **AC-WEB-41 [BE]** Given an agent sends media on a `WEBCHAT` thread, then the visitor projection
  carries a signed, short-TTL media URL bound to that message id, generated by the EXISTING
  `signed_media_url` helper; a visitor token for a different contact cannot obtain such a URL, and a
  tampered or expired signature is refused by the existing media route.
- **AC-WEB-42 [BE]** Given a visitor socket connect, a session start or a message post, then
  `contact_channel_identities.last_seen_at` is stamped, and `ThreadItem` exposes it as
  `visitorLastSeenAt`.
- **AC-WEB-43 [FE]** Given a `WEBCHAT` thread in the inbox, then the drawer shows a neutral
  presence marker derived from `visitorLastSeenAt` and NEVER locks the composer because of it; the
  marker carries no instructional copy.

## Slice S4 - Frontend: the panel and the loader integration

- **AC-WEB-44 [FE]** Given the panel route, then it lives at
  `app/(public)/public/webchat/[widgetKey]/page.tsx` - under a LITERAL `public/` path segment, not
  a bare route group - so it cannot collide with any protected dynamic route at build time.
- **AC-WEB-45 [FE]** Given the loader running on an allowlisted host page, then it injects exactly
  ONE `<iframe>` into the host document, sets its geometry through `iframe.style` properties only
  (it injects no `<style>` element and no stylesheet into the host page), and resizes between the
  launcher and open states in response to `postMessage` from the panel.
- **AC-WEB-46 [FE]** Given the loader, then it exposes a minimal global with `open()`, `close()`,
  `isOpen()` and an `identify({ userRef, hash })` call, and it validates every inbound
  `postMessage` against the expected panel origin before acting on it.
- **AC-WEB-47 [FE]** Given the panel, then it renders the greeting, the optional pre-chat step, the
  transcript and the composer using house primitives and brand tokens supplied by the session
  response; there is no "Foundryx" string, no vendor badge and no instructional copy; the panel
  document is served with `Content-Security-Policy: frame-ancestors` limited to the channel's
  allowed origins.
- **AC-WEB-48 [FE]** Given any visitor-authored text, then it is rendered as a text node in the
  panel and in the agent inbox - never through `dangerouslySetInnerHTML`, never as markdown-to-HTML,
  never into an `href`/`src` attribute without scheme validation.
- **AC-WEB-49 [FE]** Given the panel on a browser where storage is unavailable (private mode,
  blocked partitioned storage), then it falls back to an in-memory session for that tab and the
  visitor can still chat; nothing throws and no error state is shown.
- **AC-WEB-50 [FE]** Given two tabs of the same website, then both resolve the same visitor token
  from the same partitioned storage and both render the same thread and receive the same live
  messages.
- **AC-WEB-51 [FE]** Given the panel, then it is usable and non-clipped at 375px (where it fills
  the viewport) and at 1280px (where it is a bottom-anchored panel), and its quick-reply buttons
  render tappable at both widths.

## Slice S5 - Backend: business hours, pre-chat, host identity

- **AC-WEB-52 [BE]** Given the session response `online` flag, then it is computed by the EXISTING
  `BusinessHoursService` (the workspace row, else the tenant default row); a workspace with no
  business hours configured resolves `online: true` rather than guessing a schedule.
- **AC-WEB-53 [FE]** Given `online: false`, then the panel shows the channel's offline greeting
  instead of its online greeting and shows the pre-chat step if any pre-chat toggle is on; the
  message the visitor sends afterwards travels the SAME path as an online message - there is no
  separate offline-message entity anywhere.
- **AC-WEB-54 [BE]** Given a pre-chat submission with name / email / phone, then those values are
  written onto the resolved contact ONLY where the corresponding field is currently empty, and they
  NEVER cause a lookup or merge against any other existing contact.
- **AC-WEB-55 [BE]** Given a host identity assertion `{ userRef, hash }` whose HMAC verifies
  against the channel's widget secret, then the session resolves the identity
  `external_user_id = "host:<userRef>"` on that channel, reusing its contact when one exists and
  creating one lazily on the first message otherwise.
- **AC-WEB-56 [BE]** Given a host identity assertion with a missing, malformed or non-verifying
  hash, then it is IGNORED (the session proceeds as an anonymous visitor) and no error is returned
  to the visitor; a `userRef` is never trusted without a valid signature under any circumstance.
- **AC-WEB-57 [BE]** Given the dev seed with `ENVIRONMENT=development`, then a sandbox web chat
  channel (`chn-demo-web`) with a localhost allowed origin and two seeded visitor threads exists on
  the default tenant, so the inbox, the reports and the E2E journeys have a web chat thread without
  any external dependency.

## Slice S6 - Gateway, guide, workflow, migration map, wire-up, evidence

- **AC-WEB-58 [BE]** Given `POST /api/v1/omnichannel/messages`, then `to` accepts
  `"webchat:<visitorId>"`, which resolves an EXISTING identity on the chosen channel only and never
  creates one (`422 invalid_recipient` otherwise), exactly mirroring the `psid:` / `igsid:` rule.
- **AC-WEB-59 [BE]** Given both gateway read shapes (default and `?format=rio`), then `channelType`
  additionally carries `WEBCHAT`, `visitorLastSeenAt` is present on both, `cswExpiresAt` /
  `windowExpiresAt` / `humanAgentExpiresAt` read `null` for a web chat contact, and no existing
  field is renamed, dropped or given a new meaning. Both shapes are still derived from the same
  internal `ThreadItem` / `MessageItem` objects.
- **AC-WEB-60 [BE]** Given the same commit range as the gateway diff, then
  `documentation/omnichannel/consumer-integration-guide.md` carries a changelog row, the widened
  `channelType` vocabulary in sections 9.1 / 9.2 / 9.3, the `webchat:` prefix in section 4.1, the
  new `visitorLastSeenAt` field and the explicit statement that a web chat contact has no messaging
  window. A gateway diff without a guide diff is an automatic review reject.
- **AC-WEB-61 [BE][FE]** Given the workflow trigger `omnichannel.message_received`, then its
  `channelType` filter offers **Web chat** on the canvas (`lib/workflow-catalog.ts`) and matches
  `WEBCHAT` payloads on the backend; `omnichannel.send_message` sends to a web chat contact with no
  window refusal, because a web chat channel has `reengage_mode = "none"`.
- **AC-WEB-62 [BE]** Given plan 33's `SOURCE_TO_CHANNEL_TYPE`, then it gains exactly ONE row
  mapping respond.io's website-chat source value to `"WEBCHAT"`, verified against a live
  `GET /space/channel` before the row is written; an unverified guess is left absent so the source
  channel maps to "Skip this channel" rather than misrouting.
- **AC-WEB-63 [FE]** Given the Definition-of-Done gate, then every mock service introduced in S0
  and S4 is swapped for the real `api-client` call at the one service boundary and every surface is
  verified showing real data.
- **AC-WEB-64 [E2E]** Recorded agent-browser run, real clicks from `/`, 375px and 1280px: an admin
  connects a web chat channel, adds the lane's host origin, copies the snippet, and the Channels
  list shows the new channel with its Web chat badge.
- **AC-WEB-65 [E2E]** Recorded agent-browser run, 375px and 1280px: a visitor loads the lane host
  page, opens the widget, completes the pre-chat step and sends a message; the agent sees the
  thread appear live in the inbox and replies; the visitor sees the reply arrive WITHOUT reloading;
  the agent then sends an image and the visitor opens it.
- **AC-WEB-66 [E2E]** Recorded agent-browser run: the same snippet loaded from an origin that is
  NOT on the channel's allowlist never opens a chat (uniform 404 at session start), and a workspace
  with business hours set to a closed window shows the offline greeting while the visitor's message
  still lands in the inbox. Every created name is timestamped; evidence and a run log live under
  `documentation/plans/sprint-4/34-evidence/<slice>/`.
