# Plan 58: contact erase register (who erased what, and when)

UAC: `58-contact-erasures-register-acceptance-criteria.md`. Follow-up to plan 56 C (PR #188, crew browser pass GO 5 Nov). Size L by the crew contract (new table + migration), minus the mock (no UI).

## Journey

An Admin erases a contact from the staff menu, or an integration erases one with its workspace API key, exactly as plan 56 C ships it. Nothing new to click or send, and the response is unchanged. In the same commit the system records one register row: who (staff user or API key), when, which contact id in which workspace, how many messages and files went. When someone later asks "who erased contact X, and when?", the tenant's operator answers it from the register with a read query. No screen in this plan (viewer = BL-SS-350). The row names no person: only ids and counts.

## Rulings (crew, 5 Nov, on the behaviour card `crew/state/files/ss-fuji/f14-erase-audit-card.md`)

- 1a: one register for staff AND API-key erases (the API-key erase keeps its `integration_activity` row too).
- 2a: rows are kept, no age purge. They hold no erased personal data.
- 3a: no screen now; viewer filed as BL-SS-350.
- 4a: size L minus the mock: migration probed on a dev copy before review, security-reviewer runs.

## Today (9c2110c1)

- `ContactEraseService.erase(tenant_id, workspace_id, contact_id)` (`modules/omnichannel/services/contact_erase_service.py:92-105`) deletes in one transaction, commits once (`:99`), then builds `EraseResult(contact_id, erased_at, messages, files)` and runs the after-commit fan-out. `erase_in_tenant` (`:84-90`) is the staff entry.
- Staff route `routers/conversations.py:867-884` has `current_user` (`require_permission("contacts.erase")`). API-key route `routers/api_v1.py:437-445` has `api_ws.key_id` (`api_auth.py:35`) and calls `PublicGatewayService.erase_contact` (`services/public_gateway_service.py:348-362`).
- Neither path records who erased. `integration_activity` (core) logs the API-key request but has no user column and is not a module's to change. `conversation_events` has `actor_user_id` but its rows are deleted with the contact (`models.py:504` FK).

## Change

### S0. Model + migration (`[BE]`, `[T]`)

- `ContactErasure` model in `modules/omnichannel/models.py` (`OmniBase`, schema `app_omnichannel`), table `contact_erasures`, columns per AC-58-01. `erased_at` is `UTCDateTime`. No FK to `contacts` or `workspaces` (the row must outlive both). `CheckConstraint` per AC-58-02, named `ck_contact_erasures_actor`.
- Indexes: `ix_contact_erasures_tenant_erased (tenant_id, erased_at)`, `ix_contact_erasures_tenant_contact (tenant_id, contact_id)`.
- Migration `modules/omnichannel/alembic/versions/0026_omni_contact_erasures.py`, `down_revision = "0025_omni_migration_sync"`, inspector-guarded create like `0025`, downgrade drops the table. New table, starts empty: no backfill (no staff erase has run in prod: #188 is unmerged; erases on dev copies before this PR have no row, accepted).
- Probe: `pg_dump` of the crew copy DB into a throwaway DB, `bootstrap_db` from the branch head, check columns / check / indexes, downgrade + upgrade, drop the probe (the #188 copy recipe, lane-resume item 122).

### S1. Writes (`[BE]`)

- `EraseActor` (frozen dataclass in `contact_erase_service.py`): `kind` (`staff` | `api_key`), `user_id`, `api_key_id`; constructors `EraseActor.staff(user_id)` and `EraseActor.api_key(key_id)`.
- `erase(..., *, actor: EraseActor)` and `erase_in_tenant(..., *, actor: EraseActor)`: required keyword, no default (AC-58-16).
- Inside the existing `try` (before `self.db.commit()` at `:99`): `ContactEraseRepository.add_erasure(...)` (pure SQLAlchemy, `db.add` + `flush`) with the counts `_erase_rows` returned and the same `erased_at` the result carries, so the row and the response can never differ (AC-58-10/11). A failed insert falls into the same `except` -> rollback -> re-raise (AC-58-12).
- Staff route passes `EraseActor.staff(current_user.id)`; `PublicGatewayService.erase_contact` gains `api_key_id` and the API route passes `api_ws.key_id`.
- `bootstrap.uninstall_tenant` already deletes every `OmniBase` table's rows by `tenant_id` (`bootstrap.py:938-940`): the register is covered with no change (AC-58-17). "Kept" (ruling 2a) therefore means for the life of the tenant's omnichannel data: an uninstall or a platform tenant purge removes it with everything else (decision taken here, flagged in the plan review).

### Docs (`[T]`)

- `documentation/engineering/omnichannel-service.md` "Contact erase" paragraph: one sentence on the register (AC-58-21).
- Backlog BL-SS-350 "Erase register viewer" (read-only list per workspace for Admins: time, actor, contact id, counts), source this plan.
- No consumer guide change: no wire change (AC-58-20).

## Not in this plan

- A screen or API to read the register (BL-SS-350).
- Back-filling erases done before this PR.
- Logging attempts that did not erase (403/404/401 stay in their usual logs).

## Order and gates

1. Plan review (crew; lavish markup) before any code.
2. Tester writes red tests for S0 + S1 from this UAC (test list below), committed alone as `test(red): ...`; red proof in a clean copy.
3. Coder (one seat) S0 then S1 until green; control list = every test file that calls `ContactEraseService`, `erase_contact`, the staff erase route, `uninstall_tenant`, or the omnichannel migrations.
4. Migration probe on a dev copy (S0 above).
5. Reviewer (kill tests) + security-reviewer in parallel; fix rounds on the same coder.
6. PR (stacked on #188 until it merges, then `main` merged in), CI at job level, Merge-ready.

## Captain's test list (one line per AC)

- AC-58-01/02: model columns, nullability, no FK on `contact_id`/`workspace_id`; inserting a staff row without `actor_user_id`, an api_key row without `api_key_id`, a row with both, and `actor_kind='bot'` each fail at flush.
- AC-58-03: migration file revision/down_revision/id length; single head (the CI gate); live Postgres probe evidence in the PR body.
- AC-58-10: staff erase -> one row, fields equal response + caller id + contact's workspace.
- AC-58-11: API-key erase by id and by `phone:` -> one row each with the key id; `integration_activity` row still present.
- AC-58-12: forced failure in `_erase_rows` -> no row, contact present; forced failure in `add_erasure` -> erase rolled back (contact + messages present), error answered.
- AC-58-13: each non-erase (404 x4, 403, 401) -> zero rows.
- AC-58-14: distinctive name/phone/email/message text absent from every column of the row.
- AC-58-15: re-contact creates a new id, row unchanged; `purge_files` leaves the row unchanged.
- AC-58-16: `erase(...)` / `erase_in_tenant(...)` without `actor` raises `TypeError`.
- AC-58-17: `uninstall_tenant(t1)` removes t1's rows, leaves t2's.

## Definition of Done

No UI (no mock, no browser pass). New table only: no backfill, no permission, no editable key. Migration verified on live Postgres. Engineering doc + backlog in the same PR. Red proof, kill proof, reviewer READY, security-reviewer READY, CI green at job level.
