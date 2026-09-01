# Sprint 2 · Plan 04 - Account Security: Change-Email Flow + Login Error Distinction

**Branch:** `sprint-2/04-account-security`
**Closes/advances:** BL-008 (change-email + re-verification), BL-005 (auth-failure vs infra-error on login). Creates the **My Account** page that plan 05 reuses for the timezone preference.

---

## Context

Email is read-only after user creation (BL-008). The user mandate: changing email must prove the requester controls the CURRENT mailbox - but old-email approval alone cannot prove the NEW address is deliverable (a typo would bind the account to a mailbox nobody owns, with password resets going to the wrong place). Hence dual confirmation. Separately, BL-005: NextAuth v4 collapses every `authorize()` failure into `CredentialsSignin`, so a backend outage reads as "Invalid email or password."

### Locked design decisions (from grilling)

1. **Self-service flow = old approves + new verifies (dual confirmation):**
   1. User requests change on the account page, **re-enters password** (fresh proof, not just a live session).
   2. Approve link → **OLD** email ("Someone requested changing your email to n***@x.com - Approve / wasn't me").
   3. On approval, verify link → **NEW** email.
   4. Email flips **only after the new-side verify**; final notification to the old address. Either link single-use; whole request expires; re-request invalidates prior outstanding requests.
2. **Admin path = instant + notify both.** Admin with `users.update` edits email directly on the user form; applies immediately; notification mail to old + new. Ceremony is self-service-only.
3. **Token infra reused from plan 10** (single-use tokens, TTL config, outbox email, throttle patterns). New TTL setting `email_change_token_ttl_minutes` (default 60).
4. **New minimal My Account page** (`/account`, own DX: components → hooks → service → api-client) - own profile summary, change-email flow, change-password link. Replaces reliance on unwired Metronic `/account` demo pages; future home for self-service prefs (avatar, timezone in plan 05). Perm-free like `/auth/me` (self-scope only).
5. **BL-005:** `authorize()` distinguishes failure classes - network error / non-401 backend response → distinct error code surfaced through the NextAuth error string (the plan-10 429-detail channel precedent) → sign-in shows "Service temporarily unavailable - try again." vs the uniform credentials message. No user-enumeration regression: 401 keeps the uniform message.

---

## Data model (core `public`, Alembic migration)

### `email_change_requests` (new)
- `id`, `tenant_id`, `user_id` FK → users
- `new_email` String not null (normalized lowercase)
- `old_token_hash` / `new_token_hash` (hashed like plan-10 reset tokens; `new_token` generated only at approve time)
- `status`: `PENDING_OLD` → `PENDING_NEW` → `COMPLETED` | `CANCELLED` | `EXPIRED`
- `expires_at`, `created_at`, `completed_at`
- New request for the same user cancels prior non-terminal rows.

## Backend

- `POST /me/change-email {newEmail, password}` - auth'd, self-only. Verifies password (bcrypt, throttle-counted like login fails), validates new email format + **uniqueness within tenant** (uniform error - no cross-account enumeration), creates request, sends approve mail to OLD address via outbox.
- `POST /auth/approve-email-change {token}` - public, single-use; `PENDING_OLD → PENDING_NEW`, sends verify mail to NEW address.
- `POST /auth/verify-email-change {token}` - public, single-use; flips `users.email` (uniqueness re-checked transactionally), `COMPLETED`, notify old address.
- `GET /me/change-email` / `DELETE /me/change-email` - pending-request status / cancel.
- Throttle: token-redeem failures count into the IP bucket (plan-10 pattern).
- Admin path: `PATCH /users/{id}` accepts `email` (currently rejected/read-only) when actor ≠ target and holds `users.update` → immediate change + notify both. Self-edit via admin form still routes to the ceremony (no self-bypass).
- Email templates: `email_change_approve`, `email_change_verify`, `email_change_notice` (Jinja2, Foundryx base, text siblings).
- Layering: `api/v1/me.py` + `auth.py` → `services/email_change_service.py` → repositories.

## Frontend

- **`/account`** page: profile card (name, email, roles), "Change email" opens flow (new email + current password → "Check your current inbox" state → pending banner with cancel), change-password link.
- `/approve-email-change?token=` + `/verify-email-change?token=` public pages on the auth DX (`(auth)` layout, like `/change-password`).
- Session note: JWT carries user id, not email - no forced logout needed; session email refreshes via NextAuth `update()` after completion.
- BL-005: `auth-service.ts` + signin form render the distinct infra message.

## Phases

- **Phase A (frontend, mock):** account page + flow states (request → check-old-inbox → pending → done; cancel; expired-token error pages) + infra-error signin state, mock service tunable. Vitest on form validation + state rendering.
- **Phase B (backend, TDD):** request/approve/verify happy path; typo'd-new-email never flips anything; expired/reused/foreign-tenant tokens 4xx; uniqueness race; password-fail throttling; admin instant path + notifications; outbox rows asserted. Alembic migration.
- **Phase C (E2E):** real-click flow against maildir smtpd rig (plan-10 pattern - quoted-printable decode for token extraction): change email → approve from old mail → verify from new mail → re-login with NEW email works, OLD email 401s. Timestamped E2E user names.
