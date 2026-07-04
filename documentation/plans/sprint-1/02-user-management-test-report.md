# Sprint 1 · Plan 02 — User Management · Test Execution Report

**Stack under test:** Next.js :3001 → FastAPI :8001 → Postgres (`dreamz_ems`).
**Date:** sprint-1/user-management branch.

## Summary

| Layer | Tool | Result |
|---|---|---|
| Backend | pytest + httpx (in-memory SQLite) | **33 passed** |
| Frontend unit/component | Vitest + RTL | **16 passed** |
| E2E (real user clicks) | Playwright vs live stack | **12 passed** |

## Backend (`tests/test_auth.py`, `tests/test_users.py`)

| Area | Scenarios |
|---|---|
| Auth | login success/inactive/wrong-pw, no enumeration, signup, `/me`, **login returns `roles[]` (no `roleId`)** |
| List | returns active users, **sort by name asc/desc**, sort by status/joined/lastSignIn/email, search (name+email), filter `status eq`, pagination, invalid filter field → 422 |
| CRUD | create → `INVITED` + listed, duplicate email → 409, update name/status, **assign roles (M2M)**, INVITED status not overwritten by save |
| Trash | trash → hidden from active / shown in trashed → restore |
| Record-nav | `/users/at?index=` returns correct neighbour + total |
| Invite | create issues token → `/auth/set-password` redeems → ACTIVE + login works; invalid token → 400 |
| Roles / Prefs / Export | `/roles` lists; `/me/preferences` round-trips; `/users/export` CSV header + rows |

## Frontend unit (Vitest)

- `StatusBadge` — maps status→label; falls back on unknown.
- `userFormSchema` — rejects empty name / invalid email / unknown status; accepts valid + no-roles.
- `MultiSelect` — renders selected as pills; **Select all** selects every option; **Clear all** empties.
- (plus existing signin page tests.)

## E2E (Playwright, real clicks — no URL jumping)

| Scenario | Steps | Expected | Actual |
|---|---|---|---|
| Nav to list | login → expand "User Management" → click "Users" | lands on `/user-management/users`, seeded user visible | ✅ |
| Search | type "manager" | only matching user shown | ✅ |
| Row → form | click a row | form view: name heading, tabs, **`N / M` record-nav** | ✅ |
| Edit & save | Edit → change name → Save (then revert) | heading reflects new name | ✅ |
| Trashed view | click "Trashed" | list reloads in trashed scope | ✅ |

## Notes / follow-ups
- Existing session JWTs are invalidated by the SQLite→Postgres swap (different user ids) — users must re-login once.
- Reserved-TLD emails (`.test`) are rejected by `EmailStr`; tests use `.io`.
