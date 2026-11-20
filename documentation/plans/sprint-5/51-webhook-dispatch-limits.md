# Plan 51: limits on one webhook delivery

UAC: `51-webhook-dispatch-limits-acceptance-criteria.md`. Size S to M. Branch `crew/ss-webhook-dispatch-limits`.

| Area | File | Change |
|---|---|---|
| Delivery | `modules/omnichannel/services/webhook_delivery.py` (`dispatch`, `_post`, the attempt loop) | Total deadline on the whole POST (stream the response, stop at 64 KiB, stop at the deadline); release the read transaction before the POST |
| Guide | consumer guide | AC-51-05 |
| Tests | new test file | A local real socket server that trickles bytes and one that sends a large body; spy on transactions during the POST |

Traps: the guarded transport from plan 155 stays in the path; real-socket tests need one Linux run (CI) before they count as proof; keep `SoftTimeLimitExceeded` handling.

Slices: S1 tester red, coder. S2 lead kill. S3 reviewer plus security-reviewer. S4 guide-writer.
