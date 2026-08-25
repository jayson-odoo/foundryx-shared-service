# Sprint 2 · Plan 06 - Storage Integrations · Test Execution Report (Phase C)

**Date:** 2026-06-07 · **Stack:** Next :3001 (production build) → FastAPI :8001 → Postgres (native) · **Specs:** `e2e/integrations.spec.ts` (5) + `e2e/avatar.spec.ts` (2) + `e2e/session-freshness.spec.ts` (2) · **Result: 9 / 9 PASSED** (13.5s, fullyParallel)

Suite layers at the time of run: backend pytest **341 passed** (incl. storage adapter/resolution/avatar/connections-list), frontend Vitest **324 passed** (+5 new `connection-schema` blank-to-keep regressions), **full Playwright suite 78 passed / 1 skipped / 0 failed** (the skip = the documented Embedded-Signup real-Meta-env case).

Branch context: `sprint-2/06-storage-integrations`, rebased onto main (plan 05 datetime-hygiene) mid-phase - plan-06 migration re-chained after `9d2e3f4a5b6c`, new schemas adopted `ApiModel`, integrations surfaces adopted `useDatetime()`.

---

## Scenario 1 - Connect S3 storage: UNVERIFIED until tested, honest probe error

| | |
|---|---|
| **User Story** | As a tenant admin I connect an S3-compatible bucket; until a test passes the connection shouts UNVERIFIED, and a failing test tells me the real reason. |
| **Precondition** | Dedicated tenant `e2e-int-probe-*` (connections are unique per (tenant, type) - D7). Probe kept offline-deterministic: advanced Endpoint URL → `localhost:9` (closed port). |
| **Steps** | 1. Sign in, Settings → Integrations. 2. Connect integration. 3. Provider picker (SearchSelect) → Amazon S3. 4. Fill bucket/region/keys; Advanced → endpoint `http://localhost:9`. 5. Create. 6. Form "…" Actions → Test connection. |
| **Expected** | Save lands on the record page with status **Unverified**; Test surfaces the honest transport error ("Could not access bucket …") in toast + Health card; status flips **Error**. |
| **Actual** | As expected. |
| **Remarks** | The real-creds happy path is covered manually (Scenario 6). |

## Scenario 2 - Edit keeps stored secrets when left blank (write-only contract)

| | |
|---|---|
| **User Story** | As a tenant admin I rename a connection without re-typing the secrets; blank means "keep what's stored". |
| **Precondition** | Dedicated tenant `e2e-int-keep-*` with an S3 connection. |
| **Steps** | 1. Open the record, Edit. 2. Confirm secret inputs show "•••••••• (leave blank to keep)". 3. Change Name only. 4. Save. |
| **Expected** | "Connection saved." - NO "Required" error on the untouched secret fields; heading shows the new name. |
| **Actual** | As expected - after fixing a REAL bug this scenario caught in manual testing first: edit prefilled `credentials: {}`, so the registered-but-undefined secret values failed `z.record(z.string())` with a bare "Required". Both prefill builders now seed secrets as `''`; pinned by 5 Vitest regressions (`connection-schema.test.ts`). |

## Scenario 3 - One connection per type (D7) refused with a 409

| | |
|---|---|
| **User Story** | As a tenant admin I can't accidentally create a second storage connection - the server refuses and names the existing one. |
| **Precondition** | Dedicated tenant `e2e-int-dupe-*` with an S3 (storage) connection. |
| **Steps** | 1. Back to integrations. 2. Connect integration → Cloudflare R2 (also storage). 3. Fill, Create. |
| **Expected** | Error toast: a storage connection ("…") **already exists** (server 409; DB UNIQUE(tenant_id, type) backstop). |
| **Actual** | As expected. |

## Scenario 4 - Disconnect via confirm; avatar upload → crop → renders everywhere

| | |
|---|---|
| **User Story** | (a) Disconnecting routes through a destructive confirm and removes the row. (b) As a user I set my avatar on My Account; it shows in the header and the users list. |
| **Precondition** | Dedicated tenants (`e2e-int-del-*`, `e2e-avatar-*`). No storage connection on the avatar tenant → exercises the LOCAL storage fallback. |
| **Steps** | (a) Row "…" → Disconnect → confirm. (b) Header avatar → My Account → pick file (PNG fixture) → Crop avatar dialog → Save; then User Management → Users. Second test: pen badge → Remove photo. |
| **Expected** | (a) Row gone after confirm. (b) Avatar slot renders an `<img>` from `/public/avatars/{id}?v=` (key + version cache-bust, D4 - never a presigned URL); header image appears (session `update()` freshness); users list row shows the avatar; Remove returns the slot to initials. |
| **Actual** | As expected. |

## Scenario 5 - Permission freshness on refresh (D8) + menu hygiene (D9)

| | |
|---|---|
| **User Story** | When my admin revokes a permission, a page REFRESH is enough - the menu entry and page disappear without re-login. The sidebar says "Settings" (not "Workspace Settings") and carries no dead demo links. |
| **Precondition** | Dedicated tenant `e2e-fresh-*` - the test MUTATES the Admin role's grants (revokes `integrations.*` via API; role-editing UI is covered by roles-permissions.spec). |
| **Steps** | 1. Baseline: Settings → Integrations opens. 2. Revoke `integrations.*` behind the session's back. 3. Refresh. 4. Direct-nav to `/settings/integrations`. 5. Separate test: assert menu naming + dead entries. |
| **Expected** | After refresh the Integrations entry is pruned (use-session-sync → fresh `permissions[]` → menu filter); direct nav lands on the friendly NoPermission page (never a raw 403). "Settings" present, "Workspace Settings" gone; User Management carries only Users + Roles (demo's Permissions/Account/Logs links - 404 routes - pruned). |
| **Actual** | As expected. |

## Scenario 6 - MANUAL: real R2 bucket + custom-domain CDN round-trip

| | |
|---|---|
| **User Story** | As a tenant admin I connect a real Cloudflare R2 bucket with a custom-domain CDN and the probe verifies the full write→CDN-read→delete loop. |
| **Precondition** | Real R2 account (bucket `sorento-crm`), custom domain `cdn-sorento.com` attached; creds entered via the UI. |
| **Steps** | 1. Connect Cloudflare R2 with real Account ID/bucket/keys + CDN base URL. 2. Verify storage. |
| **Expected** | Probe uploads, fetches back THROUGH the CDN, byte-compares, deletes → status **Connected**. |
| **Actual** | **Connected, last tested 2026-06-07 14:50** (real WhatsApp-style live-rig posture, omnichannel precedent). |
| **Remarks** | Caught a REAL bug: Cloudflare's WAF (Bot Fight Mode) 403s the default `Python-urllib/x.y` UA - probe failed with "HTTP Error 403: Forbidden" despite correct wiring. Fixed: probe sends `User-Agent: FoundryxEMS-StorageProbe/1.0`. Also surfaced locally: `FERNET_KEY` was unset in dev `.env` → ephemeral key per process → stored credentials died on every backend restart ("Stored credentials can no longer be decrypted"). Key now pinned; prod already guarded (seed refuses without it). |

---

## Real bug caught by the suite - ActionMenu never closed (shared shell)

The change-email ceremony spec froze waiting for the pending banner's "Cancel
request" button. Live repro (MCP browser) showed the form's "…" **Actions
dropdown still open** after picking "Change email" - `onSelect` called
`e.preventDefault()` (to keep Radix from racing dialogs the action opens) but
nothing ever closed the menu, whose overlay then intercepted EVERY later click
on the page. Latent in the plan-02 ActionMenu since birth; surfaced by the
first menu action that opens its own dialog. Fix: controlled `open` state -
preventDefault stays, the handler closes the menu explicitly. Affects every
row/form "…" menu in the system (all entities inherit the fix).

## Spec modernization (plan-06 UI changes broke older specs' selectors)

- `account-security` + `datetime-hygiene`: header avatar is now the real
  session avatar behind a `User menu` button (the Metronic demo `alt="User
  Avatar"` image is gone); `/account` h1 is the USER'S NAME (Resource form
  shell); "Change email" moved into the form's Actions menu.
- `datetime-hygiene` BL-014 test: User Management's dead demo children are
  pruned, so a role without users/roles read loses the whole section (childless
  parents disappear); "Workspace Settings" → "Settings".
- `tenants`: seeded-row assertions now SEARCH first - a fullyParallel run
  provisions sibling e2e tenants mid-suite that crowd seeded rows off page 1.
- 60 residue `e2e-%` tenants purged from the local DB pre-run (BL-069 rule).

## Environment / rig notes

- Specs are **fullyParallel-safe**: every test provisions a dedicated timestamped tenant (`e2e-int-*`, `e2e-avatar-*`, `e2e-fresh-*`); slugs carry a per-test tag - two same-millisecond provisions collided on `Date.now()` alone during stabilization.
- FormRow labels are not wired to inputs (no `htmlFor`) - specs target secret inputs by `input[type="password"]` order. A11y label wiring would let these go back to `getByLabel` (candidate backlog).
- `/roles` API pagination is 0-based.
- Storage probes in CI stay offline (closed-port endpoint); only Scenario 6 touches the network, manually.
