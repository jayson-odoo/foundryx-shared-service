# Test Execution Report — Plan 09: Integration Core & Email (SMTP)

**Date:** 2026-06-05 · **Branch:** `sprint-1/integration-core-email` · **Stack:** Next :3001 (prod build) → FastAPI :8001 → Postgres · debug SMTP `aiosmtpd` :1025

## Automated coverage

| Layer | Suite | Result |
|---|---|---|
| Backend | `pytest` (full) — 21 new in `test_integrations.py` + `test_email_outbox.py` | **122 passed** |
| Frontend | `vitest` (full) — 18 new across card / wizard / hook | **115 passed** |
| E2E | `playwright e2e/integrations.spec.ts` (live stack, real SMTP) | **5/5 passed** |

## E2E scenarios (real user clicks; dedicated tenant provisioned per spec)

| # | Scenario | Steps | Expected | Actual |
|---|---|---|---|---|
| 1 | Integrations page loads | Login fresh tenant admin → sidebar Workspace Settings → Integrations | SMTP card, "Not connected", Connect button | ✅ Pass |
| 2 | Guided connect + REAL connection test | Connect → fill host `localhost:1025`, security None, from email → Save & continue → Test connection | Real SMTP NOOP succeeds → "connected" step → card Connected, summary `host · from`; persists across reload (DB row) | ✅ Pass |
| 3 | Failed connection test | Same but port 9 (closed) → Test connection | Real transport error shown in wizard; Skip → card status Error + message | ✅ Pass |
| 4 | Card quick-test | Connect, Skip (Needs test) → card **Test** | Inline connection check, toast "Connection verified.", badge → Connected | ✅ Pass |
| 5 | Disconnect | Card Disconnect → confirm dialog → Disconnect | Card returns to Not connected | ✅ Pass |

## Key backend behaviors verified (pytest)

- Credentials **encrypted at rest** (Fernet; plaintext never in DB row) and **never echoed** by any endpoint; blank credential on update keeps stored secret; non-blank rotates it.
- Unique (tenant, provider) → 409; unknown provider → 422; cross-tenant access → 404; unauthenticated → 401.
- Test endpoint updates `status`/`lastTestedAt`/`lastError` (ACTIVE on pass, ERROR on fail).
- Outbox: enqueue-on-send; **dev-log fallback** (no connection → console link, row audited as sent); dispatcher send/retry-with-backoff/tenant→platform fallback/terminal failure; **per-connection rate limit** defers excess; retention pruning.
- Found & fixed during TDD: enqueued row was flush-only after the invite repo's early commit → silently rolled back.

## Manual verification

- User-reported: wrong Gmail credentials showed "Connected" on the Phase A mock → re-tested on Phase B: real 535 from smtp.gmail.com surfaces on card. Resolved by design (mock → real swap).
- UX feedback applied mid-phase: default test = **connection check** (no recipient); test-email optional behind a link; card Test = inline + toast; password fields gained an eye toggle.

## Known environmental failures (full suite — not plan-09 code)

| Spec | Cause |
|---|---|
| `omnichannel.spec.ts` Embedded Signup | Documented: real `NEXT_PUBLIC_META_*` set in `.env.local` |
| `tenants.spec.ts` ×2 | ~50 accumulated `e2e-*` tenants push seeded rows off page 1 (no tenant purge yet — BL-035) |
| `roles-permissions.spec.ts` create/delete | Leftover `E2E Temp Role` from an interrupted run → unique-name conflict |
