# Sprint 1 · Plan 01 — Login Page

**Status:** ✅ DONE — Phase A (frontend) · Phase B (backend) · Phase C (review + merged to `main`). Code-review findings resolved (#1–#3 fixed, #4/#5 → BL-005/BL-002).
**Test reports:** [frontend](./01-login-page-test-report-frontend.md) · [backend](./01-login-page-test-report-backend.md)
**Branch:** `sprint-1/login-page`
**Figma:** `base/auth/login` — file `fPQB8IuZ76vLaHOjMQqsfA`
- Full frame: node `38726:119990`
- Right (form): `38726:119991` · Container: `38726:119996`
- Left (brand): `38726:120008` · Illustration `S_dialogue`: `38726:120009` · Logo `logo.png`: `38726:120027`
**Backlog spawned:** [BL-001 rate-limiting](../../backlogs/backlog.md), [BL-002 rememberMe](../../backlogs/backlog.md), [BL-003 signup/reset migration](../../backlogs/backlog.md), [BL-004 full multi-tenancy](../../backlogs/backlog.md)

---

## 1. Goal

Ship the Dreamz EMS sign-in page matching the Figma design, evolving the existing
Metronic `signin/page.tsx` rather than rebuilding. Frontend-first (mock auth) to tune
UI/UX, then wire the existing FastAPI `/auth/login`, refactor it to be governance-compliant,
fold in cheap security fixes, and verify end-to-end.

## 2. Design summary (from Figma)

Split-screen, light theme.

**Left panel** — solid orange `#FF5A00`:
- `DREAMZ` wordmark logo (top).
- Tagline "Bringing Events to Life." (white, Poppins).
- Line-art illustration (person + laptop, teal stroke), bottom-anchored.

**Right panel** — white:
- Title "Welcome to Dreamz EMS." (navy, Poppins 600 / 30px).
- Subtitle "New Here? **Create an Account**" — "New Here?" muted, "Create an Account" orange → `/signup`.
- Email label + input (placeholder "Your email", Inter 400).
- Password label + "Forgot Password?" (orange) → `/reset-password`.
- **[gap-fill]** Password input (toggle visibility) — not drawn in Figma, added.
- **[gap-fill]** Full-width orange primary **"Sign In"** button — not drawn in Figma, added.
- Footer: Terms · Plans · Contact Us (orange, `href="#"` stubs).

Dropped from existing Metronic page: Google OAuth button, blue demo-credentials alert.

## 3. Decisions (grill outcomes)

| # | Decision |
|---|----------|
| Scope | Evolve existing `signin/page.tsx` + `BrandedLayout`; fill Figma gaps with restyled functional elements. |
| Google + demo alert | Dropped. |
| Footer links | Styled, `href="#"` stubs; real pages later sprints. |
| Left panel | Match Figma: solid orange + DREAMZ logo + illustration + tagline. |
| Assets | Export logo + illustration from Figma as **SVG** → `public/media/dreamz/`. |
| Credentials | Empty fields (no prefill). Canonical seed `demo@example.com` / `demo1234`. |
| Route | Keep `/signin` (Figma "login" is a layer name only). |
| Frontend-first | Submit hits a **mock auth service** behind the service layer; swap to real `signIn`→FastAPI in backend phase. |
| Theme / responsive | Light pixel-match now; dark kept functional (not pixel-tuned); mobile stacks single-column, illustration panel hidden `<lg`. |
| Submit button | "Sign In", full-width orange, below password. |
| `<style>` tag | **Delete** the injected `<style>` block in `branded.tsx` (governance violation); Left color via utility/token classes. |
| Backend | Refactor `/auth/login` → Service-Repository (router does validation+response only). Fold cheap security fixes (#1 enumeration, #2 timing, #5 password policy). Defer rate-limiting + rememberMe to backlog. |
| Tenancy | **Groundwork only:** `tenant_id` on `users` (default tenant seeded), `tenant_id` JWT claim, tenant-scoped `UserRepository` lookups. Behavior stays single-tenant. Full model → BL-004. |
| Tests | Vitest + React Testing Library (component); `@playwright/test` (E2E real-click); pytest + httpx (backend). |
| Git | `git init` → `main`; work on `sprint-1/login-page`. |
| Typography | Add **Poppins** via `next/font/google` (display) + keep **Inter** (body/inputs), as Figma specifies. |
| Reuse | Extract shared `AuthBrandPanel` + `AuthFooter`. Login consumes them. Don't migrate signup/reset (→ BL-003). |

## 4. Frontend layering (enforced)

`signin/page.tsx (UI)` → `useSignin` hook → `authService` (mock | real) → `lib/api-client` → FastAPI.
UI never calls fetch/axios directly.

## 5. Build order

### Phase A — Frontend-first (mock backend), tune UI/UX
1. `git init`, `.gitignore`, baseline commit, branch `sprint-1/login-page`.
2. Add Poppins font (`next/font/google`); expose brand-font CSS var. Confirm `--primary` = `#FF5A00` (dreamz-tokens) wins over Metronic blue.
3. Export SVG assets from Figma → `public/media/dreamz/` (DREAMZ logo, illustration).
4. Build shared components: `AuthBrandPanel`, `AuthFooter` (Metronic utility classes only, explicit TS interfaces, no `<style>`/raw CSS).
5. Rewrite `BrandedLayout` → solid-orange split using `AuthBrandPanel`; **delete `<style>` block**.
6. Build `authService` with a **mock** implementation (fakes loading → success/error). Toggle via env/flag.
7. `useSignin` hook wrapping the service; manages loading/error/redirect state.
8. Restyle `signin/page.tsx` to Figma: Poppins title/subtitle, email, password (+toggle), "Sign In" button, footer. Empty fields. Drop Google + demo alert.
9. **Vitest (TDD red-green):** form validation (email format, required, min-length), loading/error/success states, mock service behavior.
10. **Playwright E2E (real clicks):** navigate via UI, type creds, submit, assert redirect/error — against mock. Produce Test Execution Report markdown.
11. Iterate UI/UX until satisfactory.

### Phase B — Backend wiring + hardening + full testing
12. **pytest (TDD red-green)** for: success, wrong password (401), unknown email (uniform 401, **no enumeration**), inactive (403), timing parity (#2), server-side password policy (#5).
13. Refactor `app/api/v1/auth.py`: extract `AuthService` + `UserRepository`. Router = validation + response only. Move DB queries out.
14. Apply security fixes: #1 uniform error message, #2 dummy bcrypt on not-found path, #5 Pydantic `min_length` on password.
14b. **Tenancy groundwork:** add `tenant_id` to `User` model + migration; seed a default tenant in `init_db`; include `tenant_id` in JWT claims; `UserRepository.get_by_email` scoped by `tenant_id`. Behavior stays single-tenant (default tenant). pytest covers tenant-scoped lookup.
15. Swap `authService` mock → real `signIn('credentials')` → NextAuth → FastAPI `/auth/login`.
16. Re-run full **Playwright E2E** against live FastAPI (port 8001) with seed `demo@example.com`/`demo1234`. Regenerate Test Execution Report.
17. Backend `/me` + protected redirect smoke check.

### Phase C — Review + merge
18. Code-review agent must pass (hard-fail rules: no DB-in-router, no axios/fetch-in-component, no `any`, no raw CSS/`<style>`, no core-table alteration).
19. Merge `sprint-1/login-page` → `main`.

## 6. Files (anticipated)

**Frontend**
- `app/layout.tsx` — add Poppins.
- `app/(auth)/layouts/branded.tsx` — solid orange, use `AuthBrandPanel`, remove `<style>`.
- `app/(auth)/signin/page.tsx` — restyle, drop Google/demo-alert, empty fields, Sign In button.
- `components/auth/auth-brand-panel.tsx` (new) — left panel.
- `components/auth/auth-footer.tsx` (new) — footer links.
- `services/auth-service.ts` (new) — mock | real auth.
- `hooks/use-signin.ts` (new).
- `public/media/dreamz/` (new) — logo.svg, illustration.svg.
- Test: `*.test.tsx` (Vitest), `e2e/signin.spec.ts` (Playwright), config files.

**Backend**
- `app/api/v1/auth.py` — slim router.
- `app/services/auth_service.py` (new).
- `app/repositories/user_repository.py` (new) — tenant-scoped lookups.
- `app/schemas/auth.py` — password `min_length`.
- `app/models/user.py` — add `tenant_id`. `app/models/tenant.py` (new, default tenant). `scripts/init_db.py` — seed default tenant. `app/security.py` — `tenant_id` in JWT claims.
- `tests/test_auth.py` (new), pytest config.

## 7. Acceptance criteria

- Visual parity with Figma (light) on desktop; graceful stack on mobile; dark not broken.
- Valid seed creds → redirect to `/`. Invalid → inline error, no user enumeration.
- No governance violations (no `<style>`, no raw CSS, no DB-in-router, no fetch-in-component, no `any`, explicit TS interfaces).
- Vitest + pytest green; Playwright E2E (real clicks) green; Test Execution Report produced.
- Code review passes; merged to `main`.
