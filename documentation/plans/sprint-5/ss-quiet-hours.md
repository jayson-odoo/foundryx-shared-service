# SS-QUIET-HOURS - per-entity off hours (behaviour card)

Owner, 9 Nov ~16:50 MYT: "for each task we need to be able to configure the off time so it doesn't
query the autocount when there is no data change like at night, should be configurable per entity".

## Behaviour

- **Where:** each task's Schedule tab gets an **Off hours** card (same card component as the
  incremental / reconcile cards). Toggle on/off + `From HH:MM` + `To HH:MM`, read in MYT
  (`Asia/Kuala_Lumpur`). No new screen.
- **Stored:** on the task row, `ac_entity_config.source_config` (no new table, no migration):
  `quietHoursEnabled` (bool), `quietHoursStart` / `quietHoursEnd` (`HH:MM`),
  `quietHoursTimezone` (default `Asia/Kuala_Lumpur`). A task without the keys = no off hours
  (unchanged behaviour on deploy).
- **Window:** `start <= local time < end`; `start > end` crosses midnight (22:00-07:00).
  `start == end` is a save error. Every day.
- **Incremental only:** a scheduled incremental tick inside the window does NOT enqueue a job, so
  there is no AutoCount query at all (SQL tunnel or HTTP). The tick re-arms `next_incremental_at`
  to the window end; no skip row is written (a 15 s task would otherwise write ~2,000 rows/night).
  A continued paged incremental pass (initial load) also waits.
- **Catch-up:** the first tick at/after the window end runs a normal incremental from the stored
  watermark, so every change made during the night is picked up in that one run.
- **Reconcile unchanged:** keeps its own "Daily at" / every-N-hours time even inside the window
  (the MYT 02:00-05:00 reconciles are inside the night window on purpose). Delete-guard unchanged.
- **Manual "Run now"** always runs (an operator asked for it).
- **Next-run times** on the page come from the same `EtlService.next_run_times`, which moves an
  incremental time that lands inside the window to the window end.

## As built

- `modules/autocount/services/etl_service.py`: `in_quiet_hours`, `quiet_hours_end`,
  `defer_past_quiet_hours`, `_validate_quiet_hours` (called by the shared `validate_schedule`;
  carried by both the SQL and HTTP task cleaners); `next_run_times` defers the incremental;
  new-task defaults pre-fill 22:00-07:00 MYT, off.
- `modules/autocount/scheduler.py` `_sweep_one`: an incremental-mode tick inside the window
  re-arms `next_incremental_at` to the window end and returns `quiet` (no job, no skip row).
  That also catches `next_incremental_at = now` set by activate, resume or a truncated pass.
- Frontend: `OffHoursCard` in `components/schedule-cadence-cards.tsx` (same card shell as the
  cadence cards) on the Schedule tab; `quietHoursErrors` in `lib/autocount-etl.ts` mirrors the server rules.
- Document feeds don't send the keys, so they get no window (unchanged).

## Examples

| Task | Cadence | Off hours | Result |
|---|---|---|---|
| Sorento sales_order (SQL) | 15 s | 22:00-07:00 MYT | last tick ~21:59:45, nothing 22:00-06:59, first tick 07:00 catches up the night |
| Mocha masters (HTTP) | 15 min | 22:00-07:00 MYT | last run before 22:00, next 07:00 |
| Sorento sales_order reconcile | daily 02:00 MYT | (any) | still runs at 02:00 |

## Open questions (crew-ask on the PR)

1. Default: none vs suggested 22:00-07:00 pre-filled but off. Rec: pre-filled, off.
2. Days: every day only. Rec: every day (weekends/holidays later if asked).
3. Manual Run now inside the window: Rec: always runs.
4. Company-level default: Rec: per entity only + an "Apply to all tasks of this company" button.
5. Timezone: Rec: MYT fixed default, stored per task.
