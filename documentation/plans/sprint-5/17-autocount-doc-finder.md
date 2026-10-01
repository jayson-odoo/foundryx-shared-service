# Plan 17: Find an AutoCount document by number (AC-DOC-FINDER)

UAC (the contract): `17-autocount-doc-finder-acceptance-criteria.md`.
Mockup (owner approval gate, build starts only after OK): `documentation/mockups/ac-doc-finder/index.html`.

## 1. Problem

Owner, 1 Oct 2026: "very hard for me to find the autocount data cause idk the doc date ...
make sure this is generic so I can scale to other doc types".

Trigger case: user AIN re-dated `PS202610-0004` in AutoCount from 01/10/2026 to 05/10/2026
(`LastModified 2026-10-01T07:39:22`). The by-DocDate pull for 01/10 no longer returns it, and
the owner has no way to find out where it went.

What the code can do today (verified):

| Fact | Where |
|---|---|
| The vendor exposes only day doors: `/deliveryorderbydocdate?DocDate=yyyyMMdd` and `/deliveryorderbyLastModified?lastModified=yyyyMMdd`; one GET per day, plain array, no paging | `doc_feed/constants.py:17-18`, `doc_feed/vendor.py:54-72` |
| A DO snapshot reads by DocDate only, and `docNo` only filters the days it read | `doc_feed/snapshot.py:156-157`, `:202-203` |
| `docNo` alone means "the 31 days ending today": it never looks forward and never by LastModified | `services/pull_gateway_service.py:158-173` |
| Snapshot rows can be paged but not searched | `routers/pull.py:193`, `routers/pull_v1.py:389` |
| Snapshots expire on their TTL, so they only hold short-term history | `services/pull_service.py:259` |
| The DO feed ledger keeps `doc_no`, `doc_date` and `source_modified_at` for every DO it pushed, but has no index on `doc_no` | `models.py:818-841` |
| No by-DocNo door on our host: `/deliveryorder/{no}`, `?DocNo=` and `/deliveryorderbydocno` all return 404 (crew probe) | live host |
| A different AutoCount API (Postman) has `POST /api/DeliveryOrder/GetDeliveryOrder {"DocNo":[...]}`; whether our host has it is UNVERIFIED | `documentation/api/autocount/SL AutoCount API.postman_collection.json:10794` |

## 2. Decisions (grill; crew answered, owner calls marked)

- **D1 Read only.** The finder only issues GETs through the vendor client. It never builds a
  sink and never writes to AutoCount or to any feed, snapshot, ledger or cursor row. A kill
  test asserts the code path holds no POST/PUT/PATCH/DELETE call to the vendor (the optional
  by-DocNo door in D6 is a POST *query*; it gets its own allow-list entry and test).
- **D2 Generic doc-type registry** (§3). Each doc type is one `AcDocType` entry: paths, field
  names, number prefixes and the snapshot or feed it maps to. Adding Invoice, Cash Sale, SO, GRN
  or RMA means adding an entry, with no change to the search code. v1 registers
  `delivery_order` (live) and `goods_receive_note` (the feed doors already exist,
  `constants.py:19-20`). The others are listed in the design as "path to confirm".
- **D3 Search order** (§4): stored first (instant, zero vendor calls), then live. Live order:
  location hints, then by-LastModified from today back N days, then by-DocDate from today
  forward M days, stopping at the first hit.
- **D4 The current record always comes from a live read.** Stored rows are history, not the
  answer. Even when the stored search finds the doc, the live phase still runs so the page shows
  today's DocDate, LastModified and Cancelled. Stored hits give the live phase its first day to
  try, which usually makes it a single GET.
- **D5 Cache = location, not content.** `ac_doc_lookup_hint` (tenant, company, doc_type,
  doc_no_norm) -> (doc_key, doc_date, last_modified_day, found_at). The next lookup tries the
  hinted DocDate first: one GET, fresh data. If that misses (re-dated again), the full scan runs
  and the hint is replaced. Misses are not cached, because a doc created a minute later must be
  findable. This keeps "cache results" without ever showing a stale record.
- **D6 Optional by-DocNo door** per registry entry (`by_doc_no`), OFF by default. It is enabled
  only after someone confirms it works on the customer host (crew-ask #2). When enabled it is
  tried first, ahead of the day scan.
- **D7 Windows** (OWNER CALL, crew-ask #1): default LastModified back **7** days and DocDate
  forward **14** days (today..+14). Both are configurable per company, capped at 31 days each.
  The user can also enter "Around date" to scan +/-3 days around a date they remember.
- **D8 Runs as a background job** (`background_jobs` type `autocount_doc_lookup`, CLAUDE.md
  rule for new async work; eager in dev/tests). The worst case is 1 + 7 + 15 = 23 sequential
  GETs at the connection's own timeout, which is too long for one request. The page polls the
  job and shows "checked N of M days". It reuses `JobService.beat_progress` plus cooperative
  abort (the user can Stop). Re-attach: the same (company, type, number) while running returns
  the same job.
- **D9 Permission = `autocount.pull.read`** (existing key, same audience as the Pull page), so
  there is no new key and no grant sweep. Starting a live search is a vendor read, not a write.
- **D10 Placement**: new page `/autocount/find` ("Find document") in the AutoCount menu, in all
  three menu arrays with `module: 'autocount'` + `permission`. It is also a deep link from the
  snapshot detail page.
- **D11 Re-date is shown, not hidden.** The page compares every stored sighting's DocDate with
  the live DocDate. When they differ it shows a warning banner: "DocDate changed from 01/10/2026
  to 05/10/2026 - last modified by AIN on 01/10/2026 07:39. A pull for 01/10 will no longer
  return it." Each snapshot row in the history table shows "in range: yes/no" for today's
  DocDate.
- **D12 Calls are audited** through the existing `record_client_calls` activity path
  (`activity.py`, as in the snapshot build), so every vendor GET appears in the developer logs.

## 3. Registry (`modules/autocount/doc_lookup/registry.py`)

```python
@dataclass(frozen=True)
class ByDocNoDoor:                      # D6 - optional, off until verified per host
    method: Literal["GET", "POST"]
    path: str                           # e.g. "/api/DeliveryOrder/GetDeliveryOrder"
    body: Callable[[str], dict] | None  # e.g. lambda no: {"DocNo": [no]}
    param: str | None = None            # GET form: query param name

@dataclass(frozen=True)
class AcDocType:
    key: str                            # "delivery_order" - wire + registry key
    label: str                          # "Delivery order" (terminology key = key)
    feed: str | None                    # doc feed whose connection we read through
    by_doc_date_path: str               # "/deliveryorderbydocdate"
    by_doc_date_param: str = "DocDate"
    by_last_modified_path: str | None = None
    by_last_modified_param: str = "lastModified"
    doc_no_field: str = "DocNo"
    doc_key_field: str = "DocKey"
    doc_date_field: str = "DocDate"
    last_modified_field: str = "LastModified"
    last_modified_user_field: str = "LastModifiedUserID"
    cancelled_field: str = "Cancelled"  # "T" / "F"
    lines_field: str = "Details"
    doc_no_prefixes: tuple[str, ...] = ()   # auto-detect type from the number
    snapshot_entity_type: str | None = None # stored search: ac_pull_snapshot.entity_type
    ledger_feed: str | None = None          # stored search: ac_doc_feed_ledger.feed
    by_doc_no: ByDocNoDoor | None = None
    module: str = "autocount"

register_doc_type(AcDocType(
    key="delivery_order", label="Delivery order", feed="delivery_orders",
    by_doc_date_path="/deliveryorderbydocdate",
    by_last_modified_path="/deliveryorderbyLastModified",
    doc_no_prefixes=("PS", "DO"),
    snapshot_entity_type="delivery_orders", ledger_feed="delivery_orders",
))
register_doc_type(AcDocType(
    key="goods_receive_note", label="Goods received note", feed="goods_receive_notes",
    by_doc_date_path="/goodsreceivenotebydocdate",
    by_last_modified_path="/goodsreceivenotebyLastModified",
    doc_no_prefixes=("GRN", "GR"), ledger_feed="goods_receive_notes",
))
```

Planned entries (registered once the path is confirmed on the host; no code change):

| key | by DocDate path | by LastModified path | prefixes |
|---|---|---|---|
| `invoice` | `/invoicebydocdate` (to confirm) | `/invoicebyLastModified` (to confirm) | `IV`, `INV` |
| `cash_sale` | `/cashsalebydocdate` (to confirm) | ... | `CS` |
| `sales_order` | `/salesorderbydocdate` (to confirm) | ... | `SO` |
| `rma` | to confirm | ... | `RMA` |

- The vendor's day doors stay one source: `DocFeedVendor` gains a generic
  `day(path, param, day)`, and the two existing methods become thin callers of it. Constants
  and query strings are unchanged, and the pinned test `test_s14_doc_feed_clock_records.py`
  keeps passing byte for byte.
- `GET /autocount/doc-lookup/types` returns the registry (key, label, prefixes, hasLastModified,
  hasByDocNo), filtered by `is_visible(module)`, so the UI's type picker comes from the server.
- A drift test asserts every entry's `feed` / `snapshot_entity_type` / `ledger_feed` exists in
  `constants.ALL_FEEDS` / the snapshot entity list.

## 4. Search algorithm (`doc_lookup/service.py`)

Input: `companyId`, `docNo` (trimmed, 1..64 chars, no control chars; same rules as
`parse_do_scope`), optional `docType` (default = detect by prefix, else `delivery_order`),
optional `aroundDay`.

**Phase A - stored (synchronous, `GET /autocount/doc-lookup/stored`)**
1. Snapshot rows: `ac_pull_snapshot_row` JOIN `ac_pull_snapshot` WHERE tenant, company,
   entity_type, status ready, and `lower(payload_json->>'DocNo') = lower(:no)`. The new
   expression index `ix_ac_pull_snapshot_row_docno` (Postgres; `create_all` uses the SQLAlchemy
   JSON accessor so SQLite tests run the same query) keeps this fast. Each sighting returns
   snapshot id, created/extracted_at, its scope (`metadata.fromDay/toDay/docNo`), and the
   DocDate, LastModified and Cancelled it had then.
2. Ledger: `ac_doc_feed_ledger` WHERE tenant, company, feed, `lower(doc_no) = lower(:no)`, using
   the new index `ix_ac_doc_feed_ledger_docno`. It returns doc_date, source_modified_at,
   last_outcome, pushed_at and vanished_at.
3. Hint row (D5).

**Phase B - live (job, `POST /autocount/doc-lookup` -> 202 {jobId}; `GET /autocount/doc-lookup/{jobId}`)**
The plan is a list of steps, built and returned up front so the UI can show progress:
1. `by_doc_no` door, if enabled (D6).
2. Hint days, newest first, deduplicated: hint.doc_date, ledger.doc_date, the DocDate of the
   newest snapshot sighting, and `aroundDay` +/-3. Read with the by-DocDate door.
3. by-LastModified: today, then back to today-N (D7). This catches any re-date or edit in the
   window, which is how PS202610-0004 is found.
4. by-DocDate: today, then forward to today+M (D7). This catches forward-dated docs nobody has
   touched.
The job skips a step already covered by an earlier one (same door + same day) and stops at
the first record whose `doc_no_field` matches (casefold + trim, the existing `_doc_no_matches`).
If several copies share the DocKey, it picks the newest LastModified (`dedupe_latest`). On a
hit it upserts the hint row. A vendor error on one day is recorded on that step, and the scan
continues. The job FAILS only when every step failed (for example, no connection).

Result payload (the job's `result_json`, also the API shape):
```
{ docType, docNo, found: true|false,
  current: { docKey, docNo, docDate, lastModified, lastModifiedBy, cancelled, header{...}, lines[...] } | null,
  foundBy: { door: "by_last_modified"|"by_doc_date"|"by_doc_no", day: "2026-10-01" } | null,
  redated: { from: "2026-10-01", to: "2026-10-05", source: "snapshot"|"ledger" } | null,
  steps: [ { door, day, status: "hit"|"miss"|"error"|"skipped", count, error? } ],
  searched: { lastModifiedFrom, lastModifiedTo, docDateFrom, docDateTo } }
```
`header` = the vendor record without the lines field, verbatim (D18 of plan 14: never rename or
retype fields). The UI shows a curated set first (Debtor, Ref, Total) and every field in a
collapsible "All fields" table.

## 5. Data / migrations (module Alembic, `app_autocount`)

- `0024_autocount_doc_lookup`:
  - `ac_doc_lookup_hint` (tenant_id, company_id, doc_type, doc_no_norm PK; doc_key BigInteger,
    doc_date Date, last_modified UTCDateTime, found_at UTCDateTime).
  - `CREATE INDEX IF NOT EXISTS ix_ac_pull_snapshot_row_docno ON ac_pull_snapshot_row
    (tenant_id, company_id, lower(payload_json->>'DocNo'))` (Postgres only; the JSON column is
    `json`, so `->>` works).
  - `CREATE INDEX IF NOT EXISTS ix_ac_doc_feed_ledger_docno ON ac_doc_feed_ledger (tenant_id,
    company_id, feed, lower(doc_no))`.
- No backfill is needed: the indexes cover existing rows and the hint table starts empty by
  design.
- No storage keys. `doc_key` is a vendor integer named to match the ledger. The `*_key` drift
  test scans only core + omnichannel metadata (`tests/test_storage_migration_registry.py:241`),
  so it is unaffected.

## 6. API (module router `routers/doc_lookup.py`, prefix `/autocount/doc-lookup`)

| Route | Perm | Notes |
|---|---|---|
| `GET /types` | `autocount.pull.read` | registry |
| `GET /stored?companyId&docNo&docType` | `autocount.pull.read` | Phase A, sync, zero vendor calls |
| `POST /` `{companyId, docNo, docType?, aroundDay?}` | `autocount.pull.read` | 202 `{jobId}`; re-attach; 409 `NO_CONNECTION` when the company has no feed connection for the type |
| `GET /{jobId}` | `autocount.pull.read` | progress + result; tenant-scoped job lookup |
| `POST /{jobId}/stop` | `autocount.pull.read` | cooperative abort |
| `GET/PUT /settings?companyId` | read / `autocount.companies.manage` | windows N/M (D7) |

Router -> `DocLookupService` -> repositories (no SQL in the router). Every query is
tenant-scoped, and the company is loaded with `CompanyRepository.get(tenant_id, id)`. Rate
guard: at most 1 running lookup per (tenant, company), and a 10 s cooldown on the same number.

## 7. Frontend

`/autocount/find` page, layered UI -> `use-doc-lookup` hook -> `doc-lookup-service` (mock first,
then real) -> api-client. It reuses the existing shell and primitives: `Container`, page toolbar,
`SearchSelect` (company, doc type), `Input`, `Button`, `Card`, `Badge`/`StatusBadge`, `Alert`,
`DataGrid` for lines and history, `ClampedText`, `useDatetime` for every timestamp. It does NOT
use the Resource list, because the input is a single search, not a list of records. The history
table embeds the snapshot list's existing row link (`/autocount/pull/snapshots/{id}`).
Responsive: the form stacks on mobile, and the line and history tables scroll inside their own
`overflow-x-auto`.

## 8. Tests (red first)

Backend `tests/test_s17_doc_lookup.py`:
- Registry: entries are well formed, the drift test passes, and a fake `invoice` entry works end
  to end with no code change (genericity proof).
- Stored: snapshot sighting found case-insensitively; ledger sighting; cross-tenant /
  cross-company rows invisible.
- Live: hint day hits first (1 GET); the re-date case (fixture PS202610-0004: by-DocDate 01/10
  empty, by-LastModified 01/10 returns DocDate 05/10) -> found by `by_last_modified`, `redated`
  01/10 -> 05/10; forward-dated doc found by DocDate +k; not found -> `found:false` with the full
  step list; a vendor error on one day still finishes; stop mid-scan; re-attach.
- Kill test: the transport mock fails the test on any non-GET (and on POST unless the request
  matches the registry's `by_doc_no` door). It also asserts there are no writes to snapshot,
  ledger, feed or cursor tables (row counts and `updated_at` unchanged).
- Permissions: 403 without `autocount.pull.read`; 403 "Module not installed" when autocount is
  inactive.
Frontend: hook/service unit tests (mock), page render states (idle / stored-only / scanning /
found / redated / not found / error). E2E `e2e/autocount-doc-finder.spec.ts` against an
httpx-mock vendor via the existing http_source test transport, at 1280 and 375.

## 9. Out of scope / backlog

- Enabling the by-DocNo POST door per host (needs live verification) -> BL entry.
- Invoice / Cash Sale / SO / RMA entries -> registered after their paths are confirmed.
- Showing the doc's CRM-side state (what Sorento holds) - only the ledger's last outcome in v1.
