# 34 - Omnichannel channel: website chat (embeddable widget + visitor identity) (A7b)

> **Contract:** `34-omnichannel-channel-web-chat-acceptance-criteria.md` (66 ACs). This plan fulfils it.
> **Program:** slice **A7b** of `24-omnichannel-respondio-parity-roadmap.md` (Phase A, P0; gap G20,
> roadmap row A7 "A7b web chat (drives A6 identity mapping)", order decided 2026-09-05).
> **Depends on:** plan 32 / A7a (the whole channel-type spine) and plan 31 / A5
> (`BusinessHoursService`, the workflow `channelType` filter) merged to `main`. Plan 33 / A6
> consumes one row from this slice and may land in either order.
> **Branch:** `sprint-4/34-channel-web-chat`, worktree `.claude/worktrees/s34` cut off `main` AFTER
> the A7a merge. Lane: backend `:8012` on DB `foundryx_service_s34`, frontend `:3011`,
> `agent-browser --session s34`, plus a static host-page server on `:3012` for the E2E (see 7 / R9).
> Each worktree gets its OWN `npm ci` - never a shared `node_modules`.
> **Code read at:** local branch `sprint-4/32-channels-messenger-instagram` HEAD `e4ac64ef`
> ("plan 32 S6 ..."). Every `file:line` in section 6 is pinned there. A7a is not yet on `origin`
> under that name; re-pin at branch time against merged `main`.

## 1. Why

Website chat is the one channel in the customer's respond.io stack with NO external provider. That
makes it the cheapest channel to build (no OAuth, no Graph, no webhook signature, no dev-stub) and
the most dangerous to ship carelessly: it is the first surface in this Service where an
UNAUTHENTICATED browser on somebody else's website writes into a tenant's inbox and reads messages
back. The engineering content of A7b is therefore not "a new adapter" - A7a already made that a
three-row change - it is a hardened public surface plus a distributable browser artifact.

It also unblocks two other slices. A6 (plan 33) needs a `WEBCHAT` target so respond.io's website
chat contacts migrate instead of being skipped, and A5's Ask-a-Question step finally has a channel
with no messaging window at all, which is where a conversational workflow actually shines.

## 2. Architecture

```
customer website (https://shop.acme.com)
  <script src="https://app.example/omnichannel/widget/<widgetKey>.js" async></script>
        |  loader: ONE iframe + postMessage(resize|open|close|identify). No secret. No CSS injected.
        v
  <iframe src="https://app.example/public/webchat/<widgetKey>">            PANEL (Next public route)
        |  visitor token in the PANEL's own localStorage, sent as Authorization: Bearer
        |  NO COOKIE ANYWHERE  => no ambient credential => no CSRF surface
        v
FastAPI public router  /public/omnichannel/webchat/{widgetKey}/...
  POST /session    origin allowlist -> throttle -> config + branding + online + visitor token
  POST /messages   throttle(ip, visitor) -> size cap -> honeypot -> WebChatAdapter.parse_inbound
  GET  /messages   history AND the poll fallback (ONE endpoint)
        |
        v
InboundService.process_payload                (UNCHANGED pipeline)
  contact stitch -> conversation_events -> realtime publish -> consumer webhooks
  -> omnichannel.message_received workflow trigger

OUTBOUND (unchanged in shape)
  MessageService.<send_*> -> messaging_policy.authorize(... reengage_mode="none" -> always allowed)
                          -> send_runner.run_send
                               -> channel_addressing.sender_ref/recipient_ref
                               -> WebChatAdapter.send  (no network; stamps SENT, publishes)

REALTIME to the visitor
  existing WS /omnichannel/ws?workspaceId=&token=<visitor token>
    _authorize gains a third principal type (typ="webchat", thread-scoped)
    every relayed frame passes through visitor_projection()  <- FAIL-CLOSED ALLOWLIST
  fallback when the socket cannot open: GET /messages?after=  (the same endpoint as history)
```

The A7a rule holds unchanged: **nothing branches on `channel_type` outside `adapters/`,
`services/messaging_policy.py` and `services/channel_addressing.py`.** A7b adds one row to each and
one new public router. The second rule this slice adds: **nothing reaches a visitor except through
`visitor_projection`.**

### 2.1 Backend pieces

| Piece | Where | Notes |
|---|---|---|
| Adapter | `modules/omnichannel/adapters/webchat.py` (new) | `channel_type = "WEBCHAT"`; `parse_inbound` turns a visitor post into the canonical event dict the pipeline already consumes; `send` does no I/O and returns a locally minted external id; `test_connection` reports the channel's origin count; `fetch_media` / `list_templates` / `exchange_code` raise `NotImplementedError` as unreachable |
| Registry row | `adapters/__init__.py` | `ADAPTERS["WEBCHAT"] = WebChatAdapter` - one line |
| Policy rows | `services/messaging_policy.py` | `POLICIES["WEBCHAT"]` (`reengage_mode="none"`), `CAPABILITIES["WEBCHAT"]`, and ONE new branch in `authorize` for `"none"` |
| Addressing | `services/channel_addressing.py` | `sender_ref` returns `widget_key`; `recipient_ref` returns the identity's `external_user_id` |
| Origins (pure move) | `modules/omnichannel/origins.py` (new) | `_validate_origin` / `_validate_origins` moved verbatim out of `services/embed_config_service.py`, which re-imports them (the `meta_graph.py` precedent) |
| Visitor tokens | `modules/omnichannel/webchat_auth.py` (new) | mint / verify (`typ="webchat"`, tenant + channel + visitor + contact binding, epoch check, sliding renewal). Uses the core `app.security` JWT helpers - no new crypto |
| Widget service | `services/webchat_service.py` (new) | connect, config read/write, secret mint + rotate, epoch bump, session start, host-assertion verification, `online` via `BusinessHoursService` |
| Visitor service | `services/webchat_visitor_service.py` (new) | the ONLY writer on the public path: throttle, honeypot, size cap, lazy contact creation, hand-off to `InboundService`, history reads |
| Projection | `services/webchat_projection.py` (new) | `visitor_message_item(...)` and `visitor_frame(...)` - fail-closed allowlists. The single chokepoint for everything a visitor sees |
| Public router | `routers/webchat_public.py` (new, manifest prefix `/public/omnichannel/webchat`, `"public": true`) | HTTP + Pydantic only; CORS headers set per-response from the allowlist |
| Loader route | `routers/webchat_widget.py` (new, manifest prefix `/omnichannel/widget`, `"public": true`) | serves `{widgetKey}.js` |
| Loader asset | `modules/omnichannel/widget/loader.js` (new, static file) | hand-written vanilla JS, no build step, two placeholder substitutions (`__WIDGET_KEY__`, `__PANEL_ORIGIN__`) done by plain string replace |
| Admin routes | `routers/onboarding.py`, `routers/channels.py` | `POST /onboarding/webchat/connect`; `GET/PUT /channels/{id}/widget`, `POST /channels/{id}/widget/rotate-secret`, `POST /channels/{id}/widget/sign-out-visitors` (all `channels.manage`, no new key) |
| Model + migration | `models.py`, `alembic/versions/0021_omni_webchat.py` | `Channel.widget_key` / `widget_config_json` / `widget_token_epoch`; `ContactChannelIdentity.last_seen_at`; partial unique index on `widget_key`; mirrored `ADD COLUMN IF NOT EXISTS` in `bootstrap.create_schema_and_tables` |
| Throttle | `app/models/auth_throttle.py`, `app/services/throttle.py`, `app/config.py` | `THROTTLE_SCOPE_WEBCHAT` + `enforce_webchat` / `record_webchat` + two settings, exactly like `THROTTLE_SCOPE_FORM_PUBLIC` |
| WS principal | `routers/ws.py` | a third branch in `_authorize` plus the projection on the relay |
| Wire | `schemas.py`, `services/conversation_service.py` | `ChannelItem` += `widgetKey`; `ThreadItem` += `visitorLastSeenAt`; `WebchatConfig`, `WebchatSession`, `VisitorMessage` |
| Gateway | `services/public_gateway_service.py`, `routers/api_v1.py` | `webchat:` `to` prefix, widened `channelType`, `visitorLastSeenAt` on both shapes |
| **Guide** | `documentation/omnichannel/consumer-integration-guide.md` | changelog row + sections 4.1 / 9.1 / 9.2 / 9.3 / 10. **Same slice as the gateway diff - non-negotiable** |
| Workflow | `workflow_nodes.py`, `lib/workflow-catalog.ts` | one option value on the existing `channelType` filter |
| A6 map | `modules/omnichannel/respondio/channel_map.py` (plan 33) | one `SOURCE_TO_CHANNEL_TYPE` row |
| Dev seed | `bootstrap.py seed_demo_conversations` | `chn-demo-web` + two visitor threads |
| Manifest | `manifest.json` | version bump + two new public router entries |

Reused unchanged: `services/inbound_service.py` (the whole pipeline), `services/message_service.py`,
`services/send_runner.py`, `services/realtime.py`, `services/event_service.py`,
`services/webhook_delivery.py`, `services/business_hours.py`, `security.py` (`signed_media_url`),
`routers/media.py`, `app/services/storage.py`, `app/branding/*`.

### 2.2 Frontend pieces

| Piece | Where |
|---|---|
| Capability row | `lib/channel-capabilities.ts` - a `WEBCHAT` record; `CHANNEL_TYPES` grows by one. `types/omnichannel.ts` `ChannelType` += `'WEBCHAT'` |
| Connect wizard | `components/platform/channel-connect-wizard/channel-connect-wizard.tsx` - a WEBCHAT branch inside the EXISTING state machine that skips the OAuth and page steps and asks for name + workspace + origins |
| Origins editor | `app/(protected)/omnichannel/settings/embed/origins-editor.tsx` - REUSED as-is by the wizard and the Widget tab (moved to `components/platform/` only if the import direction demands it; behaviour unchanged) |
| Snippet card | `.../settings/embed/snippet-card.tsx` + `copy-field.tsx` - REUSED for the install snippet |
| Widget tab | `app/(protected)/omnichannel/settings/channels/components/channel-widget-tab.tsx` (new) + the `tabs` array in `use-channel-form.tsx` |
| Composer | `components/platform/conversation-drawer/composer.tsx` - no new prop: the existing `capabilities` prop plus `reengageMode === 'none'` already suppresses the lock and the banner |
| Panel | `app/(public)/public/webchat/[widgetKey]/page.tsx` + `components/platform/webchat-panel/` (launcher, header, transcript, pre-chat, composer, quick replies) |
| Services | `services/webchat-service.{ts,mock,real}.ts` (admin), `services/webchat-visitor-service.{ts,mock,real}.ts` (visitor, no-auth `publicFetch` + Bearer visitor token) |
| Hooks | `hooks/use-webchat-config.ts`, `hooks/use-visitor-chat.ts` (session, transcript, send, WS + poll fallback) |
| Workflow catalog | `lib/workflow-catalog.ts` - one option on the existing `channelType` field |

Reused unchanged: `components/platform/{resource-list,resource-form,search-select,status-badge,
action-menu,clamped-text}`, `lib/branding-tokens.ts`, `lib/motion.ts`, `lib/toast.ts`,
`hooks/use-can.ts`, `hooks/use-datetime.ts`.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D-A7B-1 | Web chat is a channel TYPE on the A7a spine: one `ADAPTERS` row, one `POLICIES` row, one `CAPABILITIES` row, one `channel_addressing` branch. No parallel "live chat" model, no second conversation table, no second inbox | A7a paid for exactly this. A second model would fork the inbox, the reports, the workflow triggers and the gateway. The only genuinely new thing here is the public visitor surface |
| D-A7B-2 | **Loader (vanilla JS served by FastAPI) + panel (React, Next public route in an iframe).** No React, no framework and no build step in the loader; no chat UI in the backend | The chat UI must reuse the design system, brand tokens, responsive rules and Vitest harness - that means Next. The loader must run inside arbitrary customer pages - that means tiny, dependency-free and framework-free. An iframe gives style isolation both ways and prevents the host page's JavaScript from reading the transcript out of the DOM |
| D-A7B-3 | The loader is a real, hand-written file (`modules/omnichannel/widget/loader.js`) served with two plain string substitutions, NOT a bundler target and NOT a Python string | A bundler target adds a build artifact the backend has to ship; a Python string is untestable and unreadable. The loader's logic is thin enough that pytest covers the SERVED response (headers, caching, substitution, 404s) and the recorded browser journey covers the behaviour |
| D-A7B-4 | **No cookie anywhere.** The visitor token lives in the PANEL's own `localStorage` and travels as an `Authorization: Bearer` header | A cookie set by the panel is a third-party cookie in the host page's context: blocked by Safari ITP and by Chrome's phase-out, so it would fail exactly where it matters. Partitioned `localStorage` gives the semantics we actually want (a visitor identity per website). And because there is no ambient credential, the public API has NO CSRF surface at all - which removes an entire class of bug from an unauthenticated write endpoint |
| D-A7B-5 | The visitor token is a signed JWT (`typ="webchat"`, 30 day expiry, sliding renewal inside the last 7 days) bound to tenant + channel + visitor id + contact id. Mass revocation is a per-channel `widget_token_epoch` integer compared on every use. There is NO visitor-token table | A table would need writes on every page view of every customer website - the highest-volume, lowest-value write in the system. A signed token plus an epoch counter gives issuance, expiry, binding and a "sign out all visitors" button for one integer column |
| D-A7B-6 | Rotating the widget SECRET does not bump the epoch, and bumping the epoch does not rotate the secret. They are two separate admin actions | They answer two different questions ("the host's signing key leaked" vs "sign every visitor out"). Coupling them means an admin rotating a signing key silently drops every live chat |
| D-A7B-7 | The contact and its identity are created LAZILY, on the visitor's FIRST message - never at session start | Otherwise every page view of a busy website creates a contact row, and the Contacts list, the segments, the dashboard counts and the reports all become noise within a day. It also makes the cheapest public endpoint (session start) a pure read |
| D-A7B-8 | **A web chat visitor NEVER auto-stitches onto an existing contact from self-declared pre-chat data.** Pre-chat email / phone are written onto the visitor's OWN contact only, and only into fields that are empty | This is the sharp edge of the whole slice. Anyone can type a known customer's email into a pre-chat box; stitching on it would hand a stranger that customer's entire WhatsApp history through the widget. A7a's D-A7-4 refused merging on weaker grounds (no data); here we refuse on stronger ones (attacker-controlled data). Manual merge stays BL-SS-113 |
| D-A7B-9 | The ONLY sanctioned stitch is a **host identity assertion**: `{ userRef, hash }` where `hash` is HMAC-SHA256 of `userRef` keyed by the channel's own widget secret. Valid -> identity `host:<userRef>`. Missing or invalid -> silently ignored, session continues anonymously | This is the Intercom-style identity-verification contract and it is the only version that is safe: the customer's SERVER vouches for the identity with a secret the browser never has. Silent ignore (not an error) keeps the visitor experience intact when a customer misconfigures their hash - the failure is an admin problem, not a visitor's |
| D-A7B-10 | The widget secret is **per channel**, Fernet-encrypted in the channel's existing `credentials_json`, revealed exactly once at connect and once per rotation | Reusing the plan-11H tenant-level `embedSecret` would couple web chat to a different feature's lifecycle and would give one secret authority over two unrelated surfaces. Per-channel matches where the allowed-origin list already lives |
| D-A7B-11 | Allowed origins are enforced **server-side at session start** (a mismatch returns the uniform 404, never a 403) and again as `Content-Security-Policy: frame-ancestors` on the panel document. CORS echoes the exact allowlisted origin, never `*`, always with `Vary: Origin` | A 403 confirms the channel exists to an attacker who copied a snippet; a 404 tells them nothing. `frame-ancestors` is the mechanism for clickjacking here because `X-Frame-Options` cannot express a list |
| D-A7B-12 | The loader `.js` is origin-agnostic, cacheable (`max-age=300`) and carries no secret, no tenant slug, no tenant name, no branding and no origin list. All real configuration comes from the session endpoint, which enforces the origin | Varying a cacheable asset by `Origin` is a cache-poisoning footgun and CDNs get it wrong. Put the gate on the uncacheable endpoint and the asset stays boring |
| D-A7B-13 | `_validate_origin` / `_validate_origins` are MOVED verbatim into `modules/omnichannel/origins.py` and re-imported by `embed_config_service.py` | Two origin validators in one module is exactly how a security control drifts. This is the same pure-move discipline A7a used for `meta_graph.py`, with the same rule: if a coder finds itself editing an embed test, the move stopped being pure |
| D-A7B-14 | **Exact origins only in v1** - wildcard subdomains (`https://*.acme.com`) are rejected, as they are today | The existing validator rejects `*` deliberately, with a comment explaining that a wildcard fed into `frame-ancestors` silently broadens who may embed. Loosening it here would loosen it for the embed feature too. respond.io supports wildcards; we backlog it as its own considered change (BL-SS-162) |
| D-A7B-15 | **Realtime reuses the EXISTING conversation WebSocket** with a third principal type, plus a fail-closed projection on the relay. No SSE, no long-poll transport | The socket already authorizes tokens, subscribes the workspace room and filters frames per contact for thread-scoped embed tokens. A visitor is precisely a thread-scoped principal. SSE would be a third transport with its own proxy-buffering failure modes and zero reuse |
| D-A7B-16 | The poll FALLBACK is the same `GET /messages?after=` endpoint that serves history. There is no separate polling endpoint | The panel needs history on open anyway. One endpoint means one authorization path and one projection call site |
| D-A7B-17 | **`visitor_projection` is a fail-closed allowlist** and the single chokepoint. It emits `{id, direction, text?, media?, quickReplies?, createdAt, status}` and the AGENT DISPLAY NAME CONFIGURED ON THE CHANNEL - never a real user name, never an email, never an assignee, never a tag, lifecycle, custom field, close reason or internal note. An unknown message kind or frame type is DROPPED | The workspace realtime room carries every contact's frames and the internal `MessageItem` carries staff PII. This module is the reason a visitor cannot see either. The house has leaked staff emails through an unscoped stored-id resolution twice (status-engine notifications, then the gateway); a public browser surface is where that becomes unrecoverable |
| D-A7B-18 | Messaging window: `WindowPolicy("WEBCHAT", 0, None, "none")`, and `authorize` gains ONE branch - `reengage_mode == "none"` is always allowed. The composer is never locked, no window banner renders, and `window_expires_at` stays NULL on web chat identities | There is no provider policy to encode. A reply to a visitor who left is not a violation, it is a message that will be delivered when they return. Faking a window would lock agents out of their own inbox for no reason, and would break A5's Ask-a-Question on the one channel where it works best |
| D-A7B-19 | Instead of a window, the drawer shows a neutral presence marker from a new `contact_channel_identities.last_seen_at`, exposed as `ThreadItem.visitorLastSeenAt` (and therefore on both gateway shapes, per the losslessness rule) | An agent needs to know the visitor closed the tab; that is a presence fact, not an authorization fact. One nullable column, meaningless-and-NULL for existing channel types, so no backfill |
| D-A7B-20 | **Visitor uploads are DISABLED in v1** - there is no upload endpoint, multipart is refused, and the panel renders no attach control. Agent-to-visitor media IS supported, delivered as a signed short-TTL URL bound to the message id | Anonymous file ingest at internet scale is the single highest-risk thing this slice could add: quota, malware, storage cost and content liability, all for an actor we cannot identify. Removing the endpoint removes the whole class. BL-SS-160 |
| D-A7B-21 | Visitor text is capped at 4096 characters with a typed 422; the server never truncates. The request body has a capped read | Matches the existing WhatsApp body cap so one constant governs both, and a cap that silently truncates loses a customer's actual words |
| D-A7B-22 | Own throttle bucket `THROTTLE_SCOPE_WEBCHAT` with TWO key namespaces (`ip:<ip>` and `v:<visitorId>`), enforced before any database work on both public endpoints | The form-engine precedent (never share the login bucket). Two namespaces because one abusive visitor behind a corporate NAT must not throttle a whole office, and one abusive IP must not be evaded by minting fresh visitor ids |
| D-A7B-23 | Pre-chat is a FIXED set of toggles (ask name / ask email / ask phone) plus an always-rendered off-screen honeypot. It is NOT a form-engine form | A form-engine form here would be authorable into states that make no sense in a 320px chat bubble (computed fields, tables, file uploads, pages) - a foolproof-UI violation - and it would double-store the visitor's name and email outside the contact record that A1 already owns. BL-SS-161 if a customer ever needs richer capture |
| D-A7B-24 | Online / offline comes from the EXISTING `BusinessHoursService`; an unconfigured workspace resolves ONLINE. Offline changes only which greeting the panel shows - the message travels the identical path | A separate "offline message" entity would be a second inbound path that has to be re-implemented in reports, workflows and the gateway. The honest difference between online and offline is one string |
| D-A7B-25 | The public path carries the **widget key only**, no tenant slug: `/public/omnichannel/webchat/{widgetKey}/...` and `/public/webchat/{widgetKey}` on the frontend (still under a LITERAL `public/` segment) | The form engine puts the tenant slug in the path because a form slug is human-authored and only unique per tenant. A widget key is machine-minted, globally unique and unguessable, so it needs no disambiguator - and a tenant slug pasted into every customer website's page source is a white-label leak. Deviation from the form-engine shape, flagged in section 9 |
| D-A7B-26 | Visitor-authored text is NEVER rendered as HTML - text nodes only, in the panel AND in the agent inbox; links are linkified only after scheme validation | The only untrusted-content renderer in the product. This is the house anti-SSTI line applied on the client: no `dangerouslySetInnerHTML`, no markdown-to-HTML, no raw value into `href`/`src` |
| D-A7B-27 | The loader sets `iframe.style.*` properties directly. It injects NO `<style>` element and NO stylesheet into the host page | The no-raw-CSS hard-fail governs components and pages in the Next app. A served browser artifact that must position one iframe on an arbitrary third-party page cannot use Tailwind at all. Stated here so a reviewer does not read the loader as a hard-fail |
| D-A7B-28 | NO new permission keys. `channels.read` / `channels.manage` / `conversations.*` cover every gated endpoint | A new channel type is not a new resource. No grant sweep, no silent 403 for existing tenants - the cheapest possible answer to Definition-of-Done gate item 4 |
| D-A7B-29 | Web chat has NO dev-safe stub and needs none: the far side is our own backend. `_is_dev` is never consulted for `WEBCHAT`, and the E2E journeys run fully live | Every other channel needs a stub because a provider is unavailable offline. This one is the first channel where the recorded browser evidence exercises the real production path end to end |
| D-A7B-30 | Multi-tab needs no coordination in v1: same top-level site means the same partitioned storage, the same token, the same thread and two sockets in the same room | A leader-election / BroadcastChannel scheme is real complexity for a duplicate-socket cost that is one connection per open tab |
| D-A7B-31 | Transcript email to the visitor is OUT of scope | It needs a verified address (we have none) and an outbound email channel (A7d). Sending mail to an unverified, visitor-typed address from a tenant's domain is a deliverability and abuse problem, not a feature. BL-SS-163 |
| D-A7B-32 | Module Alembic `0021` and manifest `0.10.0`, both as LABELS. NOT `1.0.0` | The repo versions this module as `0.x` with one minor per slice (`0.7.0` A5, `0.8.0` A7a, `0.9.0` A6). `1.0.0` would falsely signal an API stability commitment and would waste the only major bump the module gets. `app/models/module.py parse_version` is tuple-based, so `0.10.0 > 0.9.0` orders correctly everywhere (`AppStoreService.update`, `requires_version`, the store's "update available" flag) - a lexical comparison would not, and there is none |

## 4. Slices (build order)

Each slice is sized for ONE Sonnet coder in the `s34` lane, sequential on the same branch. Thinnest
end-to-end first: **a visitor sends text, an agent sees it, the agent replies, the visitor sees it**
is complete at the end of S3, before pre-chat, business hours, identity assertions or the gateway.

| Slice | Content | Size | ACs |
|---|---|---|---|
| **S0 FE mock** | `ChannelType` += `WEBCHAT`, the `lib/channel-capabilities.ts` record, the wizard's WEBCHAT branch (name + workspace + origins, reusing `origins-editor`), the channel-form Widget tab (appearance, greetings, pre-chat toggles, snippet via the existing `snippet-card`, rotate-secret dialog), tab filtering, list Type badge + filter, composer behaviour under `reengageMode: 'none'`, `webchat-service` mock, vitest, agent-browser smoke at 375 + 1280 | L | 01-11 |
| **S1 BE type + config + loader** | `WebChatAdapter` skeleton + registry row, policy + capability rows + the `authorize` `"none"` branch, `channel_addressing` branch, the four model columns + migration `0021` + `create_schema_and_tables` mirrors, the `origins.py` pure move, `webchat/connect` + widget config routes + secret mint/rotate + epoch bump, `loader.js` + its route with headers, caching and the uniform 404, pytest | L | 12-22 |
| **S2 BE public visitor API** | `webchat_auth` (mint, verify, binding, epoch, sliding renewal), `THROTTLE_SCOPE_WEBCHAT` + settings + service methods, the public router (session, POST messages, GET messages), origin enforcement + uniform 404 + CORS, size cap + capped read + honeypot + no-multipart, lazy contact creation, `WebChatAdapter.parse_inbound` into the UNCHANGED `InboundService`, `webchat_projection` (fail-closed), pytest | L | 23-35 |
| **S3 BE outbound + realtime** | `WebChatAdapter.send` (no I/O, SENT in-run), `send_runner` wiring, the WS third principal + projected relay, the poll fallback contract, signed media URL for agent media, `last_seen_at` stamping + `visitorLastSeenAt` on `ThreadItem`, the drawer presence marker, pytest | M | 36-43 |
| **S4 FE panel** | `app/(public)/public/webchat/[widgetKey]/page.tsx` + `components/platform/webchat-panel/`, `webchat-visitor-service` trio, `use-visitor-chat` (session, WS, poll fallback, storage-unavailable fallback), quick replies, branding tokens from the session response, `frame-ancestors`, text-node-only rendering, the loader postMessage contract, vitest, 375 + 1280 | L | 44-51 |
| **S5 BE hours + pre-chat + identity** | `online` via `BusinessHoursService`, offline greeting, pre-chat write-if-empty, host identity assertion verify + `host:<userRef>` identity + silent ignore on failure, dev seed `chn-demo-web`, manifest bump, pytest | M | 52-57 |
| **S6 Gateway, guide, workflow, A6 row, wire-up, E2E** | `webchat:` `to` prefix, widened `channelType` + `visitorLastSeenAt` on both shapes, **the consumer-guide diff**, the workflow `channelType` option (backend + catalog), the `SOURCE_TO_CHANNEL_TYPE` row, mock-to-real swap at the one service boundary per trio, recorded agent-browser evidence at 375 + 1280, Test Execution Report keyed to the AC ids | M | 58-66 |
| **Review** | `reviewer` agent on **Opus** (a new unauthenticated public surface, a token scheme, a cross-origin embed, a fail-closed projection guarding staff PII), then `/codex-review` | - | - |

S2 is the load-bearing slice. If it needs splitting: **S2a** = tokens, throttle, session endpoint,
origin enforcement, uniform 404 (ACs 23-25, 27-30); **S2b** = message post, honeypot, caps, lazy
creation, `parse_inbound`, projection, history read (ACs 26, 31-35).

## 5. Contracts

### 5.1 Admin API (camelCase, datetimes Z-suffixed via `ApiModel`)

```
POST  /omnichannel/onboarding/webchat/connect                       channels.manage
        { name, workspaceId, allowedOrigins: string[] }
        -> 201 ChannelItem & { widgetSecret }        (secret revealed ONCE)
GET   /omnichannel/channels/{id}/widget                             channels.read
        -> WebchatConfig                             (never carries the secret)
PUT   /omnichannel/channels/{id}/widget                             channels.manage
        -> WebchatConfig
POST  /omnichannel/channels/{id}/widget/rotate-secret               channels.manage
        -> { widgetSecret }                          (revealed ONCE; epoch unchanged)
POST  /omnichannel/channels/{id}/widget/sign-out-visitors           channels.manage
        -> { tokenEpoch }                            (secret unchanged)

ChannelItem   += { widgetKey: string|null }
WebchatConfig  = { widgetKey, allowedOrigins: string[], tokenEpoch,
                   appearance: { accentColor, position: 'left'|'right',
                                 headerTitle, agentDisplayName },
                   greeting, offlineGreeting,
                   preChat: { askName, askEmail, askPhone },
                   snippet: string }
```

Typed 409: `channel_type_unsupported` (templates / profile on a WEBCHAT channel, the A7a rule).
422 bodies keep the house `{fieldErrors: {path: message}}` shape.

### 5.2 Public visitor API (unauthenticated; `Authorization: Bearer <visitor token>` after session)

```
GET   /omnichannel/widget/{widgetKey}.js                            public, cacheable 300s
        200 application/javascript; nosniff; ETag
        404 uniform, for every failure mode

POST  /public/omnichannel/webchat/{widgetKey}/session               public
        headers: Origin (REQUIRED, must be allowlisted)
        body:    { token?: string, identity?: { userRef, hash } }
        -> 200 { token, expiresAt, visitorId,
                 config: { appearance, greeting, offlineGreeting, preChat,
                           agentDisplayName, tenantName, brandTokens },
                 online: boolean,
                 messages: VisitorMessage[] }        (history when the token resolves a contact)
        -> 404 uniform  (unknown key | inactive | module off | tenant blocked | bad origin)
        -> 429 with Retry-After

POST  /public/omnichannel/webchat/{widgetKey}/messages              public + Bearer
        body: { text: string (<=4096), preChat?: { name?, email?, phone? }, hp?: string }
        -> 201 VisitorMessage
        -> 200 { ok: true } with NOTHING stored when hp is non-empty (honeypot)
        -> 401 invalid/expired/wrong-channel/epoch-revoked token (one indistinguishable body)
        -> 422 text_too_long | unsupported_content
        -> 429 with Retry-After

GET   /public/omnichannel/webchat/{widgetKey}/messages?after=&limit= public + Bearer
        -> 200 { data: VisitorMessage[], nextAfter: string|null }

WS    /omnichannel/ws?workspaceId=<id>&token=<visitor token>         existing route
        relays ONLY visitor_frame(...) output for this visitor's contact

VisitorMessage = { id, direction: 'in'|'out', text: string|null,
                   media: { url, mimeType, name }|null,
                   quickReplies: { id, title }[]|null,
                   agentName: string|null,          // the CHANNEL's configured display name only
                   createdAt, status: 'sent'|'delivered'|'read'|'failed'|null }
```

CORS on the two `/public/...` routes: `Access-Control-Allow-Origin` echoes the exact allowlisted
origin, `Vary: Origin`, `Access-Control-Allow-Headers: authorization, content-type`, no
`Allow-Credentials` (there is no cookie). The panel document is served with
`Content-Security-Policy: frame-ancestors <allowed origins>`.

### 5.3 The install snippet (what a customer pastes)

```html
<script src="https://app.example/omnichannel/widget/wk_a1b2c3d4e5f6a7b8c9d0e1f2" async></script>
```

Optional, for a customer who authenticates their own users (D-A7B-9):

```html
<script>
  window.fxChatIdentity = { userRef: "user-1234", hash: "<HMAC-SHA256(userRef, widgetSecret)>" };
</script>
```

The hash is computed on the customer's SERVER. The loader exposes `open()`, `close()`, `isOpen()`
and `identify({userRef, hash})` on a single global, and validates the origin of every inbound
`postMessage` before acting on it.

### 5.4 Tables and columns

```
channels  += widget_key        String NULL, index
                               + PARTIAL UNIQUE (widget_key)
                                 WHERE widget_key IS NOT NULL AND is_trashed = false
          += widget_config_json JSON(none_as_null=True) NULL
          += widget_token_epoch Integer NOT NULL DEFAULT 0

contact_channel_identities
          += last_seen_at      UTCDateTime NULL
```

No backfill is required: all four are new, empty-until-used, and meaningless for existing channel
types. The `create_schema_and_tables` `ADD COLUMN IF NOT EXISTS` mirror is mandatory (`create_all`
never ALTERs an existing table).

### 5.5 The window policy row and the third `authorize` branch

```python
POLICIES["WEBCHAT"] = WindowPolicy("WEBCHAT", 0, None, "none")

# in authorize(), after assert_kind_supported:
if policy.reengage_mode == "none":
    return SendDecision()          # always allowed, no Meta send parameters
```

`CAPABILITIES["WEBCHAT"] = ChannelCapabilities("WEBCHAT", document=True, sticker=False,
template=False, interactive_list=False, location=False, contacts=False, reaction_outbound=False)`,
mirrored by the parity-pinned frontend record.

### 5.6 Gateway diff (the guide MUST change in the same slice - AC-WEB-60)

```
POST /api/v1/omnichannel/messages
  to  += "webchat:<visitorId>"     resolves an EXISTING identity only, never creates
                                   (identical rule to psid: / igsid:)
read shapes: channelType now also carries WEBCHAT on BOTH shapes.
             ThreadItem/ContactObject += visitorLastSeenAt (ISO-Z, a Foundryx extension).
             cswExpiresAt / windowExpiresAt / humanAgentExpiresAt are null for a web chat
             contact - a web chat channel has no messaging window at all.
No field renamed or dropped. One data path, as today.
```

Guide edits: a changelog row dated at merge; section 4.1 gains the `webchat:` row; sections 9.1,
9.2 and 9.3 widen `channelType` and add `visitorLastSeenAt`; section 10 needs no new code
(`invalid_recipient` already covers an unresolvable `webchat:` value).

## 6. Seams verified at `sprint-4/32-channels-messenger-instagram` HEAD `e4ac64ef`

Backend (`service_backend/modules/omnichannel/`):

- `adapters/__init__.py:19` `ADAPTERS`, `:26` `get_adapter` (raises on unknown type)
- `adapters/base.py:33` `ChannelAdapter` Protocol, `:53` `send(...)` (already carries
  `messaging_type` / `tag` / `structured`), `:80` `parse_inbound`, `:20` `SendError(transient=)`
- `services/messaging_policy.py:38` `WindowPolicy`, `:50` `POLICIES`, `:57`
  `stamp_inbound_window`, `:149` `ChannelCapabilities`, `:166` `CAPABILITIES`, `:182`
  `assert_kind_supported`, `:268` `closed_window_message`, `:275` `window_open`, `:301`
  `authorize` (`:333` the template branch, `:340` the human-agent branch) - the `"none"` branch
  inserts at `:333`
- `services/channel_addressing.py:23` `sender_ref`, `:32` `recipient_ref`, `:18`
  `NoChannelIdentity`
- `services/inbound_service.py:75` `process_payload`, `:125` `_resolve_channel`, `:175`
  `_handle_message`, `:301` `stamp_inbound_window`, `:458` `_resolve_contact`, `:558`
  `_store_media`, `:587` `_store_media_from_url`
- `services/send_runner.py:108` `run_send`, `:193` `get_adapter(...)`, `:202` `sender_ref`,
  `:204` `recipient_ref`, `:211` the persisted `metaSend`, `:310` transient vs permanent
- `services/message_service.py:324` `send_message` (`:337` `actor_is_human`), `:375` / `:460` /
  `:536` / `:615` the `authorize` call sites, `:504` `send_media`, `:788` `react`
- `services/embed_config_service.py:44` `_HOSTNAME_RE`, `:53` `InvalidOrigin`, `:61`
  `_validate_origin`, `:116` `_validate_origins` - the pure move (D-A7B-13) takes exactly these
- `services/realtime.py:21` `channel_for`, `:38` `publish` (best-effort by design)
- `routers/ws.py:54` `_authorize` (native JWT branch + the plan-11H embed branch - the visitor
  branch is the third), `:139` `_event_contact_id`, `:160` `conversation_socket`, `:176`
  `forward_events` (where the projection wraps)
- `routers/media.py:88` `serve_message_media`, `:100` the signed-URL branch (`exp` + `sig`)
- `routers/onboarding.py:37` `oauth-callback`, `:55` `manual-connect`, `:72` `meta/pages`,
  `:86` `meta/connect` - the web chat connect route joins this router
- `services/public_gateway_service.py:111` `_workspace_channel`, `:153` the `psid:` / `igsid:`
  docstring, `:161` the prefix branch, `:251` `_resolve_contact`, `:680`
  `_resolve_or_create_contact`
- `services/conversation_service.py:154` `_channel_types`, `:261` `windowExpiresAt` on the thread,
  `:283` `thread_item`, `:286` `message_items`
- `models.py:103` `Channel` (`:109` `channel_type` plain String, `:116` `phone_number_id`, `:124`
  `external_account_id`), `:243` `ContactChannelIdentity` (`:250` `external_user_id`, `:258`-`:260`
  the A7a window columns, `:264` `UNIQUE(channel_id, external_user_id)`), `:805`
  `OmnichannelSettings` (`:829` `business_hours_json`)
- `bootstrap.py:54` `register_engine_entities`, `:137` `create_schema_and_tables` (the
  `ADD COLUMN IF NOT EXISTS` block), `:550` `install`, `:560` `install_tenant`, `:605`
  `update_tenant` (calls every backfill unconditionally and idempotently - no `from_version`
  comparison to get wrong), `:695` `uninstall_tenant`, `:733` `seed_demo_conversations`
- `alembic/versions/` head on this branch = `0018_omni_meta_connect_sessions`;
  `manifest.json` version `0.8.0`; `permissions/permissions.csv` already carries
  `channels.read` / `channels.manage` / `conversations.*` - A7b adds no row

Core (`service_backend/app/`):

- `models/auth_throttle.py:16-31` the scope constants (`THROTTLE_SCOPE_FORM_PUBLIC` at `:20` is the
  template for `THROTTLE_SCOPE_WEBCHAT`)
- `services/throttle.py:51` `_scope_policy`, `:60` the form-public policy row, `:248`
  `enforce_form_public` / `record_form_public` - the pair A7b mirrors
- `api/v1/forms.py:100` `public_router`, `:653` `public_form_view`, `:665` `public_form_submit`
  (`:674` throttle before any work) - the public-surface precedent
- `models/module.py:27` `parse_version` (tuple-based, so `0.10.0 > 0.9.0`),
  `services/app_store_service.py:174` the update gate, `dependencies.py:207` `requires_version`
- `security.py` `decode_access_token`; `secrets.py` `encrypt_secret` / `decrypt_secret`
- `branding/token_whitelist.py` + `lib/branding-tokens.ts` (the parity-pinned token diff the
  session response carries)

Frontend (`service_frontend/`):

- `types/omnichannel.ts:20` `ChannelType` (pruned to three by A7a - A7b adds the fourth), `:62`
  `Channel`
- `lib/channel-capabilities.ts:33` `ChannelCapabilities`, `:61` `CHANNEL_CAPABILITIES`, `:117`
  `CHANNEL_TYPES`, `:119` `channelCapabilities`
- `components/platform/channel-connect-wizard/channel-connect-wizard.tsx:36` `TYPE_OPTIONS`,
  `:56` `channelType` state, `:80` `capabilities`, `:81` `isWhatsApp`, `:111` the simulated branch,
  `:171` `selectMetaPage`, `:355` the type `SearchSelect`
- `hooks/use-connect-channel.ts:65` `ConnectState`, `:107` `useConnectChannel`
- `app/(protected)/omnichannel/settings/channels/components/use-channel-form.tsx:176-181` the
  `isWhatsApp` tab filter, `:181` the `tabs` array
- `app/(protected)/omnichannel/settings/embed/origins-editor.tsx`, `snippet-card.tsx`,
  `copy-field.tsx` - reused verbatim
- `components/platform/conversation-drawer/composer.tsx:84` `ComposerProps`, `:101`
  `capabilities`, `:343` the WhatsApp default, `:379` `extendedOpen`, `:380` `locked`, `:383`
  `showWindowMarker`, `:385` the attach filter, `:541` the template affordance
- `app/(public)/public/forms/[slug]/page.tsx` and `app/(public)/public/documents/[token]/page.tsx`
  - the two existing literal-`public/`-segment routes the panel joins
- `lib/workflow-catalog.ts` - the `omnichannel.message_received` entry and its A7a `channelType`
  field

Cross-lane state read 2026-09-07: `sprint-4/32` (A7a) took module Alembic `0017`/`0018` and
manifest `0.8.0`; `sprint-4/33` (A6) took `0017`/`0018` AND `0.8.0` as well - the two collide, so
whichever merges second renumbers to `0019`/`0020` and `0.9.0`. A7b therefore plans `0021` and
`0.10.0` as LABELS, not facts (section 9, F1).

## 7. Risks and mitigations - the reviewer's checklist

This slice ships the first unauthenticated WRITE surface in the omnichannel Service. The reviewer
(Opus) is asked to verify each of these explicitly, by test, not by reading intent.

- **R1 - a visitor sees another visitor's messages.** The workspace realtime room carries every
  contact's frames. Mitigation: BOTH the contact filter AND `visitor_projection` on the relay
  (defence in depth), plus the REST reads scoping to the token's contact id. Test: two visitors on
  one channel, assert zero cross-frames and zero cross-rows.
- **R2 - a visitor sees staff PII.** The internal `MessageItem` carries agent user names and the
  thread carries assignee, tags, lifecycle and close reasons. Mitigation: `visitor_projection` is a
  fail-closed allowlist emitting a fixed field set and the CHANNEL's configured display name only.
  Test: an internal note and an agent-authored message on the same thread; assert the note is
  absent and no user name or email appears in any visitor-visible byte.
- **R3 - identity spoofing through pre-chat.** Mitigation: D-A7B-8 - pre-chat NEVER looks up an
  existing contact. Test: an existing WhatsApp contact's email typed into pre-chat produces a NEW
  contact and returns an empty history.
- **R4 - token forgery, replay or cross-channel reuse.** Mitigation: `typ`, tenant, channel,
  visitor, contact and epoch are all checked on every use; one indistinguishable 401. Test: a token
  minted on channel A refused on channel B; an epoch bump refuses the previous token; a tampered
  signature refused.
- **R5 - CSRF.** Mitigation: there is no cookie (D-A7B-4), so there is no ambient credential to
  ride. Test: a request with no `Authorization` header is 401 regardless of any cookie present.
- **R6 - clickjacking and widget theft.** Mitigation: server-side origin allowlist at session start
  returning the uniform 404, plus `frame-ancestors` on the panel. Test: an off-list origin gets the
  same 404 as an unknown key; the panel response carries `frame-ancestors`.
- **R7 - enumeration.** Mitigation: one uniform 404 for five distinct failure modes on the loader
  route and the session route. Test: byte-compare all five responses.
- **R8 - denial of service and junk data.** Mitigation: throttle before any DB work with two key
  namespaces, lazy contact creation, a 4096-character cap, a capped body read, no upload endpoint.
  Test: the throttle fires before a row is written; a 5000-character body 422s and stores nothing.
- **R9 - stored XSS through visitor text.** Mitigation: D-A7B-26, text nodes only in BOTH the panel
  and the agent inbox. Test: a message containing `<img onerror>` renders as literal text in both
  surfaces.
- **R10 - SSRF.** There is deliberately no server-side fetch of any visitor-supplied URL in this
  slice (unlike A7a's Meta CDN branch). If one is ever added it goes behind the shared
  `assert_deliverable` host guard. The reviewer should confirm no new outbound fetch exists.
- **R11 - the `"none"` policy branch regresses WhatsApp.** Mitigation: the branch is added AFTER
  the template branch and keys off `reengage_mode`, and the entire pre-existing WhatsApp / Messenger
  / Instagram window suite must pass with zero edits (AC-WEB-14).
- **R12 - the panel route collides at build time.** A route GROUP is invisible in the URL, so
  `(public)/webchat/[widgetKey]` would collide with any protected `[id]` route on the same path
  depth. Mitigation: the literal `public/` segment, exactly as the form engine learned it.
- **R13 - a cached loader outlives a disabled channel.** Mitigation: `max-age=300` plus the
  authoritative gate on the uncacheable session endpoint - a cached loader that still runs simply
  cannot start a session.
- **R14 - browser storage unavailable.** Mitigation: an in-memory session for that tab; never a
  thrown error, never an error state shown to a visitor.
- **R15 - the origins pure move is not pure.** If a coder finds itself editing a plan-11H embed
  test, the move stopped being a move. Stop and re-plan (the A7a F8 rule).
- **R16 - migration number and manifest version collide across lanes** (section 9, F1). The coder
  re-reads `alembic/versions/` and `manifest.json` at branch time and takes the next free values.
- **R17 - new columns on existing tables.** `create_all` never ALTERs, so every new column is
  mirrored with `ADD COLUMN IF NOT EXISTS` in `create_schema_and_tables` and the deploy path is
  `bootstrap_db`, never `init_db`.
- **R18 - the E2E needs a real third-party origin.** The lane serves
  `documentation/plans/sprint-4/34-evidence/host/index.html` (a bare page carrying only the
  snippet) on `:3012`, which is a genuinely different origin from the app on `:3011`, so the
  cross-origin path is exercised for real rather than same-origin by accident. `http://localhost:3012`
  is added to the seeded channel's allowlist; the off-list journey (AC-WEB-66) uses `127.0.0.1:3012`,
  which is a DIFFERENT origin to a browser and therefore a true negative test.

## 8. Backlog candidates (register on close; provisional ids from BL-SS-160)

| Id | Title | Priority |
|---|---|---|
| BL-SS-160 | Visitor file / image uploads on web chat (anonymous ingest: per-visitor quota, sniff gate, size cap, retention, abuse controls) | Medium |
| BL-SS-161 | Pre-chat as a form-engine form (a curated subset of field types, published per channel) instead of the three fixed toggles | Low |
| BL-SS-162 | Wildcard-subdomain allowed origins (`https://*.acme.com`) for web chat AND the plan-11H embed, with the `frame-ancestors` broadening reviewed as its own change | Medium |
| BL-SS-163 | Email the visitor a transcript when the conversation closes (needs A7d email out and a verified address) | Low |
| BL-SS-164 | Visitor-side typing indicator and agent presence ("Sara is typing") over the existing realtime room | Low |
| BL-SS-165 | Multichannel launcher: WhatsApp / Messenger / Telegram deep links inside the same bubble (respond.io's "growth widget"), pairing with G21 / C2 | Medium |
| BL-SS-166 | Proactive messages: open the widget automatically on a page rule or after N seconds, authored as an A5 workflow | Medium |
| BL-SS-167 | Anonymous-visitor retention job: purge web chat contacts with no message and no host identity after N days, with a per-tenant setting (GDPR) | Medium |
| BL-SS-168 | Widget localisation: per-channel language strings for greeting, pre-chat labels and system copy | Medium |
| BL-SS-169 | Custom launcher icon upload per channel (sniff-gated, served CSP-sandboxed, reusing the branding asset route) | Low |
| BL-SS-170 | Visitor context capture (page URL, referrer, UTM, user agent) written into A1 typed contact fields at session start, with an explicit per-channel opt-in | Medium |
| BL-SS-171 | An installable npm loader package and platform install guides (WordPress, Shopify, Squarespace) mirroring respond.io's install matrix | Low |
| BL-SS-172 | Rate-limit the loader route at the edge and add a per-channel session-creation ceiling, once real traffic exists | Low |

## 9. Flagged for the user

- **F1 - the migration number and the manifest version are labels, not facts.** `0021` and `0.10.0`
  assume A7a and A6 both merge first, and those two lanes currently BOTH claim `0017`/`0018` and
  `0.8.0`, so one of them renumbers regardless. The coder takes the next free values at branch time.
  `1.0.0` is deliberately NOT taken (D-A7B-32).
- **F2 - the public path carries the widget key only, not the tenant slug** (D-A7B-25). This is a
  deliberate deviation from the form-engine precedent quoted in the brief. The reason is
  white-label: the snippet lives in the page source of the customer's public website, and a tenant
  slug there tells every visitor which Foundryx tenant they are talking to. The key is machine-minted
  and globally unique, so it needs no disambiguator, and the uniform-404 rule is unchanged.
- **F3 - `Content-Security-Policy: sandbox` is NOT set on the loader `.js`** (the brief suggested a
  sandbox-style header). CSP `sandbox` applies to a DOCUMENT, not to a subresource: setting it on a
  script response does not sandbox the script inside the host page, so it would be security theatre.
  The correct controls are used instead: `nosniff` plus an exact content type on the asset, the
  server-side origin allowlist on the session endpoint, and `frame-ancestors` on the panel document
  (which IS a document, and where the sandbox precedent genuinely belongs).
- **F4 - visitor uploads are off in v1** (D-A7B-20). A visitor cannot send a screenshot, which is a
  real support-workflow gap and the most likely first complaint. Flagging the consequence, not
  asking to change it: anonymous file ingest needs its own quota, retention and abuse design
  (BL-SS-160), and shipping it inside the same slice as a brand-new public surface doubles the
  review risk.
- **F5 - a web chat contact is a SEPARATE contact from the same person's WhatsApp contact** unless
  the customer implements a signed host identity assertion (D-A7B-8 / D-A7B-9). This is visible in
  the Contacts list, in segments, in broadcast audiences and in the dashboard counts, exactly as
  A7a's F3 flagged for Messenger. Auto-merging on visitor-typed data is unrecoverable if wrong, and
  here the data is attacker-controlled rather than merely weak.
- **F6 - there is no messaging window on web chat at all** (D-A7B-18). An agent can always compose,
  including to a visitor who closed the tab twelve days ago; the message is delivered when and if
  they return. The drawer shows a presence marker rather than a lock. If a customer expects the
  composer to lock when a visitor leaves, that is a product decision to take explicitly, not a
  policy we can point at a provider for.
- **F7 - the E2E journeys are fully live, with no stub anywhere** (D-A7B-29). That is a genuine
  quality gain over every previous channel slice, and it means the recorded evidence is proof of
  the production path rather than of a simulation. It also means the lane needs the extra static
  host-page server on `:3012` (section 7, R18).
- **F8 - the loader is hand-written JavaScript with no unit tests**, covered by pytest at the
  response level and by the recorded browser journeys at the behaviour level (D-A7B-3). If the
  loader grows past roughly 150 lines, that trade stops being honest and it should become a real
  build target with its own test harness.
- **F9 - a visitor's history survives for 30 days on a shared computer.** The token lives in
  partitioned `localStorage` with a 30-day expiry, so the next person using the same browser
  profile on the same website resumes the same conversation. This is the industry-standard
  behaviour (it is what makes "continue where you left off" work) and the widget offers no
  "end chat and forget me" control in v1. Raising it because it is a privacy property a customer
  may want to change, not a defect.

## 10. Sources

- respond.io website chat widget overview (theme colour, icon, position, header title / tagline /
  logo, popup message, pre-chat form, input placeholder, font):
  https://respond.io/help/website-chat-widget/website-chat-widget
- respond.io website chat widget quick start (Settings > Channels > Website Chat > Connect; the
  generated script snippet pasted before `</body>`; domain whitelisting prevents display on
  unauthorised domains): https://respond.io/help/website-chat-widget/website-chat-widget
- respond.io website domains behaviour (an unlisted website does not load the widget;
  `https://*.respond.io` whitelists subdomains plus the root, `https://respond.io` whitelists only
  the root): https://docs.respond.io/messaging-channels/website-chat-widget
- respond.io widget JavaScript API and user identification (open / close / is-open, opened and
  closed callbacks; a passed identifier matched to an existing contact resumes the conversation;
  contact fields can be sent at creation):
  https://developers.respond.io/docs/website-chat-widget/iobv5j9au5o6w-website-chat
- respond.io pre-chat survey (collect contact information before the chat starts, configured per
  channel): https://respond.io/blog/pre-chat-survey
- respond.io WordPress install guide (logged-in users identified, conversation resumed on match):
  https://docs.respond.io/messaging-channels/website-chat-widget/install-on-wordpress
- respond.io channel catalogue including "Live Chat (Website Chat, custom)" - the parity target:
  `documentation/plans/sprint-4/24-evidence/respondio-survey/set-channels.png`
