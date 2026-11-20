# Plan 50 acceptance criteria: per-key limits on the API key routes

| AC | Rule |
|---|---|
| AC-50-01 | [BE] Every route authenticated by a workspace API key (the `/api/v1` gateway, the media route and the ideation intake routes) counts requests per key. A key may have at most 10 requests in progress and 600 started per rolling minute (fixed one-minute window is acceptable) |
| AC-50-02 | [BE] A request over either limit answers 429 with a `Retry-After` header (seconds to the next minute for the minute limit, 1 for the in-progress limit) and the guide's error body (`rate_limited`). Only the key lookup runs before the check; a refused request does not touch the key row (no `last_used_at` stamp) and does not count as in progress or toward the minute. The activity log records the 429 as it records every gateway request |
| AC-50-03 | [BE] Both numbers are settings: `OMNI_KEY_MAX_IN_FLIGHT` (default 10) and `OMNI_KEY_MAX_PER_MINUTE` (default 600), plus `OMNI_KEY_LIMIT_OVERRIDES`, a JSON map from key id to either or both numbers. Values below 1 or not whole numbers are ignored with a warning. The variables pass through `docker-compose.yml` and the deploy's env; ops change them in the host `.env` and recreate the backend container, and set the matching repository variable so the next deploy keeps them. No schema change |
| AC-50-04 | [BE] Counters are shared across workers (Redis at `REDIS_URL`). Each request in progress is its own entry with its own expiry, so a slot left by a killed worker expires on time even while the key keeps calling. A slot is released when the request ends, including when the endpoint itself answers an error |
| AC-50-05 | [BE] Every 429 is logged once with the key id, the limit hit and the route name; never the payload, the key or its prefix |
| AC-50-06 | [BE] If Redis cannot be reached, requests are allowed and a warning is logged at most once a minute per worker, on its own timer separate from other warnings; a Redis call gives up quickly (well under a second) |
| AC-50-07 | [T] `documentation/omnichannel/consumer-integration-guide.md` documents the limits, the 429 body, `Retry-After`, and that support can raise a key's limits on request; the ideation intake contract notes the same 429; `DEPLOY.md` notes how ops change the values |

No migration, no new permission, no screen change. The partner's per-key traffic in production was not measured; the defaults follow the crew ruling of 2 Nov.
