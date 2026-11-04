# SS-MIGRATION-TZ-HOTFIX: respond.io contact list always sends an IANA timezone

Lane SS-MIGRATION-TZ-HOTFIX. Size S (hotfix on live SS). Base: origin/main (has #180, #182, #184).

## Symptom

Owner's MyFuji dry run (Omnichannel > Migration, Dry run, 4 Nov 16:02 MYT) failed with
`respond.io error: Sorry, there are errors in your request. Please check if timezone is a valid
IANA timezone name, such as "Asia/Kuala_Lumpur".` This is the third body field the vendor
rejected in a row (filter #182, search #184, now timezone).

## Where the timezone comes from (read from the code)

- The respond.io migration connection form has a free-text field `timezone`
  ("Workspace timezone", placeholder `Asia/Kuala_Lumpur`, `respondio_provider.py:43-49`).
  Nothing validates it on save.
- Every `POST /contact/list` reads it raw: `str(config.get("timezone") or "")`
  - preflight lifecycle scan `migration_service.py:451` -> `client.list_contacts`
  - migration job contacts phase `migration_service.py:2244` / `:2566` -> `client.list_contacts_pages`
  - continuous sync tick `migration_sync_service.py:704` / `:767` -> `client.list_contacts_pages`
- The body is built in ONE place: `_contact_list_body` (`respondio/client.py:465`), which passes
  the stored string through untouched. Anything the owner typed (`GMT+8`, `+08:00`, `Malaysia`,
  lower case, blank) goes to the vendor as is.

## Official contract (developers.respond.io, API v2, read 4 Nov 2026)

Source: https://developers.respond.io/docs/api/0759d02787ab3-list-the-contacts (Stoplight
project `cHJqOjIyMDQ1OA`, node `/v2/contact-api.yml/paths/~1contact~1list/post`).

- `POST /contact/list`. Body schema (`ContactFilter`): `search` string, `timezone` string
  (example `Asia/Kuala_Lumpur`), `filter` object (`$and` or `$or` array of
  `{category, field, operator, value}`). Every official example sends all three:
  `{"search": "", "filter": {"$and": []}, "timezone": "Asia/Kuala_Lumpur"}` ("All Contact(s)").
- Query: `limit` integer, `minimum: 1`, `exclusiveMaximum: 100`, default 10 ("Number of contacts
  to return i.e. page size."); `cursorId` ("Pointer to the contact `id` from where the next batch
  of records should start from."). We send `limit=100` today, which the schema excludes.
- Same doc set: `GET /contact/{identifier}/message/list` `limit` has `maximum: 50`; we send 100.
  `GET /space/channel`, `/space/user`, `/space/custom_field`: `exclusiveMaximum: 100`.

## Fix

1. `respondio_timezone(value)` in `respondio/client.py`: strip; reject offset style (a sign
   followed by a digit, e.g. `+08:00`, `UTC+8`, `GMT+8`, `Etc/GMT-8`); accept only a name in
   `zoneinfo.available_timezones()` (case-insensitive, sent in canonical case); anything else
   (blank, unknown, non-string) -> `Asia/Kuala_Lumpur`. `_contact_list_body` always runs it, so
   all three call sites are covered with no call-site change.
2. Page size matches the doc: `_paginated_pages` clamps `limit` to 1..99 (`exclusiveMaximum: 100`);
   message list clamps to 50 (`maximum: 50`). `CONTACTS_PAGE_LIMIT = 99`,
   `MESSAGES_PAGE_LIMIT = 50`.
3. No schema, UI or permission change. No user-visible change beyond the migration working.

## Tests (red first, `tests/test_omnichannel_migration_contact_list_timezone.py`)

- Client: bad / offset / blank / unknown / lower-case timezones -> exact body
  `{"search": "", "filter": {"$and": []}, "timezone": <IANA>}`; query `limit=99` (+ `cursorId`).
- Client: message list query `limit=50`.
- Migration dry run with connection timezone `GMT+8` against a strict mock that answers the
  live 400 for a non-IANA timezone or an out-of-range limit -> job done, every contact-list body
  exact with `Asia/Kuala_Lumpur`.
- Sync tick (poll + final) with connection timezone `+08:00` -> every contact-list body exact,
  query `limit=99`.
- Kill test: revert the fix, same tests fail; restore.

## Open items (not in this lane)

- The connection form still accepts any text for the timezone (save-time validation would be a
  UI rule change, size M).
- `GET /contact/{id}/channels` is read without `limit` (vendor default 10, `client.py:430`).
