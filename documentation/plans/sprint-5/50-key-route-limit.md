# Plan 50: per-key limits on the API key routes

UAC: `50-key-route-limit-acceptance-criteria.md`. Size M. Branch `crew/ss-key-route-limit`. Crew ruling AP (a), 2 Nov.

## Design

```text
app/config.py         omni_key_max_in_flight=10, omni_key_max_per_minute=600, omni_key_limit_overrides="{}"
key auth dependency   after the key is resolved (modules/omnichannel/api_auth.py), before any other DB work:
                        minute counter: INCR key:min:<id>:<epoch_min>, EXPIRE 120; over limit -> 429 Retry-After=seconds to next minute
                        in-flight:      INCR key:busy:<id>, EXPIRE 60 (refreshed); over limit -> DECR, 429 Retry-After=1
                        release:        DECR in a finally around the request (yield dependency)
Redis down           allow, warn at most once a minute per worker
```

## Changes

| Area | File | Change |
|---|---|---|
| Settings | `app/config.py` | Three settings |
| Limiter | new `modules/omnichannel/services/key_limits.py` | Redis counters, overrides, fail-open |
| Auth | `modules/omnichannel/api_auth.py` | Apply after the key resolves; release in a `finally` |
| Errors | gateway error helper | `rate_limited` body as the guide's error envelope |
| Guide | `documentation/omnichannel/consumer-integration-guide.md` | Limits, 429, `Retry-After`, raising a key's limits |
| Tests | new test files | Per AC; a fake Redis (fakeredis if available, else a small in-memory stub with the same calls) |

## Traps

- Count before any database work, release even when the handler raises or the client goes away.
- A refused request never holds a slot.
- Key id in logs only.
- The streaming or SSE routes, if any, hold a slot for their whole life: check and decide.

Slices: S1 tester red, coder. S2 lead kill plus a real-server check on the 429 and slot release. S3 reviewer plus security-reviewer. S4 guide-writer for AC-50-07.
