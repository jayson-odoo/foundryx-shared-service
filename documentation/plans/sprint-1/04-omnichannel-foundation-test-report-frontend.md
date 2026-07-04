# 04 — Omnichannel Foundation · Phase A (Frontend Prototype) — Test Execution Report

**Sprint:** 1 · **Plan:** [04-omnichannel-foundation](04-omnichannel-foundation.md) · **Phase:** A (frontend prototype, mock services)
**Stack under test:** Next :3001 (mock omnichannel services) → real NextAuth → FastAPI :8001 (auth + RBAC) → Postgres.
**Date:** 2026-06-02

> Phase A builds the UI against **mock** channel/workspace/onboarding services (behind the service layer). Auth + permission gating are real. The omnichannel permission keys were added to the core seed CSV as a Phase-A enabler (relocate to the module CSV in Phase B).

---

## 1. Automated coverage

### Unit / component (Vitest) — 9 passed
| Spec | Cases | Result |
|------|-------|--------|
| `hooks/use-connect-channel.test.ts` | wizard state machine: idle→selecting, cancel, authorize→exchanging→connected (carries channel + args), authorize failure→failed (error surfaced), reset→idle | ✅ 5/5 |
| `app/(protected)/omnichannel/settings/workspaces/components/workspace-schema.test.ts` | valid workspace, empty-name reject, unknown-status reject, no-members allowed | ✅ 4/4 |

Typecheck: `tsc --noEmit` → 0 errors. Lint: `eslint` over all new dirs → clean.

### E2E (Playwright, real clicks vs live stack) — 5 passed
| # | User Story | Scenario | Precondition | Steps (real clicks) | Expected | Actual | Remarks |
|---|-----------|----------|--------------|---------------------|----------|--------|---------|
| 1 | As an admin I see my connected channels | List connected WhatsApp channels | Logged in as demo Admin | Sidebar → Omnichannel → Channels | Channels list shows seeded WhatsApp channels + page subtitle | Pass | — |
| 2 | As an admin I connect a WhatsApp number with no technical setup | Embedded Signup wizard | On Channels list | Click **Connect channel** → **Connect with Facebook** → (simulated Meta popup) pick "FoundryX Events Co." → **Authorize** → **Done** | Wizard runs idle→popup→exchanging→connected; new channel appears in list | Pass | Mock popup stands in for the Meta JS SDK (Phase B swaps it) |
| 3 | As an admin I inspect a channel | Channel detail form | On Channels list | Click a channel row | Detail form opens with **General** + **Connection** tabs | Pass | First dynamic-route dev compile is slow → `waitForURL` 20s |
| 4 | As an admin I see my workspaces | Workspaces list | Logged in | Sidebar → Omnichannel → Workspaces | List shows workspaces incl. the **Default** badge | Pass | — |
| 5 | As an admin I create a workspace | Create workspace | On Workspaces list | Click **New workspace** → fill name → **Create** | Lands on the created workspace form (Settings + Members tabs) | Pass | — |

Run: `npx playwright test e2e/omnichannel.spec.ts` → **5 passed (22.8s)**.

---

## 2. Manual / exploratory notes
- Permission gating verified real: pages wrap in `<RequirePermission>`; demo Admin holds the seeded `channels.*` / `workspaces.*` keys, so no `NoPermission` page.
- Wizard states all reachable + tunable: workspace picker (intro), simulated popup, exchanging spinner, connected success, failed + Try again.
- Resource shell reused unchanged (list: server-style sort/filter/search/paginate via mock-query, status views, CSV export, action registry; form: read + Edit toggle, tabs, record-nav).

## 3. Known Phase-A limitations (carried to Phase B)
- Channel/workspace/onboarding data is **mock** (in-memory); swap to real api-client at the service boundary in Phase B.
- Embedded Signup popup is **simulated**; Phase B wires the real Meta JS SDK + `POST /omnichannel/onboarding/oauth-callback`.
- Omnichannel permission keys live in the **core** CSV (Phase-A enabler); relocate to `omnichannel/backend/permissions/permissions.csv` in Phase B.
- No backend yet for channels/workspaces/contacts/messages — Plan 04 Phase B builds the `app_omnichannel` schema + onboarding endpoints.
