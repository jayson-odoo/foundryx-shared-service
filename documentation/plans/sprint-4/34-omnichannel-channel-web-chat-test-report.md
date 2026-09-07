# Sprint 4 · Plan 34 (A7b) - Omnichannel channel: website chat - Test Execution Report

**Repo/branch:** `foundryx-shared-service` @ `sprint-4/34-channel-web-chat` (worktree `.claude/worktrees/s34`).
**Date:** 2026-09-08. **Lane:** backend `:8014` (DB `foundryx_service_s34`), frontend `:3012` (prod build), static E2E host page on `:3013`.
**This report covers S0-S6 (all 66 ACs).** S0-S5 rows are carried forward from their own commit bodies (`git log -1 <hash>` on this branch) - re-verified only where S6's own work touches the same surface (the mock-to-real flip, the gateway, the guide, the workflow filter, and the full E2E). S6 rows (58-66) are freshly executed this pass.

## Suites executed this pass (S6)

| Suite | Command | Result |
|---|---|---|
| Backend - new gateway/webchat tests | `pytest -q tests/test_omnichannel_gateway_webchat.py` | **9 passed** |
| Backend - pinned selector suite (regression) | `pytest -q tests/test_omnichannel_gateway_channel_selector.py` | **22 passed** (1 pinned assertion updated to include `WEBCHAT`) |
| Backend - full send/capabilities suite (regression) | `pytest -q tests/test_omnichannel_channels_send.py` | **65 passed** |
| Backend - webchat regression bundle | `pytest -q tests/test_omnichannel_webchat_public.py tests/test_omnichannel_webchat_outbound.py tests/test_omnichannel_channels_webchat.py tests/test_omnichannel_webchat_hours_prechat_identity.py tests/test_omnichannel_api_gateway.py tests/test_omnichannel_webchat_frame_policy.py` | **162 passed** |
| Backend - respond.io channel map (regression) | `pytest -q tests/test_omnichannel_respondio_migration.py -k channel_map` | **2 passed** |
| Frontend - webchat/composer/wizard/channel-form vitest bundle | `npx vitest run hooks/use-connect-channel.test.ts components/platform/webchat-panel/ hooks/use-visitor-chat.test.ts components/platform/conversation-drawer/composer.channels.test.tsx components/platform/channel-connect-wizard/channel-connect-wizard.test.tsx "app/(protected)/omnichannel/settings/channels/components/use-channel-form.channels.test.tsx" components/platform/conversation-drawer/conversation-drawer.test.tsx services/webchat-visitor-service.mock.test.ts services/webchat-service.mock.test.ts` | **105 passed** (12 files) |
| Frontend - lint (touched files) | `npx eslint services/webchat-service.ts services/webchat-visitor-service.ts types/omnichannel.ts components/platform/conversation-drawer/composer.tsx lib/channel-capabilities.ts` | **0 errors** (2 pre-existing a11y warnings, unrelated) |
| Frontend - prod build | `rm -rf .next && npm run build` | **clean**, all routes compiled incl. `/public/webchat/[widgetKey]` |
| E2E - live cross-origin embed | `agent-browser` recorded run, real clicks, 375px + 1280px | **PASS with ONE CRITICAL DEFECT FOUND** - see AC-WEB-66 and BL-SS-183 |
| E2E - re-record after the BL-SS-183 fix (2026-09-09) | `agent-browser` recorded run, real clicks, 375px + 1280px, `34-evidence/S6-fix/` | **PASS** - allowlisted host origin chats, off-list origin injects nothing, direct panel navigation is blank and starts nothing |

Machine-budget note: no whole-repo `pytest`/`vitest` run this pass (lane rule) - only the files above, one invocation at a time.

## CRITICAL FINDING - RESOLVED 2026-09-09 (read this before the AC table)

**Resolution.** Fixed on this branch by `fix(omnichannel): plan 34 loader-minted web chat session -
closes BL-SS-183`: the LOADER (vanilla JS in the customer's own top-level document) now mints the
session, keeps the visitor token in the HOST page's `localStorage` namespaced per widget key, and
hands the whole session to the panel over `postMessage` with the exact panel origin as target; the
panel never starts a session, never stores a token, and renders NOTHING without one (a directly
navigated panel URL is a blank document that starts nothing server-side). `POST /session` keeps the
channel allowlist - now decidable, because the caller's `Origin` really is the embedding website's
and is unforgeable from another site - plus the uniform 404. The Bearer-authed message routes are
the panel's own calls and echo only the app's own origin. The `/public/omnichannel/webchat/` prefix
answers its own CORS preflight, since a customer origin lives on the CHANNEL allowlist and never in
the service's `CORS_ORIGINS` env (Starlette's `CORSMiddleware` would otherwise reject the loader's
preflight `400 Disallowed CORS origin`). Re-recorded evidence: `34-evidence/S6-fix/README.md` -
AC-WEB-66's first half now passes for the RIGHT reason, with the app's own origin never added to the
channel's allowlist. New regression tests pin WHO may send which origin (a session start carrying
the PANEL's own origin is the uniform 404) instead of setting `Origin` freely on the test client.
Backend re-run after the fix: `test_omnichannel_webchat_public.py` **39 passed**,
`test_omnichannel_channels_webchat.py` **27 passed**,
`test_omnichannel_webchat_hours_prechat_identity.py` **18 passed**,
`test_omnichannel_webchat_outbound.py` **12 passed**,
`test_omnichannel_webchat_frame_policy.py` **6 passed**,
`test_omnichannel_gateway_webchat.py` **9 passed**. Frontend: `use-visitor-chat.test.ts` **12**,
`lib/webchat-panel-bridge.test.ts` **8**, `components/platform/webchat-panel/` **19**,
`services/webchat-visitor-service.mock.test.ts` **6**.

The original finding, kept for the record:

**BL-SS-183.** The web chat origin allowlist (D-A7B-11, AC-WEB-23/24) cannot discriminate between
customer websites in a real browser: the panel's own `fetch()` call to `/session` always carries
`Origin: <the panel's own deployed origin>` (e.g. `http://localhost:3012` in this lane), never the
top-level host page's origin, because the fetch executes from JS running inside the panel's OWN
iframe document - this is web-platform behavior, not a lane artifact. Reproduced live: the channel's
genuinely-ALLOWED origin `http://localhost:3013` gets the identical uniform 404 as an intentionally
off-list origin (`curl -H "Origin: http://localhost:3013"` -> 200, `curl -H "Origin: http://
localhost:3012"` -> 404; a live HAR capture of the real browser embed shows the SAME 404 on the
identical request). The only origin value that can ever pass this check is the panel's own origin -
once that is added to a channel's allowlist (which S6's own E2E had to do to exercise anything past
session-start), the "allowlist" no longer restricts embedding to any particular customer site at
all, and `frame-ancestors` CSP (which DOES still work correctly) is moot for a visitor who navigates
directly to the panel URL instead of through an iframe. Full repro, curl transcript and screenshots:
`34-evidence/S6/README.md` (steps 9, 18-19) and BL-SS-183 in `documentation/backlogs/backlog.md`.
This was introduced in S2 and is invisible to the existing pytest suite (which sets the `Origin`
header directly on the test client - something a real browser can never be told to do for a
same-document fetch); it surfaced only now because D-A7B-29/F7 makes this the first channel whose
E2E is fully live with no stub. **Recommend the security reviewer treat this as the top-priority
item** and that the fix (loader-side session mint + postMessage relay, or an `event.origin`-derived
explicit field) land as its own hotfix slice before this channel ships to a real customer.

## AC results

Legend: **PASS** · **DEFERRED** (covered/authored, not independently re-executed this pass) · **FAIL/BLOCKED**.

### Slice S0 - Frontend mock (01-11), commit `07f89b84`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-01 | Wizard channel-type `SearchSelect` offers Web chat | PASS | S0 commit; re-verified live in S6 E2E (wizard screenshot 01) |
| AC-WEB-02 | Web chat connect step reuses the existing origins control | PASS | S0 commit; re-verified live in S6 E2E (wizard screenshot 01) |
| AC-WEB-03 | `WEBCHAT` detail form tabs = Configuration/Widget/Webhooks | PASS | S0 commit; re-verified live in S6 E2E (channel detail tabs) |
| AC-WEB-04 | Widget tab on the resource-form section pattern | PASS (per S0 commit) | Vitest `webchat-service.mock.test.ts`/channel-form tests |
| AC-WEB-05 | Install snippet via the existing snippet-card | PASS | S0 commit; re-verified live in S6 E2E (screenshot 05) |
| AC-WEB-06 | Rotate widget secret action | PASS (per S0 commit) | `webchat-service.mock.test.ts::rotateSecret` |
| AC-WEB-07 | `lib/channel-capabilities.ts` `WEBCHAT` record | PASS | Confirmed present, `reengageMode: 'none'`, used by S6's composer/window-marker checks |
| AC-WEB-08 | Composer behavior under `reengageMode: 'none'` | PASS | S0 commit; re-verified live in S6 E2E (composer never locked, screenshots 11-13) |
| AC-WEB-09 | Channels/inbox/contacts lists show Web chat badge | PASS | Re-verified live in S6 E2E (screenshots 03, 04, 10) |
| AC-WEB-10 | `webchat-service` trio (mock at S0) | PASS (superseded) | S0 shipped the mock; S6 flips the boundary (AC-WEB-63) |
| AC-WEB-11 | 375/1280 non-clipped | PASS (per S0 commit) | Re-verified at both widths in S6 E2E |

### Slice S1 - Backend type + config + loader (12-22), commit `efdcf026`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-12 | `ADAPTERS["WEBCHAT"]` registry row | PASS (per S1 commit) | `test_omnichannel_channels_send.py` |
| AC-WEB-13 | `POLICIES["WEBCHAT"]`/`CAPABILITIES["WEBCHAT"]` | PASS (per S1 commit) | `test_omnichannel_channels_send.py` (65/65 green this pass) |
| AC-WEB-14 | Pre-existing WhatsApp/Messenger/Instagram suite unaffected | PASS | `test_omnichannel_channels_send.py`, `test_omnichannel_gateway_channel_selector.py` both fully green this pass |
| AC-WEB-15 | `channel_addressing` WEBCHAT branch | PASS (per S1 commit) | `test_omnichannel_channels_send.py` |
| AC-WEB-16 | Model + migration `0021_omni_webchat` | PASS (per S1 commit) | `test_omnichannel_channels_webchat.py` |
| AC-WEB-17 | `_validate_origin`/`_validate_origins` pure move | PASS (per S1 commit) | `test_omnichannel_channels_webchat.py` |
| AC-WEB-18 | `POST .../webchat/connect` mints key+secret, reveals once | PASS | Re-verified live in S6 E2E (screenshot 02, secret shown once) |
| AC-WEB-19 | Rotate-secret leaves epoch unchanged | PASS (per S1 commit) | `test_omnichannel_channels_webchat.py` |
| AC-WEB-20 | Loader `.js` headers/caching/body | PASS | Re-verified live this pass: `curl -D-` on `/omnichannel/widget/wk_....js` - `Content-Type: application/javascript; charset=utf-8`, `X-Content-Type-Options: nosniff`, `Cache-Control: public, max-age=300`, ETag present |
| AC-WEB-21 | Uniform 404 for the five failure modes | PASS (per S1 commit) | `test_omnichannel_channels_webchat.py` |
| AC-WEB-22 | No new permission rows | PASS | `permissions.csv` diff for this branch is empty; every new S6 endpoint reused `channels.read`/`channels.manage` |

### Slice S2 - Backend public visitor API (23-35), commit `97e482ca`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-23 | Session start (the LOADER's call) returns config + token, correct CORS | **PASS** (was FAIL live; fixed 2026-09-09) | `test_omnichannel_webchat_public.py` (39 passed) + live: `34-evidence/S6-fix/README.md` step 1 and the curl block. The caller is now the loader in the host page, so the `Origin` under test is the one a real embed actually sends |
| AC-WEB-24 | Off-list/missing Origin -> uniform 404 (incl. the app's OWN origin) | **PASS** | `test_omnichannel_webchat_public.py::test_session_from_the_panels_own_origin_is_the_uniform_404` + `..._succeeds_without_allowlisting_the_app` + the message-route/preflight tests; live `34-evidence/S6-fix/README.md` steps 1, 7 |
| AC-WEB-25 | Zero rows at session start | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-26 | First message creates contact+identity, full pipeline | PASS | Re-verified live in S6 E2E (screenshots 09-10; DB row confirmed via `psql`) |
| AC-WEB-27 | Every query token-derived, cross-channel isolation | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-28 | Epoch bump revokes previous tokens | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-29 | Sliding renewal within 7 days | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-30 | Own throttle bucket, two namespaces | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-31 | 4096-char cap, capped read | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-32 | Honeypot stores nothing | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-33 | No upload endpoint, multipart refused | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-34 | History read via projection only | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |
| AC-WEB-35 | Projection fail-closed on unknown kinds | PASS (per S2 commit) | `test_omnichannel_webchat_public.py` |

### Slice S3 - Backend outbound + realtime (36-43), commit `52dee6a4`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-36 | Agent reply reaches SENT, no network call | PASS | Re-verified live in S6 E2E (screenshot 12; `psql` row `sender_type=AGENT`, real send path) |
| AC-WEB-37 | Every WEBCHAT mutation publishes | PASS (per S3 commit) | `test_omnichannel_webchat_outbound.py` |
| AC-WEB-38 | WS third principal, thread-scoped, projected | PASS | Re-verified live: visitor received the reply with NO reload (screenshot 13) |
| AC-WEB-39 | Cross-visitor isolation | PASS (per S3 commit) | `test_omnichannel_webchat_outbound.py` (2 visitors, 0 cross-frames) |
| AC-WEB-40 | Poll fallback = the same history endpoint | PASS (per S3 commit) | `test_omnichannel_webchat_outbound.py` |
| AC-WEB-41 | Signed media URL for agent media | PASS | **Newly live-fired this pass** (S4 had flagged this as not yet exercised): agent sent a real PNG, visitor's panel fetched `GET /omnichannel/media/<id>?exp=...&sig=...` (200) - screenshots 15-17, network capture |
| AC-WEB-42 | `last_seen_at` stamped, `visitorLastSeenAt` on wire | PASS | Re-verified live: drawer showed "Online now" (screenshot 11); confirmed on both gateway shapes (AC-WEB-59 tests) |
| AC-WEB-43 | Drawer presence marker, never locks composer | PASS | Re-verified live (screenshot 11-12; composer stayed enabled throughout) |

### Slice S4 - Frontend panel + loader (44-51), commit `cac5df55`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-44 | Panel route under literal `public/` segment | PASS | Build output confirms `/public/webchat/[widgetKey]`; live-verified |
| AC-WEB-45 | Loader mints the session, owns the token, mounts ONE iframe via `iframe.style` only | **PASS** (amended 2026-09-09) | `test_omnichannel_channels_webchat.py::test_loader_mints_the_session_itself_from_the_host_page`; live: exactly one `<iframe>` with inline `style.*` and no `<style>` tag, `localStorage` on the HOST page holds `fx-webchat-token:<widgetKey>` and nothing else, and an off-list origin injects NO iframe at all (`34-evidence/S6-fix/README.md` steps 1, 6, 7) |
| AC-WEB-46 | Loader global `open/close/isOpen/identify`; both sides validate every inbound frame | **PASS** (amended 2026-09-09) | Loader: origin + `iframe.contentWindow` checks, `identify()` re-mints and re-hands the session. Panel: `lib/webchat-panel-bridge.test.ts` (8 passed - source-window check, envelope check, structural session validation) and `use-visitor-chat.test.ts` (a session frame from any other window is ignored) |
| AC-WEB-47 | Greeting/pre-chat/transcript/composer, no vendor copy, `frame-ancestors`, quiet with no session | PASS | Live-verified: `curl -D-` on the panel route shows `content-security-policy: frame-ancestors http://localhost:3013`; screenshots show no "Foundryx" string anywhere. Amended 2026-09-09: with no loader session the panel renders an EMPTY document (`document.body.innerText.trim().length === 0`, screenshot `S6-fix/shots/10-...`) and starts nothing server-side; `webchat-panel.test.tsx` pins it. Nit for the reviewer: a DIRECT navigation still shows `Foundryx` as the browser tab title (root app metadata, predates this fix; never visible to a framed visitor) |
| AC-WEB-48 | Text-node-only rendering | PASS (per S4 commit) | `lib/linkify.test.ts`, `message-text.test.tsx` |
| AC-WEB-49 | Storage-unavailable fallback | **PASS** (amended 2026-09-09 - the LOADER owns the token now) | `loader.js` `readToken`/`writeToken` try/catch with an in-memory fallback; the panel-side storage module is deleted (nothing to fall back FROM there any more) |
| AC-WEB-50 | Two tabs share the same visitor/thread | **PASS** (by construction; amended 2026-09-09) | The token now lives in the HOST origin's `localStorage` keyed by widget key, so two tabs of the same website read the identical token. Live-confirmed single-tab equivalent: a host-page reload resumes the same thread from that storage (`34-evidence/S6-fix/README.md` step 6) |
| AC-WEB-51 | 375/1280 usable | PASS | Re-verified live at both widths (screenshots 14, 17, 23) |

### Slice S5 - Backend hours + pre-chat + identity (52-57), commit `308a37d0`

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-52 | `online` via `BusinessHoursService`, unconfigured=true | PASS | Re-verified live this pass: unconfigured workspace -> `online:true`; all-days-closed -> `online:false` (curl-confirmed) |
| AC-WEB-53 | Offline greeting + message travels the same path | PASS | Re-verified live: offline greeting rendered (screenshot 20), message sent while offline landed in the inbox via the identical path (screenshots 21-22) |
| AC-WEB-54 | Pre-chat write-if-empty, never a lookup/merge | PASS (per S5 commit) | `test_omnichannel_webchat_hours_prechat_identity.py`; re-verified live (pre-chat name/email captured on a new contact, screenshot 08-09) |
| AC-WEB-55 | Valid host identity assertion resolves `host:<userRef>` | PASS (per S5 commit) | `test_omnichannel_webchat_hours_prechat_identity.py`; exercised again by S6's new `test_to_webchat_host_identity_resolves_the_existing_identity` |
| AC-WEB-56 | Invalid assertion silently ignored | PASS (per S5 commit) | `test_omnichannel_webchat_hours_prechat_identity.py` |
| AC-WEB-57 | Dev seed `chn-demo-web` + 2 threads | PASS (per S5 commit) | Not re-seeded this pass (no schema change); confirmed present in `bootstrap.py` |

### Slice S6 - Gateway, guide, workflow, A6 row, wire-up, evidence (58-66) - this pass

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-WEB-58 | `to = "webchat:<value>"` resolves an existing identity only, never creates | **PASS** | New tests: `test_to_webchat_visitor_resolves_the_existing_identity_and_sends`, `test_to_webchat_host_identity_resolves_the_existing_identity`, `test_to_webchat_that_resolves_nothing_is_422_and_never_creates_a_contact`, `test_to_webchat_identity_on_a_different_channel_is_422` (all pass, `tests/test_omnichannel_gateway_webchat.py`) |
| AC-WEB-59 | Both shapes carry `WEBCHAT`/`visitorLastSeenAt`, window fields null | **PASS** | `test_default_and_rio_shapes_carry_webchat_type_and_no_window`, `test_message_item_carries_webchat_channel_type_on_both_shapes`, `test_a_non_webchat_contact_reads_null_visitor_last_seen_at_on_both_shapes` (all pass) |
| AC-WEB-60 | Guide diff in the same commit range | **PASS** | `documentation/omnichannel/consumer-integration-guide.md` diff: changelog row (2026-09-08), §4.1 `webchat:` row + no-window paragraph, §9.1/9.2/9.3 widened `channelType` + new `visitorLastSeenAt`, §10 `invalid_recipient` row updated. Contract-drift guard: `test_consumer_guide_documents_the_webchat_prefix_and_new_fields` (pass) |
| AC-WEB-61 | Workflow `channelType` filter offers Web chat; `send_message` has no window refusal | **PASS** | Backend: `_CHANNEL_TYPE_OPTIONS` gains `WEBCHAT`; `test_message_received_trigger_declares_the_channel_type_field` updated + passing. FE: `CHANNEL_TYPES` already included `WEBCHAT` (S0), so the canvas's `omnichannelChannelType` field offers "Web chat" with no FE change needed. `test_workflow_send_message_action_has_no_window_refusal_on_webchat_contact` (pass) - the workflow action sent a real text message to a live web chat contact with zero window checks |
| AC-WEB-62 | One verified `SOURCE_TO_CHANNEL_TYPE` row for respond.io's website-chat source | **DEFERRED** | No row added. Verified against the vendor's official `@respond-io/typescript-sdk` (`src/types/contact.ts`, `dev` branch, fetched live) - its `ChannelSource` union has NO website-chat member at all. No API token in this lane and the one sandbox workspace (plan 24) has no channel connected, so a live `GET /space/channel` value could not be obtained either. Filed as **BL-SS-182** (provisional numbering, see backlog) rather than guess |
| AC-WEB-63 | Mock-to-real flip for both trios, every surface re-verified with real data | **PASS** | `services/webchat-service.ts` -> `realWebchatService`; `services/webchat-visitor-service.ts` -> `realWebchatVisitorService`. Every S0/S4 surface re-verified live this pass: wizard WEBCHAT branch (01), Widget tab + snippet + secret (02, 05), rate/sign-out routes exist (unchanged S1 routes, real service now calls them), channels list badge/filter (03-04), composer under `reengageMode:'none'` (11-13), the panel itself (06-23). `grep -rn "S0 MOCK\|S4 MOCK"` on the flipped files is empty |
| AC-WEB-64 | E2E: connect + snippet + Web chat badge | **PASS** | `34-evidence/S6/README.md` steps 1-3, screenshots 01-05, 375px (04) + 1280px (01-03, 05) |
| AC-WEB-65 | E2E: visitor journey, live reply, image | **PASS** | Image half: `34-evidence/S6/README.md` step 8, screenshots 15-17 (untouched by the fix). Core path RE-RECORDED after the BL-SS-183 fix: `34-evidence/S6-fix/README.md` steps 1-6, screenshots 01-08 + 11-12 (1280px + 375px) - send, live agent reply with no reload, reload resumes the same thread. No lightbox exists in the current code so "opens it" is satisfied by the image loading/displaying |
| AC-WEB-66 | E2E: off-list origin never opens; offline greeting, message still lands | **PASS** (first half was FAIL; fixed and re-recorded 2026-09-09) | First half: `34-evidence/S6-fix/README.md` steps 1 and 7 - the allowlisted host origin `http://localhost:3013` chats normally while `http://127.0.0.1:3013` injects no widget at all, with the app's own origin never added to the channel's allowlist (screenshots 01, 09). Second half: PASS, unchanged - screenshots 20-23, `34-evidence/S6/README.md` step 9b |

## Deferred items registered this pass

| Id | Title | Priority |
|---|---|---|
| BL-SS-169..181 | Plan 34's own §8 backlog candidates (visitor uploads, pre-chat as a form, wildcard origins, transcript email, typing indicator, multichannel launcher, proactive messages, retention job, localisation, launcher icon, context capture, npm loader package, edge rate-limit) | Medium/Low (see backlog.md; renumbered from the plan's own 160-172 because plan 32 already claimed that range) |
| BL-SS-182 | AC-WEB-62 deferred - no verified respond.io website-chat source value | Medium |
| BL-SS-183 | **CRITICAL** - web chat origin allowlist cannot discriminate real cross-origin embeds | Critical |

All ids are provisional lane-local numbering (this branch has not seen `main`'s post-merge
renumbering); say so at merge time per the standing convention.
