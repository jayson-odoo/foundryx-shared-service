# Plan 51 acceptance criteria: limits on one webhook delivery

| AC | Rule |
|---|---|
| AC-51-01 | [BE] One delivery attempt (the POST to a consumer's callback URL) ends within a total deadline of 10 seconds, whatever the server does: slow headers, a slow trickle of body bytes, or a stalled connection. Past the deadline the attempt is recorded as failed with fixed text |
| AC-51-02 | [BE] At most 64 KiB of the response body is read; a larger body is not read further. The status code decides success as today |
| AC-51-03 | [BE] No database transaction or pooled connection is held while the POST is in flight |
| AC-51-04 | [BE] Retries, dead-letter counting, the stored attempt row and the signed request are otherwise unchanged; a timed-out or capped attempt counts as one failed attempt |
| AC-51-05 | [T] `documentation/omnichannel/consumer-integration-guide.md` states that a delivery attempt waits at most 10 seconds and that the response body is not used |

No migration, no new permission, no screen change.
