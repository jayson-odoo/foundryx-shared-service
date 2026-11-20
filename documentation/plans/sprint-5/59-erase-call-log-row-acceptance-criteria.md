# Plan 59 acceptance criteria (the erase call's own log row)

Plan: `59-erase-call-log-row.md`. Follow-up to plan 56 C (contact erase, PR #188). Final: crew rulings 1a 2a 3a 4a 5a (5 Nov) on the behaviour card.

## Journey

1. An integration erases a contact with its workspace API key by phone: `DELETE /api/v1/omnichannel/contacts/phone:+60...`, exactly as plan 56 C ships it. The answer is unchanged.
2. The gateway still writes one Developers > Logs row for the call. Its operation reads `DELETE /contacts/phone:<erased>`, and the request details show the same path. The number is not in the row.
3. An erase by id (`id:<uuid>` or a bare id) and every other call (for example `GET /contacts/phone:+60...`) are logged exactly as today.

## S1. The erase call's row

- AC-59-01 [BE] Given a workspace API key, when it erases a contact through `DELETE /api/v1/omnichannel/contacts/phone:<number>` and the erase answers 200, then the call's `integration_activity` row has `operation` = `DELETE /contacts/phone:<erased>` and `request_summary_json.path` = `/api/v1/omnichannel/contacts/phone:<erased>`, and no column of that row contains the number's digits.
- AC-59-02 [BE] The same holds whatever the answer: an unknown number, a contact of another workspace, and a second erase of the same number (all 404) each write a row with `phone:<erased>` and without the digits.
- AC-59-03 [BE] The identifier is masked however it is written: `phone:` in upper or mixed case (`PHONE:`, `Phone:`), and the percent-encoded form (`phone%3A%2B60...`), all log `phone:<erased>`.
- AC-59-04 [BE] A call that writes no row today still writes none: a bad or revoked key (401) leaves no row, as before.
- AC-59-05 [BE] An erase by id logs unchanged: `DELETE /contacts/id:<uuid>` and `DELETE /contacts/<uuid>` keep the id in `operation` and `request_summary_json.path`.
- AC-59-06 [BE] Every other route logs unchanged, including the same identifier on another method or path: `GET /contacts/phone:<number>`, `GET /contacts/phone:<number>/messages`, `PATCH /contacts/phone:<number>` and `POST /contacts/phone:<number>/read` keep the number in `operation` and `request_summary_json.path`.
- AC-59-07 [BE] The erase itself is unchanged: response shape and status codes, the plan 58 register row (when merged), the `contact.erased` event, and the rest of the activity row (status, status code, latency, trace id, workspace and key ids, response summary).
- AC-59-08 [BE] Logging still never breaks the request: the masking runs inside the existing guarded `_record` path (`app/activity_log/middleware.py`), so a failure there is logged and swallowed, never surfaced to the caller.

## Contract and docs

- AC-59-20 [T] No wire change. The consumer guide section "Erase a contact" gains one line: the log of the erase call shows `phone:<erased>` in place of the number; one changelog row dated 2026-11-05.
- AC-59-21 [T] `documentation/engineering/omnichannel-service.md` "Contact erase" paragraph: the "core logs (30 days)" clause says the erase call's own row keeps no number, and earlier calls' rows age out in 30 days.
- AC-59-22 [E2E] On the crew test copy (1280 and 375): erase a contact by phone with a key, open Developers > Logs, the newest row's operation and its detail view show `phone:<erased>` and no number; an earlier `GET /contacts/phone:...` row still shows its number.
