# Sprint 2 · Plan 03 — Tenant Branding · Test Execution Report (Phase C)

**Date:** 2026-06-06 · **Stack:** Next :3001 (production build) → FastAPI :8001 → Postgres (native) · **Spec:** `dreamz_ems_frontend/e2e/branding.spec.ts` · **Result: 3 / 3 PASSED** (4.5s, fullyParallel)

Suite layers at the time of run: backend pytest **265 passed** (incl. 28 branding + frontend-defaults parity), frontend Vitest **272 passed**, lint clean.

---

## Scenario 1 — Tenant brands the workspace end-to-end

| | |
|---|---|
| **User Story** | As a tenant admin I upload my logo, set a slogan and pick my brand color, and my whole workspace — including the pre-auth sign-in page and the browser tab — reflects my brand. |
| **Precondition** | Dedicated tenant provisioned via operator API (timestamped slug `e2e-brand-self-*` — suite is fullyParallel; branding the `default` tenant would restyle concurrent specs). |
| **Steps** | 1. Sign in as the tenant admin at `<slug>.localhost:3001` (real clicks). 2. Navigate Workspace Settings → Branding. 3. Upload a PNG logo through the Logo card's file chooser. 4. Fill slogan "Events, perfected.". 5. Type `#7c3aed` into the Primary (light) hex input. 6. Save branding. 7. Download the template. 8. Open the tenant's sign-in page (signed out, pre-auth). |
| **Expected** | Upload toasts + card flips to Replace; save toasts; the app re-themes live (`--dreamz-primary` on `<html>`); tab title = tenant name; template prefilled with the saved override; sign-in page shows the tenant logo (served from `/public/branding/{slug}/asset/logo`), the slogan, a purple Sign In button — and NO Dreamz tagline. |
| **Actual** | As expected. |
| **Remarks** | First run caught a REAL bug: Next 15 streams metadata, so the SSR `<title>` (stale within the `revalidate:60` window) landed after the provider's effect and clobbered the tenant name on hard loads. Fixed in `BrandingProvider` — a MutationObserver re-asserts the client-resolved title. |

## Scenario 2 — Unbranded tenant gets stock Dreamz branding

| | |
|---|---|
| **User Story** | As a user of a tenant that never configured branding, I see the stock product sign-in page. |
| **Precondition** | Fresh tenant with no branding row (deliberately NOT the `default` tenant — local manual testing may have branded it; residue-proof per CLAUDE.md E2E rules). |
| **Steps** | Open `<slug>.localhost:3001/signin`. |
| **Expected** | Dreamz tagline "Bringing Events to Life." visible; tab title "Dreamz EMS". |
| **Actual** | As expected. |

## Scenario 3 — Operator edits a tenant's branding from the console

| | |
|---|---|
| **User Story** | As a platform operator I manage a customer tenant's branding from the console (white-label onboarding before their admin ever signs in). |
| **Precondition** | Dedicated tenant `e2e-brand-op-*` provisioned via API; operator signs in at `platform.localhost:3001`. |
| **Steps** | 1. Click-nav Platform → Tenants. 2. Search the slug, open the row. 3. Branding tab. 4. Set slogan, Save. 5. Open the tenant's sign-in page. |
| **Expected** | Save succeeds via the operator endpoints (`tenants.manage_branding`); the OPERATOR's own console keeps stock theming (no `--dreamz-primary` override on its `<html>` — the edit targeted the other tenant); the tenant's sign-in page shows the new slogan + its name in the tab. |
| **Actual** | As expected. |

---

## Coverage notes
- Template upload roundtrip, whitelist validation (422s), asset caps/sniffing, public-endpoint enumeration uniformity, theme.css generation, XSS headers, RBAC boundaries and defaults parity are covered at the pytest/Vitest layers (28 backend + 29 frontend branding tests) — E2E intentionally exercises the click-through journeys only.
- Residue: provisioned `e2e-brand-*` tenants accumulate like all E2E tenants (purge path exists since BL-035; periodic local cleanup per CLAUDE.md).
