# SS-BACKFILL-CHUNKED - doc-feed backfill survives the 2 h job limit

Status: in progress (lane SS-BACKFILL-CHUNKED).

Problem: the whole doc-feed backfill runs as ONE `jobs.run` Celery job with a
7200 s soft limit; a multi-year backfill (~1.8 s/day) can never finish, and a
limit hit outside the per-day `try` leaves the row `running` with no worker
(Stop sets `stopping` forever, Resume needs `stopped`).

Plan (AC ids for the test report):
- AC-BFC-1 chained segments: each job runs at most a time budget well under the
  limit, saves `next_day`, and enqueues the next segment; one logical backfill.
- AC-BFC-2 time limit / crash anywhere in the loop ends the row `stopped`
  (resumable) with the error recorded - never stuck `running`/`stopping`.
- AC-BFC-3 stale-row reaper: a `running`/`stopping` backfill whose job ended
  (failed/done) or has no heartbeat > 15 min is moved to `stopped`.
- AC-BFC-4 dry-run-first: finished dry runs that together cover the live range
  satisfy the gate.
