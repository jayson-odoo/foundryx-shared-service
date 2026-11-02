# Plan 50 acceptance criteria: per-key limits on the API key routes

| AC | Rule |
|---|---|
| AC-50-01 | [BE] Every `/api/v1` route authenticated by a workspace API key counts requests per key. A key may have at most 10 requests in progress and 600 started per rolling minute (fixed one-minute window is acceptable) |
| AC-50-02 | [BE] A request over either limit answers 429 with a `Retry-After` header (seconds, at least 1) and the guide's error body (`rate_limited`), before any database work. A request that is refused does not count as in progress |
| AC-50-03 | [BE] Both numbers are settings: `OMNI_KEY_MAX_IN_FLIGHT` (default 10) and `OMNI_KEY_MAX_PER_MINUTE` (default 600), plus `OMNI_KEY_LIMIT_OVERRIDES`, a JSON map from key id to either or both numbers. A restart picks up a change; no deploy, no schema change |
| AC-50-04 | [BE] Counters are shared across workers (Redis at `REDIS_URL`). An in-progress slot is released when the request ends, including on error or client disconnect, and expires on its own if a worker dies |
| AC-50-05 | [BE] Every 429 is logged once with the key id, the limit hit and the route name; never the payload, the key or its prefix |
| AC-50-06 | [BE] If Redis cannot be reached, requests are allowed and a warning is logged at most once a minute per worker |
| AC-50-07 | [T] `documentation/omnichannel/consumer-integration-guide.md` documents the limits, the 429 body, `Retry-After`, and that ops can raise a key's limits on request |

No migration, no new permission, no screen change. The partner's per-key traffic in production was not measured; the defaults follow the crew ruling of 2 Nov.
