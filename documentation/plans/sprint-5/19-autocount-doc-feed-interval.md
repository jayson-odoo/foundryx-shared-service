# 19 - AutoCount Document feed schedule - plan

UAC: [19-autocount-doc-feed-interval-acceptance-criteria.md](19-autocount-doc-feed-interval-acceptance-criteria.md).

## Mirror, not invent

| Entities (ETL task) | Doc feed |
|---|---|
| `ac_entity_config.source_config` JSON keys `incrementalMinutes/reconcileMode/reconcileHours/reconcileAt` | `ac_doc_feed.schedule_config` JSON, same keys |
| `EtlService.next_run_times` (`etl_service.py`) | the SAME function, called with the feed's resolved schedule |
| floors `MIN_INCREMENTAL_MINUTES_NO_WATERMARK=5`, `MIN_RECONCILE_HOURS=1`, `_TIME_RE` | the same constants; the poll uses the with-watermark floor (1 min, owner Q1 - it reads `byLastModified`) |
| `PUT .../etl-task`, `autocount.companies.manage` | `PUT /doc-feeds/{company}/{feed}` + `schedule`, same perm |
| `schedule-tab.tsx` Incremental + Reconcile cards | extracted to `components/schedule-cadence-cards.tsx`, used by both |

## Backend
- `doc_feed/schedule.py`: `DEFAULT_DOC_FEED_SCHEDULE`, `resolve_schedule(raw)`,
  `validate_schedule(raw) -> fieldErrors`, `next_poll_at(schedule, now)`, `next_sweep_at(schedule, now)`
  (the last two delegate to `EtlService.next_run_times`).
- `scheduler.py` re-arms from the feed's resolved schedule instead of `POLL_INTERVAL`/`SWEEP_INTERVAL`.
- `DocFeedService.update(..., schedule=None)`: validate (422 before any write), store, re-arm the
  changed half only when armed; arm-from-off computes the sweep from the schedule.
- Migration `0026_autocount_doc_feed_schedule` - `ADD COLUMN IF NOT EXISTS schedule_config JSON`.

## Frontend
- `ScheduleCadenceCards` props: `config`, `onChange`, `editing`, `incrementalFloor`, titles,
  next-run badges. Schedule tab consumes it (no visual change).
- Doc feed dialog: `schedule` state, cards below Mode, Save disabled on any validation error,
  `onSave({connectionId, mode, schedule})`. Types: `DocFeedSchedule`, `DocFeedItem.schedule`.

## Out of scope
- A list column showing the cadence (new UI element - needs a Lavish mock first).
- Per-tenant timezone for "Daily at" (BL-SS-034, same as Entities).
