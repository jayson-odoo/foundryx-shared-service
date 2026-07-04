# 04 — Omnichannel Foundation · Phase B (Backend Wiring) — Test Execution Report

**Sprint:** 1 · **Plan:** [04-omnichannel-foundation](04-omnichannel-foundation.md) · **Phase:** B (real backend; mock→real swap)
**Stack:** Next :3001 (prod build) → FastAPI :8001 → Postgres (schema `app_omnichannel`).
**Date:** 2026-06-02

> Phase B builds the `omnichannel` module backend (first App Store module): schema-isolated tables, Embedded Signup onboarding, workspace/channel/member endpoints, RBAC gating; then swaps the three frontend services from mock to the real api-client at the service boundary.

---

## 1. What shipped
- **Module** `service_backend/modules/omnichannel/`: `OmniBase` + schema `app_omnichannel`; models (workspaces, workspace_members, channels, statuses, contacts, contact_channel_identities, conversation_messages, whatsapp_templates, quick_replies); camelCase schemas; Fernet credential encryption; `ChannelAdapter` + `WhatsAppCloudAdapter` (dev-safe); workspace/channel repositories; workspace/channel/onboarding services; routers gated by `omnichannel.*`.
- **Core wiring:** `app/module_loader.py` (`load_modules` + `bootstrap_modules`); one-line `load_modules(app)` in `main.py`; `bootstrap_modules()` in `bootstrap_db.py`. Omnichannel permissions moved from the core CSV (Phase-A enabler) to the module CSV.
- **Frontend:** `workspace-service` / `channel-service` / `onboarding-service` swapped to the real api-client impls (one line each); by-workspace path aligned.

## 2. Automated coverage

### Backend (pytest) — 66 passed (8 new + 58 existing, 0 regressions)
| Spec | Cases | Result |
|------|-------|--------|
| `tests/test_omnichannel.py` | default workspace seeded; workspace create/update; member assign/list/remove; default-workspace trash-guard (400); onboarding provisions channel (dev mode); test-connection + disconnect→trashed→restore→delete lifecycle; channel update toggles status; **403 gating** for a user without `omnichannel.*` | ✅ 8/8 |
| existing suite (`auth`, `users`, `roles`, `impersonation`) | adjusted two role tests that hardcoded the catalog count (now count-agnostic — Admin holds core+module) | ✅ 58/58 |

Module tests run on SQLite via `schema_translate_map={app_omnichannel: None}`.

### Frontend
tsc 0 errors · eslint clean. Vitest (Phase A specs) still green.

### E2E (Playwright, real clicks vs **live backend**) — 5 passed
| # | Scenario | Steps | Expected | Actual |
|---|----------|-------|----------|--------|
| 1 | Channels page loads | nav Omnichannel → Channels | subtitle + Connect button | Pass |
| 2 | Connect via Embedded Signup + open detail | Connect channel → Connect with Facebook → pick number → Authorize → Done → open row | real backend provisions channel; detail tabs + **workspace link "General"** | Pass |
| 3 | Workspaces list | nav → Workspaces | default **General** + Default badge | Pass |
| 4 | Create workspace | New workspace → name → Create | lands on form, 3 tabs (Settings/Channels/Members) | Pass |
| 5 | Add member (Roles-style) | open General → Members → pick a real core user → Add member | member appears as a clickable row linking to the user form | Pass |

Run: `npm run build && npm start` then `npx playwright test e2e/omnichannel.spec.ts` → **5 passed**.

## 3. Verified invariants
- Schema isolation: 9 tables created under `app_omnichannel`; core `public` untouched; core Alembic autogenerate unaffected (module on separate `OmniBase`).
- RBAC: module permissions synced under module `omnichannel`; Admin re-granted; non-permitted user → 403.
- Onboarding dev-safe: works with no Meta app (adapter stubs the code-exchange); credentials Fernet-encrypted at rest.
- Default workspace auto-created per tenant; statuses seeded (WORKSPACE/CHANNEL/THREAD).

## 4. Carried forward
- **BL-029** per-module Alembic (Phase B uses `create_all`).
- **BL-030** DB-level cross-schema FKs into core (plain columns for now).
- **BL-031** set `OMNICHANNEL_FERNET_KEY` in prod.
- **BL-017** Meta App Review for public-tenant Embedded Signup (dev mode works now).
- Plan 05 (message processing): contacts/messages/identities/templates/quick_replies tables exist; endpoints next.
