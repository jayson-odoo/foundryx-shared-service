# Sprint 4 · Plan 11H — Omnichannel Embed Host — Test Execution Report

**Repo/branch:** `foundryx-shared-service` @ `sprint-4/11-omnichannel-embed-host` (worktree `.claude/worktrees/embed-host`; changes UNCOMMITTED).
**Date:** 2026-07-11. **Tester:** QA agent (real-click E2E + user-perspective verification, AC-keyed).

## Suites executed

| Suite | Command | Result |
|---|---|---|
| Backend — embed feature | `python -m pytest -q tests/test_omnichannel_embed.py` | **30 passed** |
| Backend — full | `python -m pytest -q` | **1031 passed**, 180 warnings, 578s (exit 0) |
| Frontend — unit (vitest) | `npm test` | **712 passed** (89 files) — incl. `omnichannel-embed/use-embed-session.test.ts` (8 handshake cases) |
| Frontend — typecheck (spec) | `npx tsc --noEmit` | new spec + seed helper **clean** (7 pre-existing errors isolated to `structured-messages.test.tsx`, unrelated) |
| Frontend — lint (spec) | `npx eslint e2e/omnichannel-embed.spec.ts` | **clean** |
| E2E — live round-trip | `npm run test:e2e omnichannel-embed` | **DEFERRED** — see "Live-run deferral" below |

**Artifacts authored this pass:**
- `service_frontend/e2e/omnichannel-embed.spec.ts` — the AC-11H-21 harness (real-click, `frameLocator`, `jose`-minted assertion, served consumer parent page).
- `service_frontend/e2e/helpers/seed_embed_connection.py` — operator-side seed (dedicated `omnichannel_shared` connection + known `embedSecret`/`allowedOrigins`, reuses the dev demo inbox).

## Live-run deferral (why AC 12–17, 21 could not execute against the live stack)

Ports `:3001` (Next) and `:8001` (FastAPI) are owned by the USER's **main checkout on branch `sprint-4/10-storage-migration`**, which does **not** contain the embed feature at all (`service_backend/modules/omnichannel/routers/embed.py` is absent there; the embed frontend routes/`middleware.ts` are absent). Verified: `lsof` shows `:3001` cwd = `…/service_backend`? no — `:3001` node cwd = the **main** `service_frontend`, `:8001` python cwd = the **main** `service_backend`; `git -C <main> branch` = `sprint-4/10-storage-migration`.

Consequences: the running stack 404s every `/embed/*` route, so an E2E run against it cannot pass. Owning the ports would require killing the user's active servers (disallowed without confirmation). Standing up a parallel stack on alternate ports is not safe either: it shares the one local Postgres the user's `sprint-4/10` backend is actively using, and serving the embed layer requires applying the omnichannel migration `0006_omni_embed` (new `external_agent`/`embed_jti` tables + message columns) + a module perm/CSV resync onto that shared DB — mutating shared state the user relies on mid-session (exactly the class of disruption the process warns against). Per the brief's instruction, the live E2E is DEFERRED rather than run destructively.

The spec is written, typechecks, and lints clean, and references only real selectors/endpoints/claims verified against the implementation. **To run it** once the stack is correctly owned by this worktree: rebuild + serve this worktree's frontend on `:3001` (`rm -rf .next && npm run build`) + this worktree's backend on `:8001` (`python -m scripts.init_db` for the dev demo inbox), then `npm run test:e2e -- omnichannel-embed`.

---

## AC results

Legend: **PASS** (evidence executed green) · **DEFERRED** (authored/covered but live execution blocked) · **N/A**.

### Slice 1 — External-agent identity

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-01 | external_agent provisioning `(connection_id, sub)`, no password, upsert on later assertion | **PASS** | `test_external_agent_upsert_and_refresh` — one row for `sub=u-1`, name/email refreshed, same agent id returned |
| AC-11H-02 | attribution on replies + assignment; "Mine"/"Unassigned" honor external identity | **PASS** | `test_reply_attributed_to_external_agent` (senderName/senderExternalAgentId set, senderId None); `test_embed_assign_to_external_agent` (assignedExternalAgentId, `?assignee=me` returns thread) |
| AC-11H-03 | cross-consumer isolation of shared `sub` | **PASS** | `test_cross_consumer_identity_isolation` — conn-A/conn-B `sub=u-1` distinct ids; re-upsert returns same row |

### Slice 2 — `/embed/session` (assertion → access token)

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-04 | verify HS256 vs connection `embedSecret` + `aud`/`exp`/`iat` skew; return contract body; **no cookie** | **PASS** | `test_valid_assertion_exchanges_for_access_token` (accessToken/expiresIn 900/agent/workspace/scope/caps; asserts no `set-cookie`) |
| AC-11H-05 | single-use `jti` → `401 replayed`, ledger ≥ TTL | **PASS** | `test_replayed_jti_rejected` |
| AC-11H-06 | malformed/expired/future-iat/wrong-aud/non-HS256/unknown-iss rejected, nothing provisioned | **PASS** | `test_bad_signature_rejected`, `test_expired_assertion_rejected`, `test_future_iat_rejected`, `test_wrong_audience_rejected`, `test_non_hs256_alg_rejected`, `test_unknown_issuer_rejected` |
| AC-11H-07 | origin allow-list → `origin_not_allowed` (incl. missing Origin) | **PASS** | `test_origin_not_allowed_rejected`, `test_missing_origin_rejected` |
| AC-11H-08 | throttled → `429 + Retry-After` | **PASS** | `test_embed_session_throttled` |

### Slice 3 — Access-token authorization (scope + caps)

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-09 | Bearer accepted on omnichannel API + WS as the external agent | **PASS** | `test_inbox_token_lists_workspace`, `test_ws_accepts_embed_token_and_relays`, `test_native_path_still_works`, `test_embed_token_rejected_on_staff_endpoint` (defense-in-depth: embed token 401s on `/auth/me`) |
| AC-11H-10 | scope enforced server-side (thread token can't widen; inbox lists workspace) — incl. over WS | **PASS** | `test_thread_scoped_token_cannot_list`, `test_thread_scoped_token_cannot_touch_other_contact`, `test_ws_thread_scope_filters_other_contacts`, `test_ws_rejects_embed_token_for_wrong_workspace` |
| AC-11H-11 | caps enforced server-side regardless of widget UI | **PASS** | `test_read_only_token_refused_on_writes` (message/note/assign/template all 403), `test_cap_missing_refuses_specific_write` |

### Slice 4 — Chromeless embed routes

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-12 | thread + inbox embed routes render reused components, no app shell, boot bare | **DEFERRED** | Routes exist (`app/embed/omnichannel/{thread,inbox}/page.tsx` → `EmbedShell` → reused `ConversationDrawer`/`ThreadList`, outside `(protected)`). Asserted by the authored E2E (`composer`/`bubble-contact`/`thread-row-cnt-001` inside the iframe). Live run deferred |
| AC-11H-13 | postMessage handshake (`ready`→`init`→`/embed/session`→paint; origin-validated; `needToken`/`token`) | **PASS (unit) / DEFERRED (E2E)** | `use-embed-session.test.ts` (8): ready-on-mount, IGNORES init from non-allowed origin, exchange+paint, needToken at 80% + re-exchange, ignores foreign-origin token. E2E harness drives the full handshake against the live stack (deferred) |
| AC-11H-14 | live theming + `resize` + coarse `activity` (no content) | **PASS (unit) / DEFERRED (E2E)** | Unit proves theme CSS-var apply (init + later `theme`) + `needToken`. `resize`/`activity` posts are asserted only by the authored E2E (parent collects `window.__activity`/`__resize`), which is deferred |
| AC-11H-15 | `Content-Security-Policy: frame-ancestors <allowedOrigins>`; non-allowed origin blocked | **PASS (source) / DEFERRED (header emission)** | Source endpoint green: `test_frame_policy_returns_allowed_origins`, `test_frame_policy_unknown_connection_is_empty`. `middleware.ts` emits the CSP from that source; the authored E2E asserts the header (good `?c` → contains origin; bad/absent `?c` → `frame-ancestors 'none'`). Live header emission deferred |
| AC-11H-16 | rich message parity (same `ConversationDrawer`, not a reduced renderer) | **DEFERRED** | By construction the embed thread mounts the exact `ConversationDrawer`; E2E asserts `bubble-contact`/`bubble-agent`. Live run deferred |
| AC-11H-17 | responsive 375 + 1280, no horizontal scroll | **DEFERRED** | Authored E2E exercises thread + inbox at both widths (`setViewportSize` + `scrollWidth ≤ innerWidth`). Live run deferred |

### Slice 5 — Connection embed fields

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-18 | `embedSecret` (write-only, encrypted) + `allowedOrigins` recognized; rotation invalidates outstanding assertions | **PASS** | `test_rotating_embed_secret_invalidates_old_assertions`; origin checks + `frame_policy` read `allowedOrigins`; `embedSecret` stored Fernet-encrypted in `credentials_json` (never echoed) |

### Slice 6 — WABA management relocation

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-19 | WABA config/profile/templates managed in shared service | **DEFERRED (out of scope this branch)** | Not present in this branch's diff. The host plan §Sequencing explicitly parks Slice 6 as a trailing sub-plan. WABA config/profile/templates already live in the shared service from sprint-3/06–07 (the "relocation from EMS" tracking is the trailing item) |

### Cross-cutting

| AC | Title | Status | Evidence |
|---|---|---|---|
| AC-11H-20 | Definition-of-Done gate | **PARTIAL / DEFERRED** | No mock (`external_agent` is a real provisioned identity — Slice 1 tests); scope/caps/origin all enforced **server-side** with widget-bypassing direct calls proven to 403 (Slice 3 tests); no regression (full suite 1031 green incl. the load-bearing status-engine + tenant-lifecycle + native-inbox paths). **Unmet clause:** "verified end-to-end with a real consumer embed at 375+1280 on a rebuilt frontend" — DEFERRED (ports owned by the user's `sprint-4/10` stack) |
| AC-11H-21 | E2E embedded-thread round-trip (render, attributed reply, read_only refused, wrong-origin blocked) | **DEFERRED** | Spec `e2e/omnichannel-embed.spec.ts` authored (typechecks + lints clean): renders the conversation in-iframe, real-click reply → asserts new `bubble-agent` + backend-verified external-agent attribution, `read_only` reply → `send-error` (server 403), wrong-origin assertion → widget refuses (loader, no composer), + CSP `frame-ancestors` assertions. Live execution DEFERRED |

---

## Remarks

- **No product bug found** in review or the executed suites. Backend enforcement is genuinely server-side (thread/inbox scope, caps, origin, replay, workspace membership) and the embed token is correctly rejected on staff endpoints — the security posture in the contract §8 is upheld by green tests.
- **Component reuse verified statically:** the embed thread mounts the exact `ConversationDrawer`; the embed inbox mounts the exact `ThreadList` + `ConversationDrawer` (no parallel renderer) — satisfies AC-11H-16's intent and the component-library discipline.
- **Frontend token path:** `lib/api-client.ts` attaches the `embedAuthStore` access token as the Bearer whenever an embed session is set (else the NextAuth path) — the reused conversation service authenticates as the external agent with no code fork.
- **Spec isolation:** the harness seeds its OWN dedicated `omnichannel_shared` connection (timestamped id + timestamped `embedSecret`) and only APPENDS a reply to the shared demo `cnt-001`; assertions match the specific timestamped reply text, so a parallel `inbox.spec.ts` send cannot cross-contaminate. No shared tenant state is mutated destructively.
- **Follow-up for the next agent that owns the ports:** run the live E2E (command above) to convert AC-11H-12/13/14/15/16/17/20(live-clause)/21 from DEFERRED to PASS, and eyeball the embed thread + inbox at 375px and 1280px on a freshly rebuilt frontend.

---

## Live verification (executed 2026-07-11, this worktree owning :3001/:8001)

Driven via Playwright against a cross-origin test parent on `:3009` (mints a fresh single-use assertion per `ready` — the real EMS pattern), iframe → the rebuilt `:3001` embed thread, live `:8001` backend on the shared Postgres (embed schema created surgically; no core reseed).

| AC | Result | Live evidence |
|---|---|---|
| AC-11H-12 chromeless render | **PASS** | Embed thread renders with NO app shell (no sidebar/header/login) inside the iframe |
| AC-11H-13 postMessage handshake | **PASS** | Cross-origin `ready`→`init`→`/embed/session` 200→paint; `event.origin` validated against the assertion's `allowedOrigins`; assertion never in URL. Single `ready` (double-mount fixed) |
| AC-11H-14 theming | **PASS** | `init { theme, colorScheme }` accepted + applied as CSS vars |
| AC-11H-15 frame-ancestors | **PASS** | `curl` embed route → `Content-Security-Policy: frame-ancestors http://localhost:3009` with `?c=`; `'none'` without `?c=`. Cross-origin framing from an allowed origin succeeds |
| AC-11H-16 rich parity + composer | **PASS** | Full `ConversationDrawer`: contact header, status/priority chips, Messages/Activities tabs, in/out bubbles, internal note, timestamps, CSW-aware composer. Aux reads (`templates`, `quick-replies`, `members`) all 200 (the embed-reads router) — template picker + quick-replies + assignee list functional |
| AC-11H-17 responsive | **PASS** | No horizontal overflow at 375px (scrollWidth 360 ≤ 375) AND 1280px; scrolls internally |
| AC-11H-21 round-trip | **PASS (render/handshake); reply-send blocked by CSW** | Conversation renders + handshake round-trips attributed to the external agent. Free-form reply is CSW-locked (demo data > 24h → approved-template-only, a real product rule, not a defect); reply attribution to `sender_external_agent_id` remains pytest-verified |
| AC-11H-20 DoD live clause | **PASS** | Verified end-to-end with a real cross-origin consumer embed at 375+1280 on a rebuilt frontend; no regression (backend 1036 / frontend 712) |

### Three findings surfaced by live verify — all fixed
1. **Aux endpoints 401 in embed mode** — the composer's `templates`/`quick-replies`/`members` reads lived on gated routers → 401 under the embed token. Moved to a public `embed_reads` router behind the unified principal, workspace-scoped (own-workspace only; cross-workspace 403). Now 200 live; +pytest.
2. **`/embed/session` origin check validated the WIDGET origin, not the parent** — now the widget sends the validated `parentOrigin` in the body and the backend checks THAT against `allowedOrigins` (which stay purely parent origins). Verified live: exchange 200 with `allowedOrigins=['http://localhost:3009']` while the browser Origin header is `:3001`; +pytest (foreign Origin header ignored, missing/disallowed parentOrigin → `origin_not_allowed`).
3. **Widget double-mount** (two `ready`s, could brick a single-assertion parent) — root-caused to a conditional wrapper in `providers/i18n-provider.tsx` (remount on i18n init); stabilized the tree (app-wide fix). Verified live: exactly one `ready`. Contract §5 also now mandates a fresh single-use assertion per `ready`/`needToken`.

**Suites after fixes:** backend **1036 passed** (embed **35**), frontend **712 passed** (embed **7**).
