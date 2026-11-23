# SS-BACKFILL-CHUNKED - doc-feed backfill survives the 2 h job limit

Lane SS-BACKFILL-CHUNKED. Backend only (no screen changes).

## Problem

Prod 23 Nov: a project-registrations dry run over 7632 days ran as ONE `jobs.run` Celery job
(`app/jobs/worker.py`, soft limit `background_job_soft_time_limit_seconds` = 7200 s). At about
1.8 s per day it needs about 3.8 h, so it can never finish. When the limit fired outside the per-day
`try` (vendor call, day pause), `doc_feed/jobs.py` failed the job but left the backfill row
`running` with no worker. Stop then only set `stopping` forever, and Resume needs `stopped`.

## Design

- **Chained segments (AC-BFC-1).** `run_backfill` reads days for at most
  `autocount_doc_feed_backfill_segment_seconds` (1800), measured on `runner._segment_clock`. It
  saves `next_day` and writes the segment's run row, and the row stays `running`.
  `run_doc_feed_backfill_job` then creates the next job, points `backfill.job_id` at it in one
  commit, finishes itself, and enqueues the next job. A job that is no longer `backfill.job_id`
  reads nothing.
- **Any job end leaves the row resumable (AC-BFC-2).** A `SoftTimeLimitExceeded` or a crash anywhere
  in the loop ends the row `stopped` with `TIME_LIMIT` / `CRASHED`. The sink's generic `except`
  re-raises the time limit instead of recording it as a sink error.
- **Reaper (AC-BFC-3).** `doc_feed/scheduler.reap_stale_backfills` runs on every doc-feed beat
  tick (`autocount.doc_feed_sweep`, every 60 s) and before Stop, Resume and Discard. It handles a
  `running` or `stopping` row as follows:
  - its job is missing or ended: the row goes to `stopped` (`JOB_ENDED`) through a guarded UPDATE
    on the job id it saw;
  - its job is running but has had no heartbeat for 15 minutes: core's orphan sweep fails the job,
    and the `on_job_orphaned` hook stops the row;
  - its job is still queued: the row is left alone.

  Stop on a row whose next segment is still queued aborts that job and stops the row at once.
  Resume aborts a stopped row's queued old segment that never started.
- **Dry run first (AC-BFC-4).** Finished dry runs that are not discarded and together cover every
  day of the live range pass the gate (`DocFeedService._dry_runs_cover`).
- Start and Resume create the job first, then set `running` and `job_id` in one commit. The
  `on_job_orphaned` hook only stops a backfill that points at the job being closed.

## Test report (`service_backend/tests/test_s14_doc_feed_backfill_chunked.py`, fake clock)

| AC | Tests | Result |
|---|---|---|
| AC-BFC-1 | budget ends segment running; whole range across 4 chained jobs, each day once, in order; Stop between segments; stale-job fence | PASS |
| AC-BFC-2 | time limit in vendor call (stopped, resume reads the rest), in sink write, in day pause; crash; stopping + limit | PASS |
| AC-BFC-3 | reaper matrix (failed / quiet / fresh / queued / no job); beat runs it; Stop on dead-job row; Discard and Resume reap first; kill-proof (hard kill, reaped after 15 min, resume reads only unread days); stale-snapshot race; guarded stop; Start's queued job not reaped; old segment orphaned late; Stop with queued segment; Resume with stale queued segment | PASS |
| AC-BFC-4 | two pieces cover; overlapping pieces cover; one-day gap, missing last day, and a discarded piece are all refused | PASS |

Red proof: 15 of 18 first tests failed on the old code (commit `red tests` on this branch).
Not deployed: crew schedules the deploy (not while the owner's backfill runs).
