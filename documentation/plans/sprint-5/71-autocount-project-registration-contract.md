# AutoCount project registration gateway (cross-repo contract)

Status: built 21 Nov 2026, lane AUTOCOUNT-PROJREG-SPO-SS, plan `71-autocount-project-registration.md`,
UAC `71-autocount-project-registration-acceptance-criteria.md`. Fulfils the CRM plan's Part A ("Contract
between the CRM and the Shared Service", sorento-crm PR #2648). Extends the write gateway contract
`57-autocount-write-qtso-contract.md`: auth (`X-API-Key`, `write_back` scope), company resolution
(`companyCode`), `Idempotency-Key` rules (its section 2), `X-Request-ID` and the acting-user headers
(its section 2a), the flat error body, `no-store` and the status mapping (its section 4) are unchanged and
not repeated here.

## 1. Routes

| Route | Wrapper door | Does |
|---|---|---|
| `POST /api/v1/autocount/project-registrations` | `POST /NewProjectReg` | Register a project (`Idempotency-Key` required) |
| `PATCH /api/v1/autocount/project-registrations/{projNo}` | `PUT /EditProjectRegbyProjNo` | Replace the whole record (`Idempotency-Key` optional) |
| `GET /api/v1/autocount/project-registrations/{projNo}?companyCode=` | `GET /ProjectRegbyProjNo?ProjNo=` | Read one registration (exact ProjNo) |
| `GET /api/v1/autocount/project-registrations?companyCode=&date=YYYY-MM-DD` | `GET /ProjectRegbyDate?Date=yyyymmdd` | The registrations of one day (for linking back) |

Every route reads and writes through the company's write connection only: the write guard (db3 in the
test period, never db1 / db2), the test-company check, and the logged client and reader (one
`ac_api_call_log` row per AutoCount call, reads included), with the ESB client's User-Agent.

## 2. The switch

`AUTOCOUNT_PROJECT_REGISTRATION_ENABLED` (default `false`). Off: every route above answers
`409 refused VENDOR_UNSUPPORTED` and calls nothing. `GET /write-capabilities` carries one entry per
primitive for kind `project-registrations`:

```json
{ "op": "create_doc", "kind": "project-registrations", "enabled": false, "reasonCode": "VENDOR_UNSUPPORTED" }
{ "op": "edit_doc",   "kind": "project-registrations", "enabled": false, "reasonCode": "VENDOR_UNSUPPORTED" }
```

`WRITE_DISABLED` / `WRITE_NOT_ALLOWED` take precedence when the company has no usable write connection.

## 3. Body (create and edit)

```json
{ "companyCode": "SRT",
  "registration": { "projNo": "PPF26110001", "projectTitle": "line 1\nline 2", "distributorName": "...",
                    "salesAgent": "...", "customerName": "...", "date": "2026-11-21",
                    "typeOfBuilding": "...", "state": "...", "mukim": "...", "developer": "",
                    "architect": "", "mainContractor": "", "status": "Pending" } }
```

The whole record every time; SS never merges fields. Field names map to AutoCount's (keys confirmed
from a db1 record, 21 Nov: the same keys as the `NewProjectReg` body):

| caller | AutoCount |
|---|---|
| `projNo` | `ProjNo` |
| `projectTitle` | `ProjectTitle` |
| `distributorName` | `DistributorName` |
| `salesAgent` | `SalesAgent` |
| `customerName` | `CustomerName` |
| `date` | `Date`, sent as `YYYY-MM-DDT00:00:00` |
| `typeOfBuilding` | `TypeofBuilding` |
| `state` | `State` |
| `mukim` | `Mukim` |
| `developer` | `Developer` |
| `architect` | `Architect` |
| `mainContractor` | `MainContractor` |
| `status` | `Status` |

Checks, before any AutoCount call: `registration` missing = `422 FIELD_REQUIRED` (`FIELD_REQUIRED:
registration`); on a create, `registration.projNo` missing or blank = `422 FIELD_REQUIRED`; on an edit the
ProjNo is the path's (it may hold a `/`, sent as is or as `%2F`), and a `registration.projNo` that
differs is `422 INVALID_REQUEST`. A ProjNo is 1..64 letters, digits and `/ _ . -`, starting with a letter
or digit. Any other name inside `registration`, any top-level field other than `companyCode` /
`registration`, a value that is not text / number / true / false / null, text longer than 4000
characters, text holding a control or invisible character (line breaks and tabs are kept), or a `date`
that is not `YYYY-MM-DD` = `422 INVALID_REQUEST`. Value rules (length, a
known agent) are AutoCount's: it refuses, SS passes its reason on (section 5).

## 4. Answer

```json
{ "operationId": "uuid or null", "actionId": "uuid or null",
  "outcome": "done | refused | pending_verification | vendor_error",
  "errorCode": null, "message": "", "warnings": [],
  "projNo": "PPF26110001",
  "registration": { "ProjNo": "PPF26110001", "ProjectTitle": "...", "Status": "Pending", "...": "..." },
  "changedFields": [] }
```

`registration` is AutoCount's record as read back after the call (AutoCount's own field names), or, on
`REGISTRATION_EXISTS`, the record AutoCount already holds. `operationId` is set on a create and on an edit
sent with an `Idempotency-Key`.

Every create and edit is read back by ProjNo and compared with what was sent: text trimmed per line,
case-insensitive, `\r\n` as `\n`; a number by value; the date by its day. A difference is a warning,
never a failure: `done`, `warnings: ["FIELD_CHANGED"]`, `message` names the fields, and
`changedFields: [{"field": "mukim", "sent": "...", "autocount": "..."}]` carries AutoCount's value.

The read by ProjNo answers `200 done` with `found: true` and `registration`, or `found: false` and
`registration: null`. The read by date answers `200 done` with `registrations: [...]` (AutoCount's
records, possibly empty).

## 5. Outcomes and codes

| outcome | errorCode | HTTP | when |
|---|---|---|---|
| `done` | null (warning `FIELD_CHANGED` possible) | 200 | written and read back, or a read |
| `refused` | `REGISTRATION_EXISTS` | 409 | create on a ProjNo AutoCount holds (`registration` = its record); also a pending create whose resend finds the ProjNo with other fields |
| `refused` | `REGISTRATION_NOT_FOUND` | 409 | edit of a ProjNo AutoCount does not hold |
| `refused` | `VENDOR_REFUSED` | 409 | AutoCount refused the write with a reason (in `message`, redacted, the connection's API key masked); nothing applied |
| `refused` | `READ_FAILED`, `REGISTRATION_AMBIGUOUS` | 409 | the first read failed, or answered more than one record for the ProjNo; nothing sent |
| `refused` | `VENDOR_UNSUPPORTED` | 409 | the switch is off |
| `refused` | `IDEMPOTENCY_CONFLICT`, `OPERATION_IN_PROGRESS`, `DOC_BUSY` | 409 | same key with another body; same key still running; another write of the same ProjNo still running (any key, or none; a run that crashed stops holding it after 10 minutes) |
| `refused` | `WRITE_DISABLED`, `WRITE_NOT_ALLOWED`, `WRITE_COMPANY_NOT_TEST` | 403 / 409 | no usable write connection / not the test book / the company is not a test book |
| `pending_verification` | `WRITE_TIMEOUT`, `WRITE_CONNECT`, `VENDOR_ERROR` (bare 5xx), `READ_FAILED`, `REGISTRATION_NOT_FOUND`, `INTERNAL_ERROR` | 202 | the write may or may not have landed and the read-back could not settle it |
| `vendor_error` | `VENDOR_ERROR` | 502 | a bare 4xx with no reason; nothing applied |

Retry rule (owner, 11 Nov): a refusal and a `vendor_error` release the key (the same key runs again);
only `done` locks it (a same-key resend returns the stored answer). A `pending_verification` create is
never sent blind: a same-key resend first reads the ProjNo: found with the same fields = `done`; found with
other fields = `REGISTRATION_EXISTS`; absent = sent again. A pending edit is simply sent again (a
whole-record PUT is safe to repeat) and judged by its read-back.

## 6. Correlation

As contract 57 section 8: `X-Request-ID` (else the `Idempotency-Key`) and the acting-user headers are
stored on every `ac_api_call_log` row and on the `ac_write_action` row, with doc type `PROJREG` and the
ProjNo as the document number.
