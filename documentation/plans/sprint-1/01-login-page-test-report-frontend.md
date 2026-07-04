# Test Execution Report — Login Page (Frontend Phase, mock auth)

**Plan:** [01-login-page](./01-login-page.md) · **Branch:** `sprint-1/login-page`
**Phase:** A (frontend-first, `NEXT_PUBLIC_AUTH_MODE` unset → mock auth service)
**User Story:** As a FoundryX EMS user, I can sign in from a branded login page so I can reach my dashboard.
**Suites:** Vitest (component/unit, 10) · Playwright (E2E real-click, 6) — **all green**.

> Backend not wired this phase. The happy-path redirect-to-dashboard is verified
> at the unit level (router.push('/') asserted) and deferred for full E2E to the
> backend phase against live FastAPI.

---

## Playwright E2E (real user clicks)

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|----------|--------------|-------|----------|--------|---------|
| E1 | Brand panel + form render | On `/signin` | Load page | Heading, tagline, email, password, Sign In visible | As expected | Pass |
| E2 | Empty submit blocked | On `/signin` | Click **Sign In** with empty fields | Validation message shown, no submit | As expected | Pass |
| E3 | Wrong credentials | On `/signin` | Type `wrong@example.com` / `badpass1`, click **Sign In** | Generic "Invalid email or password." (no enumeration), stays on `/signin`, no creds in URL | As expected | Pass |
| E4 | Password visibility toggle | On `/signin` | Type password, click show-password | Input `type` flips `password`→`text` | As expected | Pass |
| E5 | Navigate to sign-up | On `/signin` | Click "Create an Account" | URL → `/signup` | As expected | Pass |
| E6 | Navigate to reset | On `/signin` | Click "Forgot Password?" | URL → `/reset-password` | As expected | Pass |

## Vitest (component + unit)

| # | Scenario | Expected | Actual | Remarks |
|---|----------|----------|--------|---------|
| U1 | Page renders heading, account link (`/signup`), submit | Present | As expected | Pass |
| U2 | Empty submit → validation, service NOT called | Blocked | As expected | Pass |
| U3 | Malformed email → validation, service NOT called | Blocked | As expected | Pass |
| U4 | Rejected creds → generic error, no redirect | Error shown, `push` not called | As expected | Pass |
| U5 | Successful sign-in → `router.push('/')` | Redirects | As expected | Pass |
| U6 | Password visibility toggle | `type` flips | As expected | Pass |
| U7 | mockAuthService: seeded creds resolve | Resolves | As expected | Pass |
| U8 | mockAuthService: email case-insensitive | Resolves | As expected | Pass |
| U9 | mockAuthService: wrong password → `AuthError` generic | Throws generic | As expected | Pass |
| U10 | mockAuthService: unknown email → SAME message (no enumeration) | Same message | As expected | Pass |

## Manual visual verification (Playwright screenshots)

| View | Expected (Figma) | Actual | Remarks |
|------|------------------|--------|---------|
| Desktop 1440×900 | Split-screen: orange brand left, form right | Matches | Pass |
| Error state | Red alert above form, values retained | Matches | Pass |
| Mobile 390×844 | Brand panel hidden, form full-width, footer pinned | Matches | Pass |

## Commands

```bash
npm test          # vitest run  → 10 passed
npm run test:e2e  # playwright   → 6 passed
```

## Result

**PASS** — frontend prototype meets acceptance for Phase A. Pending: backend wiring
(Phase B) re-runs E2E with `NEXT_PUBLIC_AUTH_MODE=real` against FastAPI, adds the
full happy-path login E2E + pytest suite.
