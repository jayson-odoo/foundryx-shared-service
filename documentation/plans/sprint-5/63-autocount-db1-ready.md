# Plan 63: AutoCount db1 writes from production only (optional key, prod gate, person trace, calls view)

Lane AC-DB1-READY, branch `crew/ac-db1-ready`, base main 7b9335b6, size L. UAC: `63-autocount-db1-ready-acceptance-criteria.md`.
Builds on plan 55 (write guard), 57 (QT/SO writes, contract section 8 `X-Request-ID`), 61 (write v2, call log).

## 1. Why (owner, 11 Nov, verbatim)

"never ever write to db1 from the local, all should happen from production that will be traced. I informed AutoCount
team to set up API key as auth for write API so we need to be prepared for that." / "the key should be optional, it can
be no auth also which I think it is like that now, it should not affect existing endpoint for read and db get, and key
is coming from shared service right, between SS and CRM are different key"

## 2. Facts (main 7b9335b6; M = `service_backend/modules/autocount`, wb = `M/write_back`)

- F1 No AutoCount auth today. hapi = the `autocount` provider with `auth="none"` (`M/provider.py:67-75`); fields
  `M/provider.py:124-224` (appId / password secret only under `auth=basic`). Write client sends JSON only
  (`wb/client.py:95-113`), reader `wb/reader.py:81-88`, pull sync `M/http_source/client.py:240-269` (Accept +
  User-Agent), probe `M/http_client.py:132` (Accept). A field is a Fernet secret by `"secret": True`
  (`app/services/integration_service.py:296,343`); the FE renders fields generically
  (`settings/integrations/components/connection-form-fields.tsx:73,96`, blank secret = keep, `connection-schema.ts:151-170`).
  No boolean field type: use a select.
- F2 Guard: `WRITE_ALLOWED_BOOKS = {"db3"}` + host sha256 allowlist (`wb/guard.py:15-24,97-104`), run per request
  (`wb/client.py:97`). `assert_test_company` refuses any company with a SQL source or synced PO / SO / SPO rows
  (`wb/guard.py:41-54`); a production db1 company always has synced rows, so it needs the same production exception.
  Not environment-aware. `write_connection_id` set only by the CLI (`wb/admin.py`, `wb/service.py:820`).
- F3 Base URL path: `company.write_connection_id` -> connection `config_json["baseUrl"]` (`wb/frame.py:205-229`,
  `wb/pull_docs.py:79-90`); client built by `client_factory(base_url)` (`wb/frame.py:135,163`, `wb/runner.py:164,745,1205`).
  Write-back never decrypts credentials today; module decrypt pattern `M/services/company_service.py:1556-1562`.
- F4 `settings.environment` plain str default "development" (`app/config.py:173`); prod sets
  `ENVIRONMENT: production` (`docker-compose.yml:29`); comma-list setting pattern `cors_origins_list`
  (`app/config.py:152-170`); env allow-list anchor `x-backend-env` (`docker-compose.yml:14`, AUTOCOUNT block :68-73);
  deploy ENV_CONTENT `.github/workflows/deploy.yml:343-406`, default pattern :345.
- F5 Call log: `ac_api_call_log` (`M/models.py:1179-1212`) has `actor` (key id | runner | system) and `request_id`
  (`X-Request-ID`, else Idempotency-Key; `wb/call_log.py:46-60`), no person. `ac_write_action`
  (`M/models.py:1097-1136`) has `key_id`, no request id, no person. `CallContext` `wb/call_log.py:64-76`, created at
  `wb/frame.py:151-157`, `wb/runner.py:163`, `wb/pull_docs.py:109`. Headers read in `write_v1._frame`
  (`M/routers/write_v1.py:240-275`, request id :256, `give_request_id` `wb/call_log.py:185`) and `M/routers/pull_v1.py:585`.
- F6 No screen reads the call log. No AutoCount list sorts on the server; lists are `ResourceList` configs
  (`components/platform/resource-list/resource-list.tsx`, e.g. `use-doc-feed-issues-list-config.tsx`); no dd/mm/yyyy
  formatter in `lib/datetime.ts` (`formatDateTime` :91 = "02 Jan 2024, 13:45"); shared `DateRangePicker`
  `components/platform/date-range-picker/date-range-picker.tsx:141`; centred-dialog row open
  `review/[jobId]/components/staged-records-list.tsx:65-125`. Nav = 3 copies in `config/menu.config.tsx`
  (:416-445, :613-645, :796-825). Permission keys `autocount-meta.ts:23-28`.
- F7 Latest module migration `0044_autocount_api_call_log` (`M/alembic/versions/0044_autocount_api_call_log.py:16`);
  no 0045 on any open crew branch (checked 11 Nov).
- F8 UNVERIFIED: whether db1 is served by the same allowlisted wrapper host as db3 (the local DB holds no book-path
  connection). Not opened by env: the owner checklist step 4 tells (CLI prints `WRITE_NOT_ALLOWED`).

## 3. Design

### 3.1 Optional key (UAC A)
- Four new fields on the autocount provider, all `showWhen auth=none`: `apiKey` (password, secret, optional),
  `apiKeyHeader` (text, default `X-API-Key`), `apiKeyFormat` (text, default `{key}`; `Bearer {key}` allowed),
  `apiKeyOnReads` (select No / Yes, default No). Defaults are only used once a key is set; AutoCount's real header is
  entered by the owner (they have not published it yet).
- ONE helper `M/write_back/auth.py`: `auth_headers(conn_config, credentials, *, for_read: bool) -> dict` returns `{}`
  when no key, or when `for_read` and the reads flag is not Yes; else one header. Validates (AC-63-06) and raises
  `AuthConfigInvalid` (code `AUTH_CONFIG_INVALID`, no value in the text). Credentials decrypted with the module
  pattern (InvalidToken -> clean refusal).
- Wiring: the frame / pull_docs / runner resolve the connection per action (no cache, so rotation = next action) and
  hand the headers to the write client and the reader (a setter like `attach_call_log`, so injected test factories
  keep working); http_source client and probe get the read headers from their connection. Headers are never passed to
  `CallLog.record` (it has no header parameter, keep it so).

### 3.2 Production gate (UAC B)
- `guard.py`: `TEST_BOOKS = {"db3"}`; `WRITE_ALLOWED_BOOKS = {"db1", "db3"}` (code ceiling, a review to widen);
  `writable_books()` = ceiling AND `settings.autocount_write_allowed_books_list` AND (TEST_BOOKS unless
  `settings.environment == "production"`, exact string). `assert_write_allowed` uses it per call.
- `assert_test_company(db, tenant_id, company_id, book=None)`: skips the live-book check only when `book in
  writable_books() - TEST_BOOKS`. Every caller passes the book of the write connection URL. Host digest unchanged.
- Settings `autocount_write_allowed_books: str = "db3"` (env `AUTOCOUNT_WRITE_ALLOWED_BOOKS`), list property like
  `cors_origins_list`. Compose + deploy lines per AC-63-15.
- The plan-55 guard tests that pin the ceiling to {db3} (`test_autocount_write_back_guard.py::test_ac_55_02_*`) are
  updated to the new ceiling on purpose; the test-book rule they protected now lives in `TEST_BOOKS`.
- A write refused at connection resolve time (`wb/frame.py:205-229`, before any client exists) also writes one
  `guard_refused` call-log row, so a refused db1 attempt is visible on the calls view.

### 3.3 Person (UAC C)
- Headers `X-Acting-User-Id`, `X-Acting-User-Name` (percent-encoded UTF-8), parsed next to `X-Request-ID` in
  `write_v1._frame` and `pull_v1` (:585) by `call_log.person_of(...)`; handed on with the request id
  (`give_request_id` becomes `give_trace(target, request_id, person)`), stored in `CallContext` and on every
  `ac_write_action` row. Invalid = NULL, never a refusal. Header names posted to CRM lanes OI-PO-LINK / AC-QTSO-CRM-2
  (crew note `crew/state/files/AC-DB1-READY-person-headers.md`).
- Migration `0045_autocount_call_person` (AC-63-23). Backfill: none; old rows have no known person, NULL shows "-".

### 3.4 Calls view (UAC D)
- BE: `M/routers/calls.py` mounted at `/autocount/calls` (the JWT prefix, never the public `/api/v1/autocount` gateway) (JWT, `require_permission("autocount.sync.read")`, no new permission, no grant sweep) ->
  `M/services/call_log_service.py` -> `M/repositories/call_log_repository.py` (tenant-scoped, sort whitelist, ilike
  search, filters). Routes: list, filter-options, detail.
- FE: `/autocount/calls` page, `use-calls-list-config.tsx` (ResourceList), service methods in
  `services/autocount-service{,.real,.mock}.ts`, nav entry "Calls" in the 3 menu copies. Server sort: if ResourceList
  cannot hand sort to the fetcher, add that to the shell (one option, reused by later lists). dd/mm/yyyy helper added
  to `lib/datetime.ts` if none exists. Date range through the shared `DateRangePicker`.

## 4. Slices (commit per behaviour, red tests first)
- S0 tester: red pytest for A, B, C, D-BE + vitest for D-FE (test list section 5).
- S1 gate (B). S2 key (A). S3 person + migration (C). S4 calls API (D-BE). S5 calls page (D-FE).
- S6 guide-writer: contract 57 section 8 gains the two person headers; AutoCount write engineering doc notes the
  gate + key. Reviewer + security-reviewer in parallel, hand test on the crew copy (db3 only).

## 5. Test list (tester)
Key: no key -> no auth header on POST/PUT/DELETE/GET (MockTransport); key -> exact header on writes; reads flag No/Yes on
reader + http_source + probe; rotation next write; clear key; each AC-63-06 invalid case refused pre-send; key absent
from DB rows / caplog / exception / API answer. Gate: AC-63-10 matrix; db1 refused off-prod with DB config (zero
requests, one guard_refused row, CLI error); prod db1 allowed; host digest still enforced; assert_test_company
exception matrix; per-call settings read. Person: header parse cases incl. non-ASCII, invalid, absent; rows carry
person + request id; runner NULL. Calls API: tenant isolation, 403, each filter, each sort field + page 2, 422 unknown
sort, filter-options, detail 404 cross-tenant. FE: list config columns + plain outcome words + "-", dd/mm/yyyy format,
filters map to query params, row click opens dialog. Kill tests: reviewer mutates the gate formula and the
"no key -> no header" branch.

## 6. Owner prod checklist (goes in the PR body)
1. Merge and deploy; confirm the deploy log shows module migration `0045_autocount_call_person` applied.
2. Set GitHub repo variable `AUTOCOUNT_WRITE_ALLOWED_BOOKS` = `db1,db3`, redeploy (env change needs container recreate).
3. When AutoCount sends the key: Settings > Integrations > the db1 AutoCount connection: API key, header, format as
   AutoCount says; "Send API key on reads" = Yes only if AutoCount says reads need it. Save.
4. On the prod host run `set-write-connection` for the db1 company (command in the PR body); `ok` = ready,
   `error: WRITE_NOT_ALLOWED` = db1 is not on the allowlisted host or step 2 missing.
5. Turn on the CRM write switch for db1 (CRM admin).
6. One deliberate test action from the CRM on db1; open AutoCount > Calls, filter book db1: the row shows you as the
   person, outcome OK, the CRM's request id.
7. Rollback any time: set the variable back to `db3` and redeploy; db1 writes are refused at once, no code change.
