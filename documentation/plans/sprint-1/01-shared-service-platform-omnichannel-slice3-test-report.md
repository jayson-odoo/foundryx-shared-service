# Slice 3 - API-key auth + public send + idempotency · Test Execution Report

**Plan:** `01-shared-service-platform-omnichannel.md` §Slice 3
**UAC:** `01-shared-service-platform-omnichannel-acceptance-criteria.md` (AC-01-12…21, 36, 37)
**Date:** 2026-07-04 · **Branch:** `sprint-1/omnichannel-api-gateway`
**Stack verified:** backend :8001 on native Postgres + Redis; full backend suite **906 passed / 0 failed**; new gateway suite `tests/test_omnichannel_api_gateway.py` **14 passed**.

## Result matrix (per AC)

| AC | Title | Layer | Status | Evidence |
|----|-------|-------|--------|----------|
| AC-01-12 | `workspace_api_keys` table + hashed storage | BE/T | **PASS** | Table in `app_omnichannel` with exactly `(id,tenant_id,workspace_id,name,key_prefix,key_hash,last_used_at,revoked_at,created_by,created_at)`; test asserts `len(key_hash)==64`, `len(key_prefix)==8`, no plaintext column. Verified on live Postgres. |
| AC-01-13 | key minted once, shown once, live-only, revoke | BE/FE/E2E | **PASS (BE)** / FE below | `test_mint_returns_full_key_once…`, `test_multiple_active_keys_and_revoke`; revoked key → 401. Live curl: mint returned `fxw_live_…` once + masked in list. |
| AC-01-14 | Bearer resolves workspace+service, tenant-scoped, uniform 401 | BE/T | **PASS** | `get_api_workspace` constant-time compare; `test_invalid_keys_uniform_401` (None/garbage/unknown all → `invalid_api_key`). Live curl confirmed. |
| AC-01-15 | cross-service / service-not-enabled rejected | BE/T | **PASS** | `test_service_not_enabled_when_module_inactive` → 403 `service_not_enabled`. NOTE: only one service exists (omnichannel), so the *cross-namespace* leg is enforced structurally + via the module-active check; a true second-service test lands with service #2 (BL-SS-005). |
| AC-01-16 | public send 202 + our id | BE/T | **PASS (text/template)** | `test_public_send_text_open_window` → 202 + our id + inbox bubble. **Media deferred to Slice 4** (durable media §4.5) and **interactive deferred** (BL-SS-002) - both return structured `unsupported_type` for now. Async: S3 dispatches inline via the dev-stub adapter and returns 202 + our durable id; the Redis-Streams bus enqueue is a transparent S4 swap (response contract already correct). |
| AC-01-17 | CSW enforced on public send | BE/T | **PASS** | `test_csw_closed_free_form_409` → 409 `csw_window_closed`; template to same contact accepted. Reuses the SAME `_window_open` gate as the agent path. |
| AC-01-18 | idempotency dedup per workspace | BE/T | **PASS** | `test_idempotency_replay_same_workspace` (2nd call → same id + `idempotencyReplay:true`, exactly one row). Live curl replay confirmed (Redis path). Workspace-scoped key. |
| AC-01-19 | read-only templates over API | BE/T | **PASS** | `test_templates_list_over_api`; live curl returned the demo template. |
| AC-01-20 | `phone_number_id` UNIQUE service-wide | BE/T | **PASS** | Partial-unique index `uq_channels_phone_number_id` on live Postgres; migration `0002` reconciles dupes first; `test_phone_number_in_use_guard` + connect flow → 409 `phone_number_in_use`. |
| AC-01-21 | API-keys management UI (Resource shell) | FE/E2E | **PENDING** | Frontend built by the coder agent - see the frontend verification section (to be appended). |
| AC-01-36 | structured error envelope everywhere | BE/T | **PASS** | `ApiError` → `{error:{code,message,details?}}`; codes exercised: `invalid_api_key`, `service_not_enabled`, `csw_window_closed`, `unsupported_type`, `template_not_found`. Live curl confirmed envelopes. |
| AC-01-37 | every query tenant+workspace scoped | BE/T | **PASS** | Tenant+workspace derived from the key (never body/query); repo queries scoped. Covered across the gateway suite. |

## Notes / deviations (logged)
- **Media outbound** and **interactive** message types are not yet sendable - they return the structured `unsupported_type` error. Media durability (both directions) is Slice 4 §4.5; interactive is BL-SS-002. AC-01-16's media leg is therefore **partial** by design and closes in S4.
- **Async enqueue**: S3 returns 202 with the durable message id but dispatches inline (dev-stub adapter). The Redis-Streams `EventBus` (S4) is a transparent swap behind the same 202 contract.
- **Slice-2 gap fixed here**: the default tenant had no omnichannel install row (fresh DB, no backfill), so the inbox + api-key perms would 403. `bootstrap_db` now installs omnichannel for the default tenant and runs the admin grant sweep AFTER module perms sync.
- **Stale EMS tests**: the S1 strip left 6 failing tests (catalog/numbering/cluster-d) referencing removed EMS/CRM/finance data - fixed (2 catalog, 3 numbering) / deleted (1 EMS-migration guard). No core regression.

## Frontend verification (AC-01-13 FE, AC-01-21, AC-01-38) - real-click pass

**Built + served** (`rm -rf .next && npm run build` green; verified via `next dev` on :3001 against the live backend :8001, demo@example.com). Vitest: api-keys service + mint-dialog **11 passed**.

| AC | Result | Evidence (real clicks, demo tenant, live data) |
|----|--------|------------------------------------------------|
| AC-01-21 | **PASS** | Workspace detail → **API Keys** tab renders the **Resource-shell** list (Name / Key masked via `ClampedText` as `fxw_live_xxxxxxxx••••` / Status `StatusBadge` / Last used + Created tz-rendered / Actions). Not a hand-rolled table. Showed the real keys minted earlier via the API. |
| AC-01-13 (FE) | **PASS** | **Mint key** → name dialog (Mint disabled until named - foolproof) → "API key created" dialog reveals the **full** `fxw_live_…` **once** + Copy button + single-line "Copy this key now - it won't be shown again." The list never re-shows the full key (masked only). |
| AC-01-13 revoke | **PASS** | Row **Actions → Revoke** → confirm dialog ("Consumers using this key will stop authenticating immediately…") → status flips to **Revoked** live (real backend). |
| AC-01-38 | **PASS** | Verified at **1280px** (full flow) AND **375px** (viewport 375, page scrollWidth 360 → **no horizontal scroll**; tab + Mint button + list all visible). Masked key recoverable via ClampedText. |

### Critical fix during verification - demo1 MegaMenu crash (S1-strip regression)
The coder flagged (and I confirmed) that **every protected page crashed** before render: the demo1 header `MegaMenu` hardcoded `visibleMenu[0..4]` and dereferenced stripped-EMS sections (Public Profiles / Network), so after the S1 strip those indices were `undefined` → `Cannot read properties of undefined (reading 'children')`. This blocked ALL logged-in use, not just this slice.
- **Fixed** `app/components/layouts/demo1/components/mega-menu.tsx` to render **generically** from the permission/module-filtered menu (resolve sections by existence, never fixed index - per the CLAUDE.md rule) using the shared `MegaMenuSubDefault` renderer; dropped the bespoke stripped-section sub-components. The mobile mega menu was already generic.
- Verified: login → dashboard → all sidebar routes + header menu render, no crash.

### White-label cleanup (AC-01-38)
- Browser tab title `Foundryx EMS` → `Foundryx` (`app/layout.tsx`); `alt="Foundryx EMS"` → `Foundryx`; auth-panel default tagline `Bringing Events to Life.` → `One platform, every conversation.` (events-domain slogan removed) + branding E2E assertions updated.

## Code review (round 1) + resolutions
Reviewer verdict: **REQUEST CHANGES** (1 blocker, 1 real-500, hardening). All addressed:
1. **BLOCKER - MegaMenu Rules-of-Hooks crash (regression in my own fix):** `MegaMenuSubDefault(children)` was called positionally inside `.map()`, so its internal `usePathname`/`useMenu` hooks ran in MegaMenu's fiber a *variable* number of times (count shifts as `filterMenu` resolves) → "rendered more/fewer hooks" white-screen. **Fixed:** wrapped it in a `MegaMenuSection` component rendered as JSX, so each gets its own fiber. (My earlier browser verify missed it because the demo tenant's menu count was already stable by first paint.)
2. **Disconnect→reconnect 500 (test-invisible):** the partial-unique phone index covered *all* non-null rows, but `disconnect()` keeps `phone_number_id` + sets `is_trashed=true` → reconnecting the same number hit the index → 500. **Fixed:** scoped the index (+ reconcile + `_assert_phone_available`) to `WHERE phone_number_id IS NOT NULL AND is_trashed = false` in migration 0002 **and** bootstrap (with a DROP of any stale all-rows index); added an `IntegrityError`→409 backstop in `_persist_channel`. Verified on live Postgres: trashed+new-live coexist, two-live rejected.
3. **Idempotency double-send race:** lookup→send→remember wasn't atomic. **Fixed:** reserve-before-send - `reserve()` SET-NX a PENDING sentinel; winner `finalize()`s with the real id, `release()`s on failure; a concurrent in-flight duplicate gets `409 idempotency_in_progress`.
4. **Isolation test added:** a workspace-A key can't list workspace-B's templates nor create a contact in B (`test_key_cannot_reach_another_workspace`).
5. **Validation envelope:** `RequestValidationError` on `/api/v1/*` now returns the `{error:{code:"invalid_request",…}}` envelope (AC-01-36 consistency).
6. **Reuse:** `_resolve_or_create_contact` now uses `ContactRepository.find_by_phone_in_workspace` (the inbound stitch) instead of a duplicate load-all loop; created contacts get `status_id` = OPEN.
7. Softened the API-keys empty-state copy (removed procedural hint, foolproof-UI).

Gateway suite now **16 passed** (added isolation + trashed-reconnect tests). Full backend suite re-run + frontend rebuild after the fixes (green).

### Environment notes (for re-verification)
- Frontend needs `.env.local` (created): `NEXT_PUBLIC_BACKEND_API_URL`/`BACKEND_API_URL=http://localhost:8001`, `NEXTAUTH_URL=http://localhost:3001`, `NEXTAUTH_SECRET`.
- `next.config` sets `output: standalone` → `next start` does not serve; use `next dev` (verification) or `node .next/standalone/server.js`.

