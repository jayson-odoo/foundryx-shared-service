# Sprint 2 · Plan 05 — Datetime End-to-End + Menu Pruning (Hygiene Sweep)

**Branch:** `sprint-2/05-datetime-hygiene`
**Closes/advances:** BL-012 (UTC end-to-end, High), BL-014 (menu visibility by permission — remaining core-item half), BL-015 (close — already fixed by `tenant_id_from_role`, `models/permission.py:20`; backlog status was stale).
**Depends on:** plan 04 (My Account page hosts the timezone picker).

---

## Locked design decisions (from grilling)

1. **BL-012 = full timestamptz sweep**, not serialize-only:
   - Every `DateTime` column → `DateTime(timezone=True)` (Postgres `timestamptz`) across all core models (~14 files) AND `modules/omnichannel/models.py`. One Alembic migration for core; omnichannel follows its current create_all reality (per-module Alembic remains BL-029 — migration handled in core Alembic transitionally, consistent with BL-029's open state).
   - Server defaults: naive `func.now()` / `datetime.utcnow()` → timezone-aware UTC (`datetime.now(timezone.utc)` / `func.now()` on timestamptz).
   - Wire: Pydantic serializes ISO-8601 with `Z`/offset (global model-config serializer — one place, not per-schema).
   - Frontend: parse-as-UTC, format via `Intl.DateTimeFormat` with the **user's timezone**; one shared `lib/datetime.ts` formatter — sweep existing ad-hoc date rendering onto it.
2. **Timezone source = user profile field**: `users.timezone` (IANA name, nullable; null = browser tz via `Intl.DateTimeFormat().resolvedOptions().timeZone`). Picker (searchable — SearchSelect mandate) on plan 04's My Account page; value rides the login payload + session.
3. **BL-014 = `MenuItem.permission` key** on the menu config, pruned via session permissions (`useCan`), same mechanism family as `MenuItem.module` / `platformOnly`. Parent with zero visible children disappears (parents are non-clickable per shell rules).
4. **BL-015:** no code change — flip backlog row to Closed with pointer to `tenant_id_from_role`.
5. **BL-010 / BL-011 stay backlog** (no list hurts yet; keyset premature).

## Work items

### Backend
- Audit + flip all `DateTime` columns; Alembic migration (`USING ... AT TIME ZONE 'UTC'` for existing naive rows — they ARE UTC by convention).
- Global Pydantic datetime serializer (Z-suffixed). Spot-check schemas with manual `strftime`.
- `users.timezone` column + `PATCH /me/preferences` acceptance + login payload/session field.
- Tests: serializer emits offset; round-trip stays UTC; throttle/outbox lease math unaffected by tz-aware comparison (naive-vs-aware `TypeError` is the classic landmine — grep all `datetime.utcnow()` comparisons).

### Frontend
- `lib/datetime.ts`: `formatDateTime(iso, {tz})` family; user tz from session, fallback browser.
- Sweep list cells / detail fields / inbox timestamps onto it.
- Timezone SearchSelect on My Account.
- Menu pruning: add `permission` to core `MenuItem` entries (`users.read`, `roles.read`, `statuses.read`, `tenants.read`, …) + filter in menu rendering.

### Phases
- **Phase A (frontend):** datetime lib + sweep + tz picker (mocked pref) + menu pruning with Vitest on the filter logic.
- **Phase B (backend, TDD):** migration + serializer + preference endpoint; full pytest sweep green (naive/aware mismatches surface here).
- **Phase C (E2E):** user with non-local tz preference sees shifted timestamps on a list; menu items vanish for a role lacking `<resource>.read` (real clicks, dedicated role + user, timestamped names).

### Risk notes
- Naive/aware comparison `TypeError`s can appear anywhere `utcnow()` survived — grep-driven sweep (`utcnow|datetime.now()` without tz) is part of Phase B.
- One Postgres serves all worktrees: run the migration only from the branch being served (CLAUDE.md worktree rule).
