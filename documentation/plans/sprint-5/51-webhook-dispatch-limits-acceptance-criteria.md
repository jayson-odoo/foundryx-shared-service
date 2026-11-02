# Plan 51 acceptance criteria: limits on one webhook delivery

| AC | Rule |
|---|---|
| AC-51-01 | [BE] One delivery attempt (the address check and the POST to a consumer's callback URL) ends within a total deadline of 10 seconds, whatever the server does: a slow connect, `100 Continue` or header bytes sent slowly, a slow trickle of body bytes, or a stalled connection. Past the deadline the attempt is recorded as failed with the fixed text, any open connection is closed, a connection that completes later is closed before anything is sent, and nothing is sent for that attempt after it is recorded. A host name lookup already in progress cannot be interrupted; it may finish in the background, and it sends nothing |
| AC-51-02 | [BE] At most 64 KiB of the response body is read; a larger body is not read further. The status code decides success as today |
| AC-51-03 | [BE] No database transaction or pooled connection is held while the POST is in flight |
| AC-51-04 | [BE] Retries, dead-letter counting, the stored attempt row and the signed request are otherwise unchanged; a timed-out attempt counts as one failed attempt, and a capped body with a 2xx status counts as a success |
| AC-51-06 | [BE] The stored error of a failed attempt is fixed text (the status code, the error class or the deadline sentence), never bytes the server sent and never the host or address |
| AC-51-05 | [T] `documentation/omnichannel/consumer-integration-guide.md` states that a delivery attempt waits at most 10 seconds and that the response body is not used |

No migration, no new permission, no screen change.
