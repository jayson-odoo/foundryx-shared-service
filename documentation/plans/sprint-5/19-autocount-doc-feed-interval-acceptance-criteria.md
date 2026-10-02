# 19 - AutoCount Document feed schedule (poll + sweep interval) - User Acceptance Criteria

Lane `DOC-FEED-INTERVAL`. The owner sets how often each Document feed (Delivery orders, Goods
receive notes) runs, with the SAME mechanism the Entities tab uses for an ETL task's schedule
(`schedule-tab.tsx` Incremental + Reconcile cards, `etl_service.py` floors + `next_run_times`).
Plan: [19-autocount-doc-feed-interval.md](19-autocount-doc-feed-interval.md).

Behaviour card: PR #110 `crew-ask`. Owner answers (2 Oct): **Q1 poll floor = 1 minute** (Entities'
with-watermark floor - the poll reads `byLastModified`); Q2 sweep = Entities' reconcile (1 h floor,
daily HH:MM or every N hours); Q3 (a) shared component in the Configure dialog, no list column.
Q4 unanswered - the recommendation (a) "re-arm only the changed half" stands.

Tags: `[BE]` backend pytest, `[FE]` vitest, `[T]` tester / hand-test proof.

## Group A - storage, defaults, wire

- **AC-19-01 [BE]** Module Alembic `0026` adds a nullable JSON column `ac_doc_feed.schedule_config`
  (additive only, idempotent `ADD COLUMN IF NOT EXISTS`). Existing rows stay `NULL`.
- **AC-19-02 [BE]** A feed with `schedule_config IS NULL` resolves to the defaults
  `{incrementalMinutes: 60, reconcileMode: "interval", reconcileHours: 24, reconcileAt: null}` -
  byte-for-byte today's cadence (poll 60 min, sweep 24 h). The beat for such a feed re-arms
  `next_poll_at = now + 60 min` / `next_sweep_at = now + 24 h` exactly as before.
- **AC-19-03 [BE]** `GET /autocount/doc-feeds/{company}` returns per feed a `schedule` object
  (resolved, never null) plus the existing `nextPollAt` / `nextSweepAt`.

## Group B - edit + validation (same rules as Entities)

- **AC-19-04 [BE]** `PUT /autocount/doc-feeds/{company}/{feed}` accepts an optional `schedule`
  `{incrementalMinutes, reconcileMode, reconcileHours?, reconcileAt?}`; omitted = stored schedule
  kept. Gate stays `autocount.companies.manage` (a user without it gets 403).
- **AC-19-05 [BE]** Validation mirrors the Entities no-watermark rules, as a 422 house
  `detail.fieldErrors` map: `incrementalMinutes` missing/non-integer/< 1 rejected; `reconcileMode`
  outside `interval|dailyAt` rejected; `interval` needs `reconcileHours >= 1`; `dailyAt` needs
  `reconcileAt` `HH:MM` (UTC). A rejected PUT changes nothing (mode/connection included).
- **AC-19-06 [BE]** The beat honours the stored schedule: a due poll re-arms `now + N min`; a due
  sweep re-arms `now + N h` (interval) or the next `HH:MM` UTC (dailyAt).

## Group C - re-arm on change

- **AC-19-07 [BE]** Saving a CHANGED poll interval on an armed feed (mode != off) sets
  `next_poll_at = now + new minutes`; `next_sweep_at` keeps its value.
- **AC-19-08 [BE]** Saving a CHANGED sweep rule on an armed feed sets `next_sweep_at` from the new
  rule; `next_poll_at` keeps its value. Saving an unchanged schedule re-arms nothing.
- **AC-19-09 [BE]** On an `off` feed the schedule is stored, both next times stay `NULL`. Arming
  it (off -> dry_run/push) sets `next_poll_at = now` (unchanged rule) and `next_sweep_at` from
  the stored sweep rule (default: `now + 24 h`, today's value).

## Group D - UI (reused Entities component)

- **AC-19-10 [FE]** The Incremental + Reconcile cards are ONE shared component; the Entities
  Schedule tab renders it unchanged (existing `schedule-tab.test.tsx` stays green).
- **AC-19-11 [FE]** The Doc feeds Configure dialog renders that component (titles "Poll" and
  "Deletion sweep"), prefilled from `schedule`, with the same live validation (floor 1 min,
  1 h, HH:MM); Save is disabled while invalid and sends `schedule` in the PUT body.
- **AC-19-12 [T]** Hand test: change the DO feed to poll every 15 min and sweep daily at 02:00
  UTC; reopen shows the saved values; `nextPollAt` moves to ~now+15 min; at 375 px and 1280 px
  the dialog has no horizontal scroll.
