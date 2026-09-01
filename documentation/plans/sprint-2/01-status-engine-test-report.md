# Sprint 2 · Plan 01 - Status & State-Machine Engine · Test Execution Report

**Branch:** `sprint-2/status-engine` · **Date:** 2026-06-05
**Stack under test:** Next.js :3001 (production build) → FastAPI :8001 → local Postgres (`bootstrap_db`: Alembic `f5a6b7c8d9e0` + seed)

## Automated suites

| Suite | Scope | Result |
|-------|-------|--------|
| Backend `python -m pytest -q` | 199 tests - 15 new in `tests/test_status_engine.py` + full regression incl. merged plan 10 | **199 passed** |
| Frontend `npm test` (Vitest + RTL) | 193 tests post-rebase (plan-10 suites joined) - 11 new in `components/platform/status-engine/status-engine.test.tsx` | **193 passed** |
| `npm run build` + `tsc --noEmit` | type-check + lint + 107 routes | **green** |
| Playwright E2E (full suite, post-rebase) | 64 specs incl. 4 new in `e2e/status-engine.spec.ts` | **63 passed, 1 skipped** (known Meta-env Embedded-Signup case) |

> Final full run included `password-reset-live.spec.ts` (aiosmtpd maildir daemon up, throttle counters cleared first, dev `.env` carries `THROTTLE_IP_MAX_FAILS=200`). One-command suite wiring (daemon in Playwright global-setup, throttle isolation) remains **BL-061**.

## E2E scenarios (real clicks)

### TC-1 Operator builds the transition graph
- **User story:** As a platform operator I configure statuses, transitions, fire-roles and notifications on a visual canvas.
- **Precondition:** Bootstrapped stack; operator `platform@example.com` (platform tenant).
- **Steps:** Sign in at `platform.localhost:3001` → click **Status Engine** in the Platform menu → verify the seeded tenant graph (Active/Suspended/Archived nodes, Reactivate edge, "Platform defaults" tier badge) → **Add status** → drawer: label `E2E Hold <ts>`, flag *Blocks access* → Create → drag from Active's right handle onto the new node's left handle → edge drawer: action label, **Add notification** (EMAIL, merge-field subject/body, recipient = Acting user) → Create transition → click the edge label → verify the saved notification round-trips → Delete transition → delete the created status.
- **Expected:** Graph renders from server data; terminal node (Archived) exposes no source handle; drag-create opens the edge drawer; notification persists; node delete cascades its edges.
- **Actual:** As expected. **PASS**
- **Remarks:** SVG edge-label clicks use `dispatchEvent` (label re-renders with the post-save refetch - pointer-stability wait would time out).

### TC-2 Transition fires through the status machine
- **User story:** As an operator I suspend a tenant; the move must traverse a defined graph edge and surface the engine's editable display label.
- **Precondition:** TC-1 stack; dedicated tenant provisioned in-spec (`e2e-se-<ts>`, isolation rule).
- **Steps:** Provision via console form → Tenants list → search slug → row Actions → **Suspend** → confirm.
- **Expected:** Row badge renders the server-driven label ("Suspended"); the Actions menu no longer offers Suspend (no Suspended→Suspended edge) and offers Reactivate.
- **Actual:** As expected. **PASS**
- **Remarks:** Email-outbox enqueue on notified transitions is asserted by backend integration tests (`test_notification_recipients_resolve_and_enqueue_email` - USER/ROLE/DYNAMIC recipients resolved, rendered subject/body rows in `email_outbox`); no outbox UI exists yet (BL-044).

### TC-3 Tenant surface + two-tier visibility
- **Steps:** Tenant admin `demo@example.com` → Workspace Settings → **Statuses**.
- **Expected/Actual:** Page loads under `statuses.read`; platform-owned `tenant` entity hidden from tenant callers; empty-state explains module-registered entities. **PASS**

### TC-4 Permission gating
- **Steps:** `demo@kt.com` (Member - no `statuses.*`) → Workspace Settings → Statuses.
- **Expected/Actual:** Friendly NoPermission page, never a raw 403. **PASS**

## Backend coverage highlights (`tests/test_status_engine.py`)

registry visibility (operator vs tenant) · two-tier platform-fallback → fork-on-first-edit with record remap + platform tier untouched · strict no-edge reject (D4) · fan-out + loop-back branching · self-loop / terminal-outgoing / duplicate / cross-entity edge validation · edge-role allow+deny (D5) · block-delete-while-referenced → deactivate → migrate-records → clean delete with edge cascade (D8) · system-row label-editable/behavior-locked · batch reorder validation · **flag-driven lifecycle**: new operator status with `blocks_access` fired via the generic transition endpoint kills tenant sign-in (no category branch) · archived terminal (no outgoing edge creatable) · notification recipients USER/ROLE/DYNAMIC dedup + outbox enqueue + inline merge-field render · IN_APP inert · `StatusTransitioned` event payload.

## UI rework (post-review iteration, same day)

User review corrected the surface shape; re-verified end-to-end after:
- **Resource design language applied**: entity ResourceList (`statusEntities.list` - Entity/Module/Statuses/Transitions/Source columns) → row click → ResourceForm detail with **Flow** + **Statuses** tabs; the global **Edit toggle gates the canvas** (read-only flow view by default).
- **Menu rule**: no clickable parents - Status Engine under "Platform Engines" parent; App Store under "App Store ▸ Browse Modules".
- **Canvas interactivity**: controlled nodes/edges (drag applies locally - smooth), position saves silent (no refetch jank), edge click = select + floating Edit/Delete toolbar + Delete-key support, node click = drawer.
- Suites re-run green: pytest (incl. entity stats), Vitest 193, build, Playwright full suite 54+1 passed (impersonation spec flaked once under parallel contention, passes solo - pre-existing).

## Environment notes

- Local DB was rewound off plan-10's head mid-session, then plan 10 merged to main and this branch rebased - final chain is linear `4eb2fa454ce8 → abbca98c3966 (auth throttle) → f5a6b7c8d9e0 (status engine)`, single Alembic head, verified by `bootstrap_db` + `alembic heads/current` against Postgres.
- E2E residue (accumulated `e2e-%` tenants crowding page 1) purged per the CLAUDE.md residue rule before the final green run.
