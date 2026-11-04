# Plan 59: the erase call's own log row keeps no phone number

UAC: `59-erase-call-log-row-acceptance-criteria.md`. Follow-up to plan 56 C (PR #188). Size M by the crew contract (wording on an existing screen: Developers > Logs).

## Journey

An integration erases a contact with its workspace API key by phone, exactly as plan 56 C ships it. The gateway still writes one Developers > Logs row for the call, but its operation and request path read `phone:<erased>` in place of the number. Erases by id and every other call log as today.

## Rulings (crew, 5 Nov, on the behaviour card `crew/state/files/ss-fuji/f16-erase-log-card.md`)

- 1a: only the erase route (`DELETE /contacts/{identifier}`); the other 8 identifier routes are unchanged.
- 2a: fixed token `phone:<erased>`; no digits kept.
- 3a: on every answer, errors included (route match, not result).
- 4a: no backfill; existing rows age out with the 30-day retention (`app/config.py:346`, `app/activity_log/retention.py:21`).
- 5a: one line in the consumer guide's erase section plus a changelog row.

## Today (origin/main 5d33707f)

- `IntegrationActivityMiddleware._record` (`app/activity_log/middleware.py:272-320`) writes one row per attributable gateway call: `operation = f"{method} {path[len(_GATEWAY_PREFIX):]}"` (`:295-296`, prefix `/api/v1/omnichannel` at `:66`) and `request_summary_json` from `_request_summary` (`:325-344`), whose `path` is `request.url.path` (`:330`). `request.url.path` is the decoded path, so `phone%3A` arrives as `phone:`.
- Erase route `modules/omnichannel/routers/api_v1.py:437-445`; identifier forms `phone:+60...` | `id:<uuid>` | `<uuid>` (`:208`); the resolver matches `phone:` case-insensitively (`services/public_gateway_service.py:371`). Error texts never echo the identifier (`:359`, `:379`).
- Unattributable calls (bad or revoked key) write no row (`middleware.py:292-293`).
- Shown in Developers > Logs: list column `use-integration-logs-list-config.tsx:69-76`, detail `log-detail-view.tsx:104-124`, trace timeline `trace-timeline.tsx:81`.

## Change

### S1. Mask the erase call's identifier (`[BE]`)

- One helper in `app/activity_log/middleware.py`, applied to the path once in `_record` before both uses (operation and `_request_summary`): when the method is `DELETE` and the path, after `_GATEWAY_PREFIX`, is exactly `/contacts/<segment>` with `<segment>` starting with `phone:` (any case), the segment becomes `phone:<erased>`. Any other method or path, and an `id:` or bare-id segment, passes through unchanged.
- `_request_summary` takes the already-masked path instead of reading `request.url.path` itself, so the two can never differ. Everything else in the summary (method, query, headers, body) is unchanged.
- Core file, gateway-specific rule: the route shape lives next to `_GATEWAY_PREFIX`, which already makes this middleware omnichannel-aware. No module code changes; no new table, column or migration, so no backfill (ruling 4a).

### Docs (`[T]`)

- Consumer guide `documentation/omnichannel/consumer-integration-guide.md` section "Erase a contact" (`:537`): one line (AC-59-20); changelog row 2026-11-05.
- `documentation/engineering/omnichannel-service.md:190` "Not erasable" clause (AC-59-21).
- User guide: n/a. No page under `documentation/user-guides/` covers Developers > Logs or contact erase today; the visible change is one masked path segment.

## Not in this plan

- Earlier calls' rows (for example `GET /contacts/phone:...` before the erase): they age out in 30 days, as plan 56 C accepted (`56-partner-d5-pricing-erase-retry.md:65`).
- Application stdout logs (uvicorn access log): not stored in the database, outside `integration_activity`.
- Masking the identifier on the other 8 routes (ruling 1a).

## Order and gates

1. Plan review: crew (rulings above); this file + UAC committed first.
2. Tester writes red tests from this UAC (`tests/test_activity_erase_row.py`), committed alone as `test(red): ...`; red proof in a clean copy.
3. Coder (one seat) until green; control list = every test file that drives the activity middleware or the erase route (`tests/test_activity_*.py`, `tests/test_omnichannel_contact_erase*.py`, `tests/test_omnichannel_api_gateway.py`, `tests/test_omnichannel_gateway_key_lifecycle.py`).
4. Kill test, then reviewer + security-reviewer in parallel (API-key gateway logging); fix rounds on the same coder.
5. Docs (AC-59-20, AC-59-21) in the same PR; crew browser pass AC-59-22 on the test copy (1280 and 375).
6. PR base `main`, CI at job level, Merge-ready.
