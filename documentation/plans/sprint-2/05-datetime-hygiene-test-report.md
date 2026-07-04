# Test Execution Report — Sprint 2 · Plan 05 (Datetime End-to-End + Menu Pruning)

**Branch:** `sprint-2/05-datetime-hygiene` · **Date:** 2026-06-06 · **Stack:** live (FastAPI :8001 + Next prod build :3001, Postgres migrated to `9d2e3f4a5b6c`, maildir smtpd :1025)

## Automated coverage

| Layer | Suite | Result |
|---|---|---|
| Backend | `tests/test_datetime_hygiene.py` (8: aware-UTC reads, +08:00 round-trip stores the instant, Z-suffixed wire on users list + ceremony payloads, PATCH /me/preferences set/clear/unknown-zone-422/auth-required) | 8/8 ✅ |
| Backend | full suite (`python -m pytest -q`) — the naive/aware sweep surfaced 4 breaks, all fixed (2 outbox tests compared against naive `utcnow()`; rule-engine fact inference didn't unwrap TypeDecorators) | 290/290 ✅ |
| Frontend | Vitest (`npm test`) incl. `lib/datetime` (11: parseUtc pins naive→UTC, tz-shifted render incl. cross-day, invalid-tz fallback, dateKey), `lib/menu-filter` (11: permission/module/platformOnly at every level, emptied parents, orphan headings, no mutation), TimezoneCard (3) | 298/298 ✅ |
| E2E | `e2e/datetime-hygiene.spec.ts` | 2/2 ✅ |
| E2E | full suite regression | 74 passed, 1 known env skip (Embedded Signup with real Meta env) ✅ |

## E2E scenarios (real clicks, per §6)

### 1. Timezone preference shifts list timestamps into the chosen zone
- **User story:** As a user in another country I pick my timezone once and every timestamp in the app renders in it.
- **Precondition:** Dedicated timestamped tenant (operator-API provisioned), admin login.
- **Steps:** signin → avatar → My Account → Preferences card → Timezone SearchSelect → search "Kiritimati" → pick Pacific/Kiritimati (UTC+14 — wall-clock always differs from any local zone) → "Timezone saved." toast → sidebar → User Management → Users → admin row's Last Sign In cell equals the wire `lastSignInAt` (asserted `Z`-suffixed) formatted by `Intl` in Pacific/Kiritimati → back on My Account, reload → picker still shows Kiritimati (preference lives on the user, not the tab).
- **Expected = Actual:** ✅ all assertions.

### 2. Menu items vanish for a role lacking `<resource>.read` (BL-014)
- **User story:** As a limited user my navigation only shows what I can actually open.
- **Precondition:** Same tenant; baseline asserts full Admin sees App Store + Users/Roles. Setup (API): Admin role stripped to `statuses.read` + `branding.read`.
- **Steps:** fresh login → App Store parent gone (sole child needs `app_store.read`) → User Management expanded: Users + Roles pruned, untagged demo entries remain → Workspace Settings: Statuses + Branding visible, Integrations + Rules pruned → direct URL to /user-management/users still lands on the friendly NoPermission page (backend/page guard stays the boundary).
- **Expected = Actual:** ✅ all assertions.

## Remarks
- **Spec contract updated by design:** `status-engine.spec.ts › user without statuses.read` used to CLICK the Statuses menu entry to reach the NoPermission page — BL-014 now prunes that entry, so the spec asserts the link is hidden and reaches the guard by direct navigation instead.
- **Stale-server gotcha (again):** first run failed with chunk-load 400s — a long-running `next-server` from before the rebuild still owned :3001 (my `npm start` died `EADDRINUSE` silently); `lsof` per the CLAUDE.md port-owner ritual, kill, restart. The wrong-build rule held.
- **Code-review round (7 finders → 3 verifiers): 7 confirmed findings fixed** — header mega-menu (+mobile) rendered MENU_MEGA unfiltered (BL-014 leak; now tagged + same `filterMenu` pass as the sidebar, sub-components look sections up by title); `filterMenu` memoized in the sidebar; tz-save no longer reports success as an error when the session re-pull hiccups; `ProfilePreferences` inherits `ApiModel`; 8 dead `BaseModel` imports stripped; orphaned tz-blind `i18n/format.ts` deleted; dead mock export removed. 1 plausible noted in `ApiModel`'s docstring (nested-collection datetimes bypass the wildcard net — no such field exists). Full suites re-run green after fixes.
- **E2E residue purged twice** (28 then 34 `e2e-%` tenants, user-approved) via archive → `TenantService.purge` — `tenants.spec.ts` page-1 assertions were failing on residue, not code. Auto-purge remains BL-069.
- Spec-setup detour: `/roles?page=1` looked empty until it turned out the list endpoint's `page` is 0-indexed (`Query(0, ge=0)`) — not a bug; setup switched to `/roles/options` (the proper lightweight picker) anyway.
