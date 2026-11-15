# SS-AUTOCOUNT-SPEEDUP: cheaper AutoCount write-path calls

Option (c) of the AutoCount latency scout: no change a user can see except a shorter wait.

## Acceptance criteria

- AC-SPD-01 [BE][T] One guarded HTTP client (connection pool) per process is reused by every
  write-back read and write; a connection is not re-opened per call. Timeouts, redirects-off,
  the SSRF guard (checked at connect), the API key header and the allowlist guard before every
  write stay exactly as today.
- AC-SPD-02 [BE][T] Every hapi call still writes one call-log row (same method, path, outcome).
- AC-SPD-03 [BE][T] A `link_row` no longer reads the PO twice in a row: the read-back of the first
  PUT is reused as the fresh read for the second PUT when no other call ran in between.
- AC-SPD-04 [BE][T] Independent first reads (PO and SO) run in parallel where the code allows;
  the live re-read before write and `expectedLastModified` checks stay.
- AC-SPD-05 [BE][T] Refusal / unknown-outcome paths and response shapes are unchanged.
- AC-SPD-06 [T] Before/after table: call count and wall time per link with a fixed mocked per-call delay.

## What changed

| # | Change | Where |
|---|---|---|
| 1 | One guarded `httpx.Client` per process (fork-safe, rebuilt when closed). Each request still carries its caller's own timeout, API key header, redirects off; the SSRF guard still runs on every new connection (at connect); the write allowlist still runs before every write. | `http_client.shared_autocount_client`, `write_back/reader.py` + `client.py` `_http()` |
| 2 | The move edit takes the previous step's read-back instead of an identical second GET: only inside an operation, only for an edit, only for the same DocKey. | `primitives._reusable` / `_prepare`, `operations._move_rows` |
| 3 | The link target's first read (SO for a PO link, PO for an SPO link) runs on a second thread during the document's own first read. Refusal order unchanged (target still checked after the document's own guards); its calls are held and logged on the request thread with their real duration. | `operations._target_beside`, `call_log.BufferedCallLog` |

Who can write the PO between the replace read-back and the move PUT: another SS operation or the
plan-55 `WriteBackService` link flow cannot (both hold the per-PO-document lock for the whole flow,
`link_lock.link_locks`, #244, plus `uq_ac_write_operation_one_in_progress` for operations). A standalone
SS document primitive (it takes no PO lock, its `frame._check_not_busy` only sees in-flight actions) and
an AutoCount desktop user can. Before, the move's own GET would have picked such a write up; now the move
PUT is built from the read-back, so a header change made in that gap (for example Description) would be
sent back as it was. The gap grows by about one GET plus a few local commits (tens of ms to ~1 s); the
same race already existed between the old GET and the PUT. Closing it fully would need a re-read, which
is the call this change removes.

Not changed: the live re-read right before the first PUT, `expectedLastModified` (DOC_STALE),
refusal codes and their order, unknown-outcome / resume / recovery outcomes, response shapes, the
batch path's per-link SO reads.

Side effects, by design:
- The SO read starts with the PO read, so every refusal that comes after the PO read (DOC_NOT_FOUND,
  READ_FAILED, DOC_STALE, ROW_ALREADY_LINKED, ROW_ON_SPO, ROW_RECEIVED, ...) now also makes and logs
  one SO GET. The request waits for it so that it is logged on the request thread: usually no extra
  wait (both reads start together); at worst an SO read that is slower than the PO read (a failed
  bydocno plus the day-list fallback) delays the refusal by that difference.
- No cookie is kept or sent (the shared client refuses cookies). Before, a per-call client only kept
  cookies within one call (the debtor page walk).
- The shared pool has no cap on open connections (only idle ones are capped), so a write never waits
  for a slot. A kept-alive connection the server closes at the moment it is reused fails as a connect
  error and the write is pending (the safe path: resume reads AutoCount); httpcore checks a pooled
  connection before reuse, so this is rare.
- Never call `abort_connections` on the shared transport (nothing does today).

## Measured (mocked vendor, fixed delay per call, median of 5 runs)

| Per-call delay | Before (main): calls / wall | After: calls / wall | Saved |
|---|---|---|---|
| 0 ms | 8 / 71 ms | 7 / 63 ms | 8 ms |
| 44 ms (warm read p50) | 8 / 442 ms | 7 / 340 ms | 102 ms |
| 82 ms (cold read p50) | 8 / 754 ms | 7 / 589 ms | 165 ms |

Connections (real guarded transport, local keep-alive server, 7 reads): before 7 TCP connections,
after 1. The mock has no TLS, so the ~35 ms per new TLS connection (scout report) comes on top in
production.
