# Cluster D (sprint-4/05) · Slice 3 - Test Execution Report

**Feature:** Registration · Ticketing · Check-in - slice 3 (ticket status engine, checkpoints + scan, nomination/QR rotation, **participant `Checked-in` derived consumer**).
**Branch:** `sprint-4/05-cluster-d-slice3` (impl `0f9f5e7`).
**Tester:** QA agent. **Date:** 2026-06-21.
**Plan:** `documentation/plans/sprint-4/05-cluster-d-registration-ticketing-venue.md` (slice 3, R3-2) · **Derived-status ACs:** `documentation/plans/sprint-4/03-status-engine-derived-status-acceptance-criteria.md`.

## Summary

| Layer | Result |
|---|---|
| Backend - full suite (`python -m pytest -q`) | **917 passed** (904 prior + 13 new functional), 0 failed, exit 0 (confirmed twice). |
| Backend - affected suites (`test_cluster_d* test_status_engine test_rule_engine test_ems_spine test_finance`) | **143 passed** + the 13 new (156). Status/rule suites stay GREEN (AC-03-25). |
| Backend - new functional coverage (`test_cluster_d_slice3.py`) | **13 passed**. |
| Backend - migration bug-guard (`test_cluster_d_slice3_migration.py`) | **2 xfailed** (documents a found BUG - see below). |
| Frontend E2E (`e2e/cluster-d.spec.ts`) | New test ⑥ (nomination via real clicks) **added + parses + lists**. Non-ticket flows (Venues, mobile) **pass** on the live stack. **All ticket-touching flows (⑤ checkout, ⑥ nomination) are BLOCKED on the live stack by BUG-1** (the slice-3 migration never applied to Postgres). |

## Bugs found

### BUG-1 (P1, deploy-blocking) - slice-3 EMS migration is un-runnable on Postgres (revision id > Alembic's `VARCHAR(32)`)

- **Symptom on the live stack:** every ticket-touching endpoint 500s with
  `psycopg2.errors.UndefinedColumn: column tickets.qr_nonce does not exist`
  (public GA hold, public checkout/confirm, and therefore nomination - which needs a confirmed ticket).
- **Root cause:** the slice-3 migration revision id `0005_cluster_d_ticket_status_checkpoints` is **40 characters**, but Alembic's version table (`app_ems.alembic_version_ems.version_num`) is `VARCHAR(32)` (Alembic `MAX_REVISION_LENGTH`). Applying it raises:
  ```
  psycopg2.errors.StringDataRightTruncation:
      value too long for type character varying(32)
      [SQL: UPDATE app_ems.alembic_version_ems SET version_num='0005_cluster_d_ticket_status_checkpoints' ...]
  ```
  So `run_module_migrations(engine, 'ems')` fails at the version-stamp step → the `add_column` ops for `tickets.qr_nonce` / `tickets.status_id` never apply on a real deployment (the checkpoints tables were created incidentally via a `create_all` pass; the live `alembic_version_ems` is stuck at `0004`).
- **Why the suite is green anyway:** conftest builds the schema via `EmsBase.metadata.create_all` (no Alembic), so SQLite tests have the columns and never exercise the migration path. The broken migration is invisible to every existing test.
- **Repro (clean):**
  ```bash
  cd service_backend && source .venv/bin/activate
  python -c "from sqlalchemy import create_engine; from app.config import settings; \
  from app.module_platform.migrations import run_module_migrations; \
  run_module_migrations(create_engine(settings.database_url),'ems')"
  # → DataError: StringDataRightTruncation (value too long for varchar(32))
  ```
- **Coverage added (flagging, NOT fixing - per the QA contract):** `tests/test_cluster_d_slice3_migration.py` - two `xfail(strict=True)` guards. They scan every module migration id against the 32-char limit and pinpoint the slice-3 offender. They flip to **xpass → test failure** the moment the coder shortens the id, which is the signal that the fix landed.
- **Suggested fix (coder):** rename the revision to e.g. `0005_ticket_status_checkpoints` (30 chars), keep `down_revision='0004_cluster_d_cart_tickets'`, then `run_module_migrations` / `bootstrap_db` on the live Postgres. (Same class as the cross-branch-alembic + revision-id lessons in CLAUDE.md; the comparison `0003_cluster_d_venues_offerings` is 31 chars - already at the edge.)
- **Not fixed by tester** - no implementation change made; hand-patching the shared dev Postgres was correctly refused.

## Test Execution Detail

| # | User Story | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|---|---|
| 1 | As the platform, ticket lifecycle rides the status engine | Ticket status entity registered + seeded | EMS installed | GET `/status-entities`; GET `/statuses?entityType=ticket` | `ticket` present; `issued` initial; `void`/`refunded` terminal; edges Validate/Check in/Transfer/Void/Refund | PASS | Coder `test_ticket_status_entity_seeded`. |
| 2 | As a buyer, a confirmed ticket carries engine state | Confirm sets `status_id` + QR nonce | GA offering | CheckoutService.confirm → inspect ticket | `status=issued`, `status_id` set, `qr_token`+`qr_nonce` present | PASS | Coder `test_confirm_sets_ticket_status_id`. |
| 3 | As an admin, I nominate/transfer a ticket | Transfer rotates QR; nominee can't re-transfer | Confirmed ticket | POST `/tickets/{id}/nominate` ×2 | first: `transferred`+`qrRotated`; second: 409 | PASS | Coder `test_nominate_rotates_qr_and_blocks_re_transfer`. |
| 4 | As a gate, I scan a QR | Admit then double-scan dedup | Confirmed ticket + checkpoint | scan ×2 | first `admitted` (ticket→checked_in, 1 log); second `already_in` (no 2nd admit log) | PASS | Coder `test_scan_admits_then_double_scan_is_already_in` (SINGLE dedup). |
| 5 | As a gate, a tampered QR fails safe | Garbage token | Checkpoint | scan garbage | HTTP 200, `result=denied` (not 500) | PASS | Coder `test_scan_tampered_token_is_clean_rejection`. |
| 6 | As the system, a rotated QR dies | Old token after transfer | Transferred ticket | scan old QR; scan new QR | both `denied` (nonce mismatch / terminal) | PASS | Coder `test_scan_rotated_qr_dies`. |
| 7 | **R3-2 centerpiece** - participant auto-checks-in | Derived consumer via service | Eligible participant w/ ticket | `_move_to_key(checked_in)` → bus | participant `status_id` = checked_in (no manual transition) | PASS | Coder `test_derived_participant_checked_in`. |
| 8 | AC-03-18 - fork/copy carries trigger_mode | Auto edge on copied scope | New project | inspect Eligible→Checked-in edge | `trigger_mode='auto'`, `conditions_json` present | PASS | Coder `test_participant_checkin_edge_is_auto_on_copied_scope`. |
| 9 | **R3-2 / AC-03-23 (EMS)** - auto check-in end-to-end through the API | Real HTTP scan → bus re-derives participant | Eligible participant w/ ticket + checkpoint | POST `/checkpoints/{id}/scan` | `admitted`; participant auto-advances Eligible→Checked-in via the bus (no manual transition) | PASS | **NEW** `test_scan_endpoint_auto_advances_participant_checked_in` - proves the full stack (the coder's test used the service shortcut). |
| 10 | **R3-2** - the `==` denominator guard | Partial (1/2) does NOT advance; full (2/2) does | 1 participant, 2 admission tickets, Eligible | check in ticket 1 → assert; check in ticket 2 → assert | after 1/2: still Eligible; after 2/2: Checked-in | PASS | **NEW** `test_partial_checkin_does_not_advance_then_full_does` - the core derived condition. |
| 11 | AC-03-13/33 (EMS) - aggregate facts owner-scoped | Sibling's tickets never contribute | 2 participants, 1 each | resolve `admission/checkedInTicketCount` per participant | A: 1 admission, 0 checked-in; B: 1/1 - no cross-bleed | PASS | **NEW** `test_checkin_aggregate_facts_are_owner_scoped`. |
| 12 | Live denominator | Void excluded from admission count | 1 participant, 1 void + 1 checked-in ticket | resolve facts | admission=1 (void dropped), checkedIn=1 → guard satisfiable | PASS | **NEW** `test_voided_ticket_excluded_from_admission_count`. |
| 13 | **AC-03-14** - re-eval is failure-isolated | Broken derivation never 500s the scan write | Confirmed ticket; a raising bus subscriber registered | scan | HTTP 200 `admitted`; ticket→checked_in + log committed; raising subscriber was actually invoked | PASS | **NEW** `test_broken_derivation_never_500s_the_scan` - injects via the real `register_event_subscriber` path. |
| 14 | AC-03-04 (EMS) - auto edges hidden from user surfaces | Auto Check-in absent from participant transitions | Eligible participant | `available_transitions` | the auto edge exists in the graph (`trigger_mode=auto`) but is **excluded** from the fireable list | PASS | **NEW** `test_auto_checkin_edge_absent_from_participant_transitions`. |
| 15 | As a gate, segment gating is enforced + audited | Segment mismatch denies + logs | Ticket whose participant lacks the gated segment | scan | `denied`; ticket stays `issued`; a denied checkpoint_log written | PASS | **NEW** `test_segment_mismatch_denies_and_logs`. |
| 16 | Tampered QR leaves no audit noise | Garbage token writes no log | Checkpoint | scan garbage | `denied`; **zero** checkpoint_log rows | PASS | **NEW** `test_tampered_qr_writes_no_log` (no-log invariant). |
| 17 | Security boundary | Scan endpoint gated `checkpoints.manage` | Checkpoint | scan with NO auth | 401 | PASS | **NEW** `test_scan_requires_checkpoints_manage`. |
| 18 | Security boundary | Nominate endpoint gated `tickets.manage` | Ticket | nominate with NO auth | 401 | PASS | **NEW** `test_nominate_requires_tickets_manage`. |
| 19 | Transfer leaves money alone | Invoice untouched on transfer | Paid ticket w/ invoice | nominate → re-resolve invoice | `ticket.invoice_id` unchanged; invoice total unchanged | PASS | **NEW** `test_nominate_leaves_invoice_untouched` (R3 money-untouched rule). |
| 20 | Foolproof-UI + real boundary | Blocked nominee refused | Suspended nominee profile | nominate to it | 422 | PASS | **NEW** `test_nominate_blocked_for_suspended_nominee`. |
| 21 | Defensive validation | Unknown nominee | - | nominate to ghost id | 422 | PASS | **NEW** `test_nominate_unknown_profile_422`. |
| E2E-1 | As an admin, I nominate via the UI | participant "…" → Nominate / transfer → pick nominee → Transfer | live stack + confirmed registrant + nominee (API-seeded) | login → event → Participants → row "…" → Nominate → pick nominee → Transfer; assert toast + (API) ticket `transferred` on the nominee | toast "Ticket transferred - QR rotated"; nominee holds a `transferred` ticket | **BLOCKED** | New `e2e/cluster-d.spec.ts` ⑥ - **written, parses, lists**. Cannot run green: BUG-1 500s the registrant setup (`public .../cart/.../ga` → `column tickets.qr_nonce does not exist`). Re-run prerequisite below. The pre-existing ⑤ checkout E2E is blocked identically - confirming the blocker is the migration, not the new spec. |
| E2E-2 | Non-ticket flows still work | Venues create/zone/seats + mobile no-overflow | live stack | real clicks | pass | **PASS** on the live stack | Proves auth + FE build + Resource shell are healthy; only ticket flows are blocked. |

## E2E re-run prerequisite (once BUG-1 is fixed)

```bash
# backend up + seeded (slice-3 migration applied):
cd service_backend && source .venv/bin/activate
python -m scripts.bootstrap_db        # after the coder shortens the 0005 revision id
uvicorn app.main:app --reload --port 8001
# frontend served from a clean build of this branch:
cd ../service_frontend && rm -rf .next && npm run build && npm start   # :3001
# clear the shared throttle, then:
npx playwright test cluster-d.spec.ts -g "Nomination/transfer"
```
The new spec timestamps all created names (`Nominee <ts>`, `registrant-<ts>@…`) and seeds the registrant via the public/operator API; the **transfer itself is real clicks**. Setup runs on a dedicated second event (`nomEventId`) within the default tenant to avoid disturbing slices ①-⑤.

## Notes / non-blocking observations

- The coder's `_move_to_key`-based centerpiece test is correct but bypasses the HTTP layer; new test #9 closes that by driving the real scan endpoint.
- `available_transitions` correctly hides the auto edge for scoped (participant) graphs too - the scoped `is_active` repurpose does not leak auto edges (test #14).
- The aggregate facts filter the legacy `Ticket.status` string mirror (kept in sync by `TicketService`); tests #11/#12 confirm the mirror + the live/void semantics behave.
- Full backend suite confirmed green twice (917 passed) - slice-3 additions do not regress status/rule/template/workflow/finance suites (AC-03-25).
