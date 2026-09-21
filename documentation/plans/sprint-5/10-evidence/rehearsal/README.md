# Sprint-5/10 rehearsal evidence - AC-10-56 joint runs on the Sorento clone

Run log for the joint rehearsal between the Foundryx `autocount` pull gateway
and a Sorento clone doing the consumer side (build, review, apply). No
product code changed in this slice; this document plus the DB/log evidence
quoted below IS the deliverable.

## Setup

- **Foundryx lane:** worktree `.claude/worktrees/s40` at `origin/main`
  `bf54663d`. Backend `uvicorn` on `:8009`, DB `foundryx_service_s40`
  (Postgres, `app_autocount` schema).
- **Sorento peer:** clone `sorento_acpull_e2e` on Sorento `main` `b831b6ef0`
  with `SR6` applied, running frontend `:3083` / backend `:8083`.
- **Pull API key:** name `rehearsal-20260921T0011Z`, prefix `nEIGCVSi`,
  scoped to companies `SRT` and `MCH`, base URL `http://localhost:8009`. The
  key plaintext is never recorded in this document or anywhere in the repo.
- All timestamps below are UTC. The Postgres session's own zone is
  `Asia/Seoul` (+09); every value quoted from the DB was pulled through
  `AT TIME ZONE 'UTC'` to normalize it.

## The four runs

### Run 1 - SRT products

**Peer report (verbatim, UTC):** snapshot `7db045d9`, recordCount `11,842`.
Pull click `02:08:26`, ready+preview `02:11:31`, dry-run done `02:15:13`,
Confirm `02:17:33`, applied `02:22:13`. Preview: new 9 / changed 59 /
unchanged 11,762 / failed 12 (10 blank-name `name required`; 2 unique
conflict on product_code `6356` and `6509` = Sorento-side ref collision
with old line-ingest DocKey refs; also `507` and `1861` collide but failed
on blank name first). Apply: created 9, 12 failed.

**Our DB evidence** (`app_autocount.ac_pull_snapshot`, id `7db045d9-1efd-42d7-83ea-ddeef6dcf697`):

| field | value |
|---|---|
| status | ready |
| record_count | 11,842 |
| complete | true |
| created_at (row insert) | 2026-09-21 02:06:13.665571 UTC |
| extracted_at (build done) | 2026-09-21 02:11:26.732013 UTC |
| expires_at | 2026-09-22 02:11:26.732013 UTC (24h TTL) |
| build duration (created -> extracted) | 5m 13s |
| metadata_json | `excludedRows: []`, `excludedCount: 0`, `sourcePageSize: 1000`, `zeroListPriceCount: 5129`, `negativeListPriceCount: 121`, `enrichMissCount: 0` |

`ac_pull_audit` rows for this key/snapshot:

| action | status_code | n | first | last |
|---|---|---|---|---|
| build | 202 | 2 | 02:08:26.580 | 02:11:26.750 |
| get_header | 200 | 20 | 02:08:38.363 | 02:17:34.873 |
| get_rows | 200 | 24 | 02:11:31.681 | 02:17:35.482 |

Uvicorn log: `POST /api/v1/autocount/snapshots -> 202 Accepted` appears
**once** in the access log for this run's window, but the audit table shows
**two** `build` writes (202/202, 3m00s apart). Read together with the row's
own `created_at`/`extracted_at`, the second `build` audit write lands 18ms
after `extracted_at` - i.e. it is the request that actually observed
completion. The first `build` audit write (02:08:26) lands 2m13s after the
row was created, mid-build, and returns fast (no second extraction ran -
only one `ready` snapshot id exists for this triple). See Finding F1.

### Run 2 - SRT stock

**Peer report (verbatim, UTC):** snapshot `d30ef25e`, received `12,117`.
Pull click `02:27:33` (first POST 502 on Sorento side, retry ok), ready
`02:30:46`, review `02:31:01`. Fed 6,487 (active warehouses), not applied
inactive 5,475, unknown location 155, qty changes 6,466, set-to-0 0,
product-not-found 0, negative pairs 42. Apply 12s (created 17, updated
6,470, zeroed 0). Stock List `autocount-stock-list-srt-20260921.xlsx`.

**Our DB evidence** (id `d30ef25e-4c8d-4e69-bf9e-a13145d53bbf`):

| field | value |
|---|---|
| status | ready |
| record_count | 12,117 |
| complete | true |
| created_at | 2026-09-21 02:25:19.488985 UTC |
| extracted_at | 2026-09-21 02:30:39.602806 UTC |
| expires_at | 2026-09-22 02:30:39.602806 UTC |
| build duration | 5m 20s |
| metadata_json | `excludedCount: 0`, `sourcePageSize: 1000`, `zeroPairs: 56442`, `negativePairs: 42` (`negativePairList` has 42 entries - summarized to a count; sample items include `**NEW`/BRW `-75`, `AC-EXP-006`/HQ `-2437`, `TRANSPORT`/BRW `-2612`), `fractionalPairs: 0`, `excludedNonzeroCount: 0` |

`ac_pull_audit` rows:

| action | status_code | n | first | last |
|---|---|---|---|---|
| build | 202 | 2 | 02:27:35.441 | 02:30:39.628 |
| get_header | 200 | 20 | 02:27:49.491 | 02:32:46.103 |
| get_rows | 200 | 26 | 02:30:43.848 | 02:32:46.508 |

This is the run the peer explicitly called out the 502 on. Our audit
confirms the same 2-call pattern as Run 1: `build` #1 at 02:27:35 (2m16s
after `created_at`), `build` #2 at 02:30:39.628, 25ms after `extracted_at`.

### Run 3 - MCH products

**Peer report (verbatim, UTC):** snapshot `98156bfa`, received `3,445`.
Click `02:41:07`, review ~`02:49`. New 3 / changed 789 / unchanged 2,653 /
failed 0 / price_to_zero 1. Apply 1m 45s (created 3, updated 3,442).
`ref_mismatch 0` on both product runs.

**Our DB evidence** (id `98156bfa-bf9d-4693-9d9f-344217993bb8`):

| field | value |
|---|---|
| status | ready |
| record_count | 3,445 |
| complete | true |
| created_at | 2026-09-21 02:39:15.760813 UTC |
| extracted_at | 2026-09-21 02:47:11.235035 UTC |
| expires_at | 2026-09-22 02:47:11.235035 UTC |
| build duration | 7m 55s |
| metadata_json | `excludedCount: 0`, `sourcePageSize: 300`, `zeroListPriceCount: 333`, `negativeListPriceCount: 0`, `enrichMissCount: 0` |

`ac_pull_audit` rows:

| action | status_code | n | first | last |
|---|---|---|---|---|
| build | 202 | 2 | 02:41:08.794 | 02:47:11.971 |
| get_header | 200 | 38 | 02:41:19.982 | 02:53:10.997 |
| get_rows | 200 | 8 | 02:47:21.948 | 02:53:12.143 |

Same pattern: `build` #1 at 02:41:08 (1m53s after `created_at`), `build`
#2 at 02:47:11.971, 736ms after `extracted_at`.

### Run 4 - MCH stock

**Peer report (verbatim, UTC):** snapshot `8747bb87`, received `3,166`.
Click `02:58:55`, review ~`03:20` (build ~22 min). Fed 3,061, inactive 105,
unknown 0, qty changes 102, set-to-0 5, negative 9. Apply 12s (created
1,159, updated 1,902, zeroed 5). `autocount-stock-list-mch-20260921.xlsx`.

**Our DB evidence** (id `8747bb87-5590-4db9-bc34-473ecb54a1a0`):

| field | value |
|---|---|
| status | ready |
| record_count | 3,166 |
| complete | true |
| created_at | 2026-09-21 02:57:37.182158 UTC |
| extracted_at | 2026-09-21 03:05:50.856776 UTC |
| expires_at | 2026-09-22 03:05:50.856776 UTC |
| build duration | 8m 14s |
| metadata_json | `excludedCount: 0`, `sourcePageSize: 300`, `zeroPairs: 7380`, `negativePairs: 9` (full list, under the 20-entry cutoff): `AC-EXP-006`/HQ-ACC `-3`, `AC-EXP-027`/HQ-ACC `-32`, `CARTON BOX`/HOLD `-470`, `CARTON BOX`/MWH-RSV `-234`, `COURIER`/MOCHA-WH `-73`, `MISC`/MKTG-HQ `-2`, `RPACC`/REPAIR `-7`, `TRANSPORT`/HQ `-10`, `TRANSPORT`/MOCHA-WH `-69`; `fractionalPairs: 0`, `excludedNonzeroCount: 0` |

`ac_pull_audit` rows:

| action | status_code | n | first | last |
|---|---|---|---|---|
| build | 202 | 2 | 02:58:56.682 | 03:05:50.901 |
| get_header | 200 | 6 | 02:59:07.547 | 03:24:43.648 |
| get_rows | 200 | 8 | 03:22:50.958 | 03:24:43.792 |

Our build finished at 03:05:50 (8m14s from click), well before the peer's
"review ~03:20" - the extra ~15 minutes on the peer side is their own
diff/review computation over the fetched rows, not additional time spent
building the snapshot on our side. `build` #1 at 02:58:56 (1m19s after
`created_at`), `build` #2 at 03:05:50.901, 44ms after `extracted_at`.

## Uvicorn log

`/private/tmp/.../scratchpad/rehearsal-8009.log` (91MB over the whole
session) is INFO-only access logging for this run - `grep -c "WARNING\|ERROR"`
returns 0, and there are no application-level retry-ladder lines (the
default uvicorn access-log format carries method/path/status only, no
per-request duration; the durations above come from the DB timestamps).
Status-code distribution for `/api/v1/autocount/snapshots*` across the
whole log: `200` x150, `202` x4 (one `POST` per run), `401` x2 (the
post-revoke verification call from this task, plus one earlier probe),
`404` x6 (setup-time probes against placeholder ids, all before Run 1's
`02:06` window). No unexpected status code appears inside any of the four
runs' windows.

## Findings

**F1 - the lane's synchronous build masks the real prod behaviour, and the
retry pattern is visible in our own audit log, not just the peer's
report. Scope: lane only.** `service_backend/app/jobs/service.py`'s
`enqueue()` runs the job **inline, on the request's own session**,
whenever `CELERY_TASK_ALWAYS_EAGER=true` - so on THIS lane, `POST
/snapshots` does not return `202` until the ENTIRE extraction has
finished (5-8 minutes across these four runs), not
immediately-with-a-background-job the way prod already answers (prod
dispatches to a real Celery worker and returns `202` right away - this is
not a prod defect, it is an artifact of how this particular rehearsal
lane was configured). Every one of the four runs shows the same 2-call
`build`/202 signature in `ac_pull_audit`: an early call, 1m19s-2m16s
after the snapshot row's `created_at`, that returns fast because it lands
mid-build and re-attaches to the in-flight snapshot
(`PullService.request_build`'s re-attach branch - confirmed by there
being exactly one snapshot id per triple, never two); then a second call
whose audit write lands within tens of milliseconds of the row's own
`extracted_at` - the request that actually rode out the full synchronous
build to completion. The peer explicitly reported a 502 + retry for Run 2
only, and reported no user-visible toast on it (their defect to fix); the
same signature is present in our audit for all four runs, so the same
silent-502-then-retry likely happened on every run, not only the one the
peer happened to notice. Plan 11 R8 makes the E2E lane run a real Celery
worker instead of eager inline execution, which removes this artifact
from future E2E lanes - it is a lane-fidelity fix, not a prod gate.

**F2 - two product_code conflicts, and a related hazard for a future
run.** Run 1's apply had 2 unique-constraint failures (product_code `6356`
and `6509`) because Sorento already has rows keyed by an OLD line-ingest
`DocKey` ref that happens to collide with these numeric `ItemCode`s (plus
`507` and `1861`, which also collide but failed on the blank-name check
first, masking the ref collision for those two). The underlying hazard: if
a **new** AutoCount `ItemCode` is ever assigned a value that matches an old
`DocKey` ref still sitting in a Sorento row, Sorento's own ingest logic (by
code-vs-ref precedence) could rename an unrelated product out from under
itself. Sorento has proposed a fix (code wins over a ref hit, and refuse a
code change driven purely by a ref match; also relax the blank-name
rejection). No Foundryx-side change is implicated - this is entirely a
Sorento-side ingest/matching decision.

**F3 - MCH stock's ~22 minute review time is peer-side, not a build-size
regression.** Our own build for that run (Run 4) completed in 8m14s
(`created_at` 02:57:37 -> `extracted_at` 03:05:50); the peer's "review
~03:20" reflects their own diff computation over the fetched rows on top
of that, not additional snapshot-build time. AC-10-85/86's sizing
assumptions hold. The practical requirement stands: any consumer polling
loop must not time out a `building` snapshot under 30 minutes, since a
combined build+review cycle in the 20-30 minute range is a real, observed
shape for this data volume.

**F4 - SRT product count growth is vendor data drift, not a defect.**
11,842 today vs the 2026-09-19 baseline of 11,840 - a 2-record increase
consistent with normal AutoCount data growth between rehearsal runs, not
a Foundryx-side counting change.

## AC-10-56 verdict

**PASS** for the joint runs against the Sorento clone: all four
build/preview/apply cycles completed, record counts matched between our
snapshot headers and the peer's reported `recordCount`/`received` figures
exactly (11,842 / 12,117 / 3,445 / 3,166), and the two product-side unique
conflicts plus one stock negative-pairs shape are explained (F2) rather
than being unexplained data loss. Prod cut-over is gated on:

1. **The owner's go on the Sorento ingest fixes** (F2) - code wins over a
   ref hit and Sorento refuses a `product_code` change driven purely by a
   ref match, a blank `name` is allowed rather than rejected, an
   unchanged row is a no-op, and a failed/timed-out build POST surfaces a
   toast instead of failing silently.
2. **The Foundryx prod pre-flight** - category/UOM/product/stock_balance
   pull tasks active per book, a real (non-rehearsal) prod pull key
   issued, and Sorento prod's base URL set to
   `https://chat.foundryx.my/be`.

F1 is NOT part of that gate - it is a lane-fidelity artifact of this
rehearsal's `CELERY_TASK_ALWAYS_EAGER=true` setting, not a prod behaviour
gap; prod already dispatches to a real worker and answers `202`
immediately. Plan 11 R8 (real Celery worker on the E2E lane) removes the
artifact from future E2E lanes, independent of the prod cut-over gate
above.

## Housekeeping performed as part of this task

- Rehearsal pull API key `rehearsal-20260921T0011Z` (id
  `c8d83109-9962-4ac4-9cdf-81869f99f7e5`) was revoked via
  `POST /autocount/pull/keys/{id}/revoke` (session-authed operator route;
  synchronous, no deferred-action commit step needed for this route -
  confirmed against `tests/test_s10_s4_pull_key_routes.py`). `GET
  /autocount/pull/keys` confirmed `revokedAt: "2026-09-21T03:32:32.229974Z"`;
  a subsequent gateway call with the (now revoked) key answered `401
  INVALID_API_KEY` ("Missing, malformed, unknown or revoked key.").
- The rehearsal key plaintext and the login token were deleted from the
  scratchpad after use; neither is recorded anywhere in this document or
  the repo.
- Lane backend (`uvicorn`, pid `80398`, cwd
  `.claude/worktrees/s40/service_backend`) was stopped and `:8009` was
  confirmed free.
