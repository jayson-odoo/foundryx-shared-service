# Test Execution Report — Plan 10: Auth Hardening (Phase C)

**Date:** 2026-06-05 · **Branch:** `sprint-1/auth-hardening` (worktree) · **Stack:** Next :3001 (prod build) → FastAPI :8001 → Postgres · debug SMTP `aiosmtpd` :1025 with a **Mailbox (maildir) handler** so specs read delivered mail

**Automated coverage:** backend `pytest` **184 passed** (incl. 23-test `tests/test_auth_hardening.py`) · frontend Vitest **182 passed** (incl. new reset/change-password page specs + `lib/api-client.test.ts`) · Playwright **59 passed, 1 skipped** (`omnichannel › Embedded Signup` — known env-dependent case with real `NEXT_PUBLIC_META_*` set; documented in CLAUDE.md, not a regression)

---

## US-1: Forgot password end-to-end

**User story:** As a user who forgot their password, I request a reset link by email and set a new password, so I can regain access without contacting support.

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|----------|--------------|-------|----------|--------|---------|
| 1 | Request link (known email) | Dedicated tenant provisioned via operator API (spec isolation §7); tenant SMTP connection → debug mailbox | Signin → click "Forgot Password?" → fill admin email → Send Reset Link | Uniform message "If an account exists…"; `password_reset` outbox row; mail delivered with `/change-password?token=` link | As expected | `e2e/password-reset-live.spec.ts` — mailbox assertion reads the maildir |
| 2 | Request link (unknown email) | — | POST same flow with unknown address | **Identical** 200 + body; NO outbox row | As expected | pytest: status/body equality asserted; UI shows same confirmation |
| 3 | Redeem link | Mail from #1 | Open emailed link → new password + confirm → Reset Password | Success state → auto-redirect to signin | As expected | Policy hints displayed; eye toggles work |
| 4 | Old vs new password | #3 done | Sign in with OLD password, then NEW | Old → uniform 401 message; new → dashboard | As expected | |
| 5 | Single-use token | #3 done | Re-open the same emailed link, submit again | "Link expired." + "Request a New Link" → /reset-password | As expected | |
| 6 | Expired token | pytest | Rewind `expires_at` → redeem | 400 invalid/expired | As expected | `test_expired_reset_token_is_rejected` |
| 7 | Superseded token | pytest | Two forgot requests → redeem FIRST token | 400 (invalidated by the second request); second token redeems | As expected | `test_new_forgot_password_invalidates_prior_tokens` |
| 8 | Inactive user / unknown tenant | pytest | forgot-password for INACTIVE user; for unknown slug | Uniform 200; nothing enqueued | As expected | |
| 9 | Server-side password policy | pytest | Redeem with weak passwords (no upper/lower/digit/special/short) | 422 each | As expected | Policy now mirrors the frontend zod schema (gap fixed per plan §3) |

## US-2: Remember me

**User story:** As a returning user, I tick "Remember me" so my session lasts 30 days instead of 24 hours.

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|----------|--------------|-------|----------|--------|---------|
| 1 | Checkbox renders | — | Open /signin | "Remember me" checkbox, unchecked by default | As expected | Vitest + Playwright |
| 2 | Unchecked login | live stack | Login `rememberMe=false` → decode JWT `exp` | ~24h | **24.0h** | |
| 3 | Checked login | live stack | Login `rememberMe=true` → decode JWT `exp` | ~30d | **720.0h** | NextAuth `maxAge` raised to 30d; backend JWT exp is the boundary (D4) |
| 4 | 401 = session end | Vitest | apiFetch with token → 401 | NextAuth `signOut({callbackUrl:'/signin'})` | As expected | `lib/api-client.test.ts`; **note:** plan said this behavior already existed — it did not; added in Phase B |

## US-3: Brute-force protection

**User story:** As the platform owner, I want repeated failed logins throttled so accounts can't be brute-forced.

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|----------|--------------|-------|----------|--------|---------|
| 1 | Email lock after 5 fails | Dedicated tenant | 5 wrong passwords (real clicks) → 6th attempt with CORRECT password | First 5 → uniform 401; 6th → throttled, distinct "Too many attempts" message | As expected | E2E + pytest (`Retry-After` header asserted) |
| 2 | Lock is temporary | pytest | Rewind window/lock → correct login | 200 | As expected | Temp lock only — no permanent lockout (victim-DoS guard) |
| 3 | Success resets email counter | pytest | 4 fails → success → 4 more fails | Still 401 (no lock) | As expected | |
| 4 | 429 leaks nothing | pytest | While locked: wrong AND right password | Both 429 | As expected | |
| 5 | IP counter across emails | pytest | N fails across different emails | 429 from IP scope, `Retry-After` set | As expected | |
| 6 | forgot-password mail-bomb guard | pytest | Every forgot request counts toward IP | 429 past the limit | As expected | |
| 7 | set-password token guessing | pytest | Failed redeems count toward IP | 429 past the limit | As expected | |
| 8 | Spoofed X-Forwarded-For | pytest | Default `trust_proxy_headers=false`: spoofed XFF per request | Same counter (header ignored); honored only when trusted | As expected | |
| 9 | Guard before bcrypt | code | Throttle check is the first statement in the login route | Cheap rejection under attack | As expected | `app/api/v1/auth.py` |

## US-4: Signup parked + reCAPTCHA stripped

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|----------|--------------|-------|----------|--------|---------|
| 1 | Signin link hidden | — | Open /signin | No "Create an Account" | As expected | `signupEnabled` flag (frontend `NEXT_PUBLIC_SIGNUP_ENABLED`, backend `signup_enabled`) |
| 2 | Routes parked | — | /signup, /verify-email | not-found boundary | As expected | Client `notFound()` — HTTP status stays 200 on the static shell; UI asserted |
| 3 | Endpoint killed | pytest | POST /auth/signup | 404 while disabled; works when flag on | As expected | Kill-switch, not deletion (BL-032 re-enables) |
| 4 | reCAPTCHA gone | — | grep + pages | popover/hook/lib deleted; no `x-recaptcha-token` sent | As expected | Was never verified server-side (theater); real captcha = BL-041 |

---

## Environment notes / deviations

- **Signin 429 message** shows the backend detail ("Too many attempts. Please try again later.") — distinct from invalid-credentials as required, but without the ~N-minutes hint because NextAuth's `authorize()` does not surface the `Retry-After` header. The reset/change-password pages (direct api-client) DO show "~N minutes". Acceptable per D6 (distinctness is the requirement); noted for BL-039/BL-041 follow-ups.
- **Spec isolation residue:** the live spec provisions `e2e-reset-<ts>` tenants (never purged — BL-035) and the throttle accumulates per-IP counters across repeated suite runs on one machine; a mid-session cleanup (`DELETE FROM auth_throttle`, purge `e2e-%` tenants) was needed before the final green run — consistent with the CLAUDE.md residue rule.
- **Mailbox rig:** `python -m aiosmtpd -n -l localhost:1025 -c aiosmtpd.handlers.Mailbox /tmp/dreamz-e2e-mailbox` — the maildir needs `tmp/new/cur` subdirs created up front, and a leftover plain `aiosmtpd` from the plan-09 session had to be replaced (port owner check).
- **Migration:** `abbca98c3966` (auth_throttle) applied; the autogen also detected unrelated `modules` index drift — dropped from the migration, pre-existing and out of scope.
