# SS-MIGRATION-CURSOR: respond.io list pagination sends the documented cursorId

Lane SS-MIGRATION-CURSOR. Size S (hotfix on live SS) plus a local end-to-end dry run against the
real MyFuji workspace before hand-back. Base: origin/main (has #180, #182, #184, #187).

## Symptom

Owner's MyFuji dry run (Omnichannel > Migration, MyFuji Platform, Dry run, 4 Nov 17:32-17:33 MYT,
after #187 went live) processed 99/796 contacts, then failed with
`respond.io error: Invalid cursorId`. Page 1 (no cursor, `limit=99`) works; the page 2 request
carries a cursor respond.io does not accept.

## Official contract (developers.respond.io, API v2, rendered 4 Nov 2026)

Every list endpoint documents the same shape. Query: `cursorId` + `limit`. Response:
`{items, pagination: {next, previous}}` where `next` / `previous` are FULL URLs that carry the
cursor in their own `cursorId` query parameter.

| Endpoint | Doc page | `cursorId` type | `pagination.next` example (verbatim) |
|---|---|---|---|
| `POST /contact/list` | `docs/api/0759d02787ab3-list-the-contacts` | integer, "Pointer to the contact id from where the next batch of records should start from." | `https://api.respond.io/contact/list?limit=10&cursorId=-10` |
| `GET /contact/{identifier}/message/list` | `docs/api/m4ay6be8n8ckc-list-messages` | string, "Pointer to the message id from where the next batch of records should start from." | `https://api.respond.io/contact/{identifier}/message/list?limit=10&cursorId=10` |
| `GET /space/user` | `docs/api/96d00b7396970-list-users` | integer | `https://api.respond.io/space/user?limit=10&cursorId=10` |
| `GET /space/custom_field` | `docs/api/172e05dbb955d-list-custom-fields` | integer | `https://api.respond.io/space/contact_field?limit=10&cursorId=10` |
| `GET /space/channel` | `docs/api/57c6923fef9e9-list-channels` | integer | `https://api.respond.io/space/channel?limit=10&cursorId=10` |
| `GET /contact/{identifier}/channels` | `docs/api/a17bccb520d2e-list-contact-channels` | integer, `limit` default 10 | `https://api.respond.io/contact/{identifier}/channels?limit=10&cursorId=10` |

Review round 1 (reviewer, should-fix): `get_contact_channels` read only the first page, so a
contact with more than the vendor's default 10 channels lost identities. It now walks
`_paginated` like every other list call (red `ab5e4fd1`, fix `0e20ab36`).

The API overview page: "The integration can use the `pagination.next` in another request to
receive the next part of the list". The example URLs omit the `/v2` prefix, so the client must
NOT request `next` as a URL; it takes the `cursorId` out of it.

## Root cause (read from the code)

`RespondIoClient._paginated_pages` (`service_backend/modules/omnichannel/respondio/client.py`)
does `cursor = pagination.get("next")` and sends that whole value as `cursorId` on the next
request. With the real vendor that is the full URL, so page 2 is
`?limit=99&cursorId=https://api.respond.io/contact/list?limit=99&cursorId=...` and the vendor
answers 400 `Invalid cursorId`. Every test mock returned a bare cursor in `next`, so no test saw
the real shape. Every paginated respond.io call goes through this one generator:

- migration contacts phase `services/migration_service.py` (`list_contacts_pages`, resumable)
- preflight lifecycle scan (`list_contacts`)
- messages phase (`list_messages_pages`)
- continuous sync tick poll/final sweep `services/migration_sync_service.py` (`list_contacts_pages`)
- preflight space reads (`list_space_channels/users/custom_fields`)

## Fix

1. One helper `_next_cursor_id(next_value)` in `respondio/client.py`: a URL -> the verbatim
   `cursorId` query value (string, as issued); a URL with no `cursorId` -> no next page plus a
   blocker (we cannot follow it); a bare non-URL value -> used as is (keeps the existing mocks and
   any future bare cursor working); `None` / empty -> last page.
2. `_paginated_pages` uses it for `next`, and also normalises `start_cursor`, so a job whose
   checkpoint stored the full URL before this fix (the failed prod dry run) resumes with the
   right cursor.
3. The same-cursor and empty-page guards compare the extracted cursor ids.
4. No schema, UI, permission or wire change. No user-visible change beyond the migration working.
   guide: n/a.

## Tests (red first, `tests/test_omnichannel_migration_contact_list_cursor.py`)

Strict mock: every page answers `next` as the documented full URL with a fresh cursor; any
request whose `cursorId` was not issued by the previous page is the live 400
`Invalid cursorId`.

- `list_contacts_pages` walks 3 pages (99 + 99 + 50) and yields bare cursors; last page stops.
- `list_contacts` (preflight) and `list_messages_pages` / space reads walk past page 1.
- Resume from a stored full-URL cursor sends the bare id.
- Last page signalled by `next` null, missing, or empty string: clean stop, no blocker.
- Migration dry run end to end with 250 contacts against the strict mock: job done, 250 fetched.
- Sync tick (poll) with more than one page against the strict mock walks every contact.

Kill test: revert the helper call, the same tests fail with `Invalid cursorId`.

## End-to-end proof (owner requirement)

Local SS test copy, respond.io connection with the MyFuji key (read from the crew key file, never
printed or committed), Workspace timezone `Asia/Kuala_Lumpur`, Omnichannel > Migration > Dry run
to completion. Report counts, duration, errors only. Dry run never writes to respond.io.
