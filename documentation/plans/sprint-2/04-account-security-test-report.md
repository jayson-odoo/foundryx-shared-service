# Test Execution Report — Sprint 2 · Plan 04 (Account Security: Change-Email + BL-005)

**Branch:** `sprint-2/04-account-security` (rebased onto post-branding main) · **Date:** 2026-06-06 · **Stack:** live (FastAPI :8001 + Next prod build :3001, Postgres, maildir smtpd :1025)

## Automated coverage

| Layer | Suite | Result |
|---|---|---|
| Backend | `tests/test_email_change.py` (13: full ceremony, pending/cancel, re-request supersede, wrong-password 400 + throttle lock, same-email 422, bad/cross-endpoint/reused tokens 400, expiry, typo'd-address never flips, uniqueness race 409, admin instant + notify both, admin self-bypass 409, admin duplicate 409, plain PATCH untouched) | 13/13 ✅ |
| Backend | full suite (`python -m pytest -q`) | 278/278 ✅ |
| Frontend | Vitest (`npm test`) incl. account page (7), redeem pages (5), email-change mock contract (13), authorize() BL-005 (5) | 270/270 ✅ |
| E2E | `e2e/account-security.spec.ts` | 3/3 ✅ |
| E2E | full suite regression (after residue purge) | 67 passed, 1 pre-existing parallel flake (`roles-permissions` impersonation — passes alone) ✅ |

## E2E scenarios (real clicks, per §6)

### 1. Request → pending banner → cancel kills the link
- **User story:** As a signed-in user I start an email change, see it pending, and can withdraw it.
- **Precondition:** Dedicated timestamped tenant (operator-API provisioned), tenant SMTP → maildir smtpd, admin login.
- **Steps:** signin → avatar dropdown → My Account → Change email → wrong password (rejected in dialog, "Incorrect password.") → correct password → "Check your current inbox" → Got it → pending banner ("awaits approval from your current inbox") → approve mail arrives at the CURRENT address → Cancel request → banner gone → cancelled approve link → Approve Change → "Link expired."
- **Expected = Actual:** ✅ all assertions.

### 2. Full ceremony: approve old → verify new → re-login with new email
- **User story:** As a user I move my account to a new mailbox only after BOTH mailboxes confirm.
- **Steps:** request change → approve mail (old inbox, masked target `r***@…`) → /approve-email-change → Approve Change → "Change approved." → verify mail arrives at the NEW address → /verify-email-change → Confirm New Email → "Email updated." → notice mail to the PREVIOUS address (carries the full new email) → Go to Sign In → OLD email rejected with the uniform 401 message → NEW email + same password lands on the dashboard.
- **Expected = Actual:** ✅ all assertions.

### 3. Redeemed links are single-use
- **Steps:** completed ceremony's verify link → Confirm New Email → "Link expired." + "Go to My Account" path back.
- **Expected = Actual:** ✅.

## Remarks
- **Mail-read race fixed in-spec:** the serial flow sends several mails to one address — `expectMailTo` takes a `containing` discriminator (masked target / full new email) so a stale message can't satisfy the wait. Spec timeout raised to 120s: the outbox dispatcher delivered up to ~35s after enqueue under a busy parallel suite (default 30s test timeout lost that race).
- **Header fix verified visually:** `/account` previously rendered the Metronic demo `<Breadcrumb />` slot (empty header); the mega menu now renders on every page.
- **Pre-existing suite issues fixed en route:** `signin.spec.ts` asserted the fixed slogan, stale since branding (slogan is tenant-configurable; default tenant is branded with no slogan) — assertion moved to the panel logo. Omnichannel demo threads' CSW windows had expired by wall-clock (seed is idempotent-skip) — refreshed; auto-refresh tracked in BL-069.
- **E2E residue purged twice** (34 then 14 `e2e-%` tenants) via `TenantService.purge` — each full-suite run regrows ~10 tenants and re-breaks `tenants.spec.ts` page-1 assertions; auto-purge tracked in BL-069.
