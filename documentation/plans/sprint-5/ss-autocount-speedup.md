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
