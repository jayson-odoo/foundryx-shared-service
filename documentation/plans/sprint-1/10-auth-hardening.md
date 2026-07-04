# 10 — Auth Hardening (forgot-password, remember-me, rate limiting)

**Sprint:** 1
**Branch:** `sprint-1/auth-hardening`
**Closes:** BL-001 (login rate-limiting), BL-002 (`rememberMe` end-to-end), BL-003 (auth pages → Dreamz design/DX)
**Depends on:** sprint-1/09 (working `EmailService` — forgot-password sends real mail), sprint-1/07 (tenant resolution at login)

---

## 1. Goal

Close the three open security/UX gaps on the auth surface:

- **Forgot-password works end-to-end** — public, enumeration-safe backend + rebuilt pages,
  emails delivered via the plan-09 outbox.
- **`rememberMe` honored** — checkbox restored; short vs long session driven by the flag
  through NextAuth *and* the backend JWT.
- **Brute-force protection** — Postgres-backed dual (email + IP) throttle on the public
  auth endpoints.
- Plus cleanup: **public signup hidden** behind a flag (until BL-032), **dead reCAPTCHA
  stripped** (backend never verified it — security theater), and the leftover Metronic
  page internals rebuilt on the login-page reference DX.

Out of scope (deferred, see §9): real backend-verified captcha, refresh-token
architecture, per-tenant security policy (configurable TTLs).

---

## 2. Decision record (from the grill session)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Forgot-password design | Public `POST /auth/forgot-password`: **always 200** ("if an account exists, an email was sent"), dummy-work on not-found (timing parity, same posture as login), single-use expiring token, redeem via existing `POST /auth/set-password`. |
| D2 | Token TTLs | **Env-configurable now** (`reset_token_ttl_minutes=60`, `invite_token_ttl_minutes=10080`); per-tenant control deferred to a future tenant security-policy page (BL-039). |
| D3 | Signup | **Hidden**: `signup_enabled=False` setting → endpoint 404s, signin page hides "Create an Account", verify-email page parked behind the same flag (no live path to it). BL-032 re-enables with real tenant provisioning. |
| D4 | rememberMe durations | Unchecked = **24h** (today's default), checked = **30d**; both env-configurable. NextAuth `maxAge` set to the long value; the **backend JWT `exp` is the real boundary** (api-client already treats 401 as session end). |
| D5 | Throttle store | **Postgres behind a `ThrottleStore` interface** — auth traffic is low-QPS, on-prem stays one-service; Redis adapter lands with BL-040/BL-022. |
| D6 | Throttle policy | Dual counters: **5 fails / email / 15 min → 15 min temp lock** (temp, not permanent — hard lockout = attacker DoS on victims); **20 fails / IP / 15 min → throttle**. 429 + `Retry-After`; success resets the email counter; thresholds in Settings. Applies to `/auth/login`, `/auth/forgot-password`, `/auth/set-password`. |
| D7 | reCAPTCHA | **Strip** from reset-password/signup pages (site key unset, `x-recaptcha-token` never verified server-side). Real captcha = BL-041. |

---

## 3. Forgot-password flow (D1, D2)

### Backend

- `POST /auth/forgot-password {email, tenantSlug?}` (public):
  - Resolve tenant (plan 07 slug rules) → look up user tenant-scoped.
  - Found + active → issue single-use reset token (reuse the existing invite/reset token
    mechanism from sprint-1/02, TTL `reset_token_ttl_minutes`), **invalidate prior
    outstanding reset tokens**, enqueue `password_reset` email (plan-09 outbox).
  - Not found / inactive → perform dummy token-generation work (timing parity), send nothing.
  - **Always** `200 {message: "If an account exists for this email, a reset link has been sent."}`.
- `POST /auth/set-password` (exists) redeems — verify it enforces single-use + expiry +
  server-side password policy (add tests; fix if gaps).
- Admin-triggered `/users/{id}/reset-password` now also delivers real mail via the outbox
  (no endpoint change — EmailService swap does it).

### Frontend (BL-003 residue)

Rebuild the leftover Metronic internals on the login reference DX
(`hook → service → api-client`, shared `components/auth/` pieces, Dreamz tokens):

- **`/reset-password`** (request page): email field → `POST /auth/forgot-password` →
  success state shows the uniform message. reCAPTCHA popover removed.
- **`/change-password`** (redeem page, linked from the email): token from query →
  new password + confirm (policy hints) → `POST /auth/set-password` → success → signin.
  Invalid/expired token = friendly error + "request a new link".
- **`/signup` + `/verify-email`**: parked behind `signup_enabled` (hidden link, route
  guard renders not-found while disabled). No rebuild work beyond the flag.
- New `password-service.ts` (+ mock) and `use-forgot-password` / `use-change-password`
  hooks; pages export explicit TS interfaces (no `any`).

## 4. rememberMe (D4)

- **Frontend:** checkbox restored on signin (label "Remember me", default unchecked) —
  schema/hook/service wiring already carries the field; render it and pass it through.
- **NextAuth:** `authorize()` forwards `rememberMe` in the login POST; session
  `maxAge = 30d` (global); JWT callback stores backend-token expiry.
- **Backend:** `LoginRequest` gains `rememberMe: bool = False`;
  `create_access_token` exp = `remember_me_expire_minutes` (30d) when set, else
  `access_token_expire_minutes` (24h). Both in Settings.
- Boundary test: expired backend JWT → 401 → api-client signs the user out (existing
  behavior, add regression test).

## 5. Rate limiting (D5, D6)

### `ThrottleStore` + Postgres impl

```
auth_throttle
  id           String PK
  scope        String   -- "email" | "ip"
  key          String   -- normalized email / client IP
  window_start DateTime (UTC)
  fail_count   Int
  locked_until DateTime NULL (UTC)
  UNIQUE(scope, key)
```

`app/services/throttle.py`: `check(scope, key) -> Allowed|RetryAfter`,
`record_failure(scope, key)`, `reset(scope, key)` — interface small enough that the
future Redis impl (BL-040) is one adapter file. Atomicity via row upsert + row lock.
Stale-row cleanup piggybacks the plan-09 dispatcher housekeeping.

### Enforcement

- FastAPI dependency `throttle_guard` on `/auth/login`, `/auth/forgot-password`,
  `/auth/set-password`: check IP counter then (login only) email counter **before**
  credential work; over limit → `429` + `Retry-After` (seconds).
- Failed login → record both counters; success → reset email counter.
- Client IP: honor `X-Forwarded-For` first hop only when behind the known proxy
  (setting `trust_proxy_headers`, default false — direct uvicorn in dev).
- Uniform credential error stays `401 "Invalid email or password."`; throttle response
  is deliberately distinct (429) — locking is observable anyway; clarity beats theater.
- **Frontend:** signin/reset pages map 429 → friendly "Too many attempts — try again in
  ~N minutes." (distinct from invalid-credentials).

### Settings

```
throttle_email_max_fails=5      throttle_email_window_minutes=15   throttle_email_lock_minutes=15
throttle_ip_max_fails=20        throttle_ip_window_minutes=15
reset_token_ttl_minutes=60      invite_token_ttl_minutes=10080
remember_me_expire_minutes=43200   # 30d
signup_enabled=false            trust_proxy_headers=false
```

---

## 6. API summary

```
POST /auth/forgot-password   public, throttled, enumeration-safe (NEW)
POST /auth/set-password      existing — single-use/expiry verified, throttled
POST /auth/login             gains rememberMe; throttled (email+IP)
POST /auth/signup            404 while signup_enabled=false
```

## 7. Phases (mandatory methodology)

- **Phase A — frontend-first:** rebuilt reset-password + change-password pages against
  mock services (success / invalid-token / 429 / loading states), rememberMe checkbox,
  signup link hidden, reCAPTCHA removal, Vitest tests, Playwright real-click E2E
  against mocks (click from signin → "Forgot password?" — no direct URLs).
- **Phase B — backend (TDD, pytest+httpx):** migration (`auth_throttle`),
  ThrottleStore + guard (window expiry, lock, reset-on-success, 429 contract),
  forgot-password endpoint (enumeration safety: identical status/body/timing-shape for
  found vs not-found), token single-use/expiry/invalidation, rememberMe exp logic,
  signup flag. Swap mocks→real.
- **Phase C — E2E + report:** full stack with mailbox assertion (debug SMTP from
  plan-09 Phase C): forgot → email arrives → click link → set new password → old
  password rejected, new works; rememberMe checked vs not (inspect token exp);
  6 rapid bad logins → locked → friendly message → unlock after window.
  Test Execution Report per orchestration guide §6.

## 8. Risks / invariants

- Enumeration safety is end-to-end: response **and** outbox behavior must not leak
  existence (no error toast difference, no timing cliff).
- Throttle guard must run **before** bcrypt work (cheap rejection under attack).
- Temp lock only — no permanent lockout (victim-DoS vector).
- `signup_enabled` is a kill-switch, not a deletion — BL-032 re-enables the same code path.

## 9. Deferred → backlog

| New ID | Item |
|--------|------|
| BL-039 | Per-tenant security policy page (token TTLs, session lengths, password policy, throttle thresholds) — pairs plan 07 |
| BL-041 | Real captcha on public auth endpoints (backend-verified; replaces removed Metronic reCAPTCHA stub) |
