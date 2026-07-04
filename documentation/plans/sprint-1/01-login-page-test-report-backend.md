# Test Execution Report — Login Page (Backend Phase, live FastAPI)

**Plan:** [01-login-page](./01-login-page.md) · **Branch:** `sprint-1/login-page`
**Phase:** B (backend wiring + hardening + tenancy groundwork)
**Stack under test:** NextAuth → FastAPI `/auth/login` (port 8001) → AuthService → UserRepository → SQLite.
**Suites:** pytest (10) · Playwright real-backend E2E (2) · plus Phase-A regression (Vitest 10, mock E2E 6) — **all green**.

---

## pytest (backend, in-memory SQLite, seeded default tenant)

| # | Scenario | Expected | Actual | Remarks |
|---|----------|----------|--------|---------|
| P1 | Login success | 200, token + user, `user.tenantId` = default tenant | As expected | Pass |
| P2 | Token carries `tenant_id` claim | JWT decodes with `tenant_id` + `sub` | As expected | Pass |
| P3 | Wrong password | 401, "Invalid email or password." | As expected | Pass |
| P4 | Unknown email | **401 (not 404)**, same generic message | As expected | No enumeration |
| P5 | Unknown email vs wrong password | Identical status + body | As expected | No enumeration |
| P6 | Inactive account | 403 | As expected | Pass |
| P7 | Unknown-email path runs bcrypt | Response not near-instant (>10ms) | As expected | Timing parity (no oracle) |
| P8 | Signup short password | 422 (Pydantic `min_length=8`) | As expected | Server-side policy |
| P9 | Signup success then duplicate | 201 then 409 | As expected | Pass |
| P10 | `/me` requires + accepts token | 401 without, 200 with (`tenantId` present) | As expected | Pass |

## Playwright E2E — real backend (`npm run test:e2e:real`)

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|----------|--------------|-------|----------|--------|---------|
| R1 | Happy-path login | Backend up + seeded, real-auth mode | Type `demo@example.com`/`demo1234`, click Sign In | Leaves `/signin`, lands on dashboard `/` | As expected | Full stack |
| R2 | Bad creds from real backend | Backend up | Type wrong password, click Sign In | Generic "Invalid email or password.", stays on `/signin` | As expected | No enumeration end-to-end |

## Regression (Phase A, still green)

| Suite | Count | Result |
|-------|-------|--------|
| Vitest (component/unit) | 10 | Pass |
| Playwright mock E2E | 6 | Pass |

## Security fixes verified

| Gap (plan §security) | Fix | Verified by |
|----------------------|-----|-------------|
| #1 User enumeration | Uniform 401 "Invalid email or password." for unknown email + wrong password | P3, P4, P5, R2 |
| #2 Timing oracle | Dummy bcrypt compare on not-found path | P7 |
| #5 No server password policy | `SignupRequest.password` `min_length=8` | P8 |

> Deferred (logged): #3 rate-limiting → [BL-001], #4 rememberMe end-to-end → [BL-002].

## Architecture / governance

- Router (`app/api/v1/auth.py`) holds **no DB queries** — delegates to `AuthService` → `UserRepository`. Layering hard-fail resolved.
- Tenancy groundwork: `tenant_id` on `users` (FK → `tenants`), per-tenant email uniqueness, `tenant_id` in JWT, tenant-scoped repository lookups, default tenant seeded. Behaviour single-tenant. Full model → [BL-004].

## Commands

```bash
# backend
python -m pytest -q                       # 10 passed
uvicorn main:app --port 8001              # live API

# frontend
npm test                                  # vitest  → 10 passed
npm run test:e2e                          # mock E2E → 6 passed
npm run test:e2e:real                     # real E2E → 2 passed (needs backend up + seeded)
```

## Result

**PASS** — backend refactored to Service-Repository, cheap security fixes landed and
verified, tenancy groundwork in place, full-stack login works end-to-end. Ready for
Phase C (code review → merge).
