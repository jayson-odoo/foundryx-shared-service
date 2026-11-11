# Plan 63 UAC: AutoCount db1 writes from production only (key, gate, person, calls view)

Plan: `63-autocount-db1-ready.md`. Lane AC-DB1-READY. Every AC is a pytest (fake vendor / MockTransport, never a real
book) unless marked [FE] (vitest) or [B] (agent-browser run at 375px and 1280px on the crew test copy). No AC ever
calls db1 or db2.

## A. Optional AutoCount API key on the hapi connection
- AC-63-01 The AutoCount connection form (auth "none") shows four more fields: "API key" (secret, blank = none),
  "API key header" (default `X-API-Key`), "API key format" (default `{key}`), "Send API key on reads" (No / Yes,
  default No). The key is stored Fernet-encrypted in `connections.credentials_json`; the other three in `config_json`.
  A connection saved before this change (no such keys) behaves as "no key".
- AC-63-02 No key set: every write request (POST / PUT / DELETE) and every GET carries exactly the headers it carries on
  main 7b9335b6 (no auth header of any name). Proven by a MockTransport capturing the request headers.
- AC-63-03 Key set: every write request carries ONE header `<API key header>: <API key format with {key} replaced>`,
  e.g. format `Bearer {key}` -> `Authorization: Bearer k1`. Every other header unchanged.
- AC-63-04 Key set, "Send API key on reads" = No: write-back read GETs (bydocno, day-list, debtor term, read-back),
  pull-sync GETs and the connection probe carry no key header. Same with "Yes": they carry it.
- AC-63-05 Rotation: change the key on the connection, the very next write sends the new value (no restart, no cache).
  Clear the key: the next write sends no key header.
- AC-63-06 Invalid header name (not an RFC 7230 token, or one of Host / Content-Length / Content-Type /
  Transfer-Encoding / Connection / Cookie), a format without exactly one `{key}`, or CR / LF / non-printable in key or
  format: the write is refused BEFORE any request with `AUTH_CONFIG_INVALID`, logged as a guard refusal; never a 500,
  never the key in the message. Saving such a connection is refused 422 with a plain message when the provider has a
  save-time validator.
- AC-63-07 The key value never appears in: `ac_api_call_log` (any column), `ac_write_action` (any column), the
  http_source call records, any log line (caplog at DEBUG), any exception text or API answer, the connection GET.

## B. Production-only gate
- AC-63-10 Writable books = code constant `WRITE_ALLOWED_BOOKS` {db1, db3} AND env `AUTOCOUNT_WRITE_ALLOWED_BOOKS`
  (comma list, default `db3`) AND, unless `settings.environment == "production"`, the test-book constant {db3}.
  Matrix test: environment {development, test, production, "Production", ""} x book {db1, db2, db3, db4} x env list
  {unset, "db3", "db1", "db1,db3", " db1 , db3 "}: writable exactly when the formula says so.
- AC-63-11 Off production, a company whose write connection is `/api/db1` on the allowlisted host, with env list
  `db1,db3`: every write is refused `WRITE_NOT_ALLOWED` before any request, one `guard_refused` call-log row, zero
  requests on the transport. Same for `set-write-connection` (CLI prints `error: WRITE_NOT_ALLOWED`).
- AC-63-12 Production + env list `db1,db3`: a db1 write goes out (fake vendor). The host digest rule is unchanged
  (db1 on any other host = `WRITE_NOT_ALLOWED`).
- AC-63-13 `assert_test_company` skips its live-book check ONLY for a book that is writable AND not a test book (so
  only in production). Off production a company with SQL source / synced PO / SO rows is still
  `WRITE_COMPANY_NOT_TEST` for every book; in production a db1 company with synced rows passes; a db3 company with
  synced rows is still refused in production.
- AC-63-14 The gate is read per call: switching `settings.environment` or the env list in a test takes effect on the
  next write without re-creating the client.
- AC-63-15 `docker-compose.yml` x-backend-env carries `AUTOCOUNT_WRITE_ALLOWED_BOOKS: ${AUTOCOUNT_WRITE_ALLOWED_BOOKS:-db3}`;
  `deploy.yml` ENV_CONTENT carries `AUTOCOUNT_WRITE_ALLOWED_BOOKS=${{ vars.AUTOCOUNT_WRITE_ALLOWED_BOOKS || 'db3' }}`.

## C. Person and request id on every write
- AC-63-20 Every write route (`/api/v1/autocount/documents/...`, `/write-operations/...`, PO link routes) reads
  optional `X-Acting-User-Id` (1..64 printable ASCII) and `X-Acting-User-Name` (UTF-8 percent-encoded, 1..128 chars
  after decoding, control characters removed). Both reach every `ac_api_call_log` row and every `ac_write_action` row
  the request causes; `X-Request-ID` (existing rule) also lands on `ac_write_action.request_id`.
- AC-63-21 Missing or invalid person headers store NULL and the write runs exactly as today (never 4xx for them).
  A non-ASCII name (`%E9%99%88%E5%A4%A7%E6%96%87`) is stored decoded.
- AC-63-22 Runner and system calls store NULL person. Existing rows keep NULL (no invented person).
- AC-63-23 Migration `0045_autocount_call_person` adds nullable `acting_user_id`, `acting_user_name` to
  `ac_api_call_log` and `request_id`, `acting_user_id`, `acting_user_name` to `ac_write_action`; single head; upgrades
  on live Postgres.

## D. "AutoCount calls" view
- AC-63-30 `GET /autocount/calls` (JWT, `autocount.sync.read`, tenant from the JWT only) pages
  `ac_api_call_log` newest first; another tenant's rows never appear; no permission = 403.
- AC-63-31 Filters (combine with AND, multi values with OR): date range (from / to instants), company, book,
  document type, outcome, person (acting user id); search matches document no, request id or path (case-insensitive).
- AC-63-32 Server sort on every column (time, company, book, person, method, path, document type, document no,
  outcome, HTTP status, duration, error code, request id), asc / desc, unknown field = 422; the order holds on page 2.
- AC-63-33 `GET /autocount/calls/filter-options` returns the tenant's distinct books, document types, outcomes
  and persons (id + latest name); `GET /autocount/calls/{id}` returns one row with request JSON and the stored
  (already redacted) response body; another tenant's id = 404.
- AC-63-34 [FE] The page "AutoCount calls" is the shared ResourceList: one toolbar row (Search, Filters, Columns), every
  row one line with "..." + hover for long text, columns hideable / reorderable and kept per user, every filter
  multi-select, date range through the shared date range picker (no native date input), filters + sort + page in the
  address bar. No Create button (a log has nothing to create).
- AC-63-35 [FE] Time reads `dd/mm/yyyy, h:mm am/pm`; a missing person, status or error reads "-"; outcomes read in
  plain words (OK, Refused by AutoCount, Timed out, Could not connect, Blocked by SS).
- AC-63-36 [FE] Clicking a row opens a centred dialog with the request JSON and the response body; nothing opens in a
  side panel.
- AC-63-37 [B] Sidebar AutoCount > Calls opens the page; filter by book db3 + outcome OK + a date range shows only
  matching rows; sort by duration desc holds on page 2; 375px and 1280px.

## E. Unchanged
- AC-63-40 Pull sync, doc feeds and every read path behave as on main when no key is set (their existing suites pass
  untouched); db3 writes off production behave as on main.
