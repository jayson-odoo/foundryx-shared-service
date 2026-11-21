# 71 - AutoCount project registration routes (Shared Service half, slice 1)

Lane AUTOCOUNT-PROJREG-SPO-SS. Partner CRM lane AUTOCOUNT-PROJREG-SPO (sorento-crm PR #2648, plan
`documentation/plans/autocount/PLAN-autocount-projreg-spo-21nov.md`; its Part A is the contract).
UAC: `71-autocount-project-registration-acceptance-criteria.md`. Contract:
`71-autocount-project-registration-contract.md`.

## Why

Owner rulings 21 Nov: projects are numbered only in the CRM (ProjNo `PPF` + yy + mm + 4 digits) and
sent to AutoCount; the CRM shows two buttons, Register and Update in AutoCount; registrations AutoCount
already holds are linked back by a person through the read (exact ProjNo); staff stop using AutoCount's
own registration screen. The Shared Service is the only thing that talks to AutoCount, so it carries the
four routes.

Live shape (owner, db1 GET, 21 Nov): `Status` always reads `Pending`; `SalesAgent` is the upper-case
short agent name; `TypeofBuilding`, `State`, `Mukim` are upper-case; `ProjectTitle` is multi-line (`\n`);
`Developer`, `Architect`, `MainContractor` are empty.

## Design

Backend only (no screen in SS: the CRM owns the buttons and dialogs). Reuses, never forks:

- `write_back/frame.py WriteFrame` - the write connection resolved with tenant_id, the db3 guard
  (`_resolve_write_base_url`, `guard.assert_test_company`), `_finish` / `_refuse`, the action row trace
  columns, `new_call_log`.
- `write_back/client.py AutoCountWriteClient` and `write_back/reader.py AutoCountDocReader` - the logged
  client and reader (`ac_api_call_log`); never the unlogged `http_source` sync transport. Two small
  additions: `set_user_agent` on both (the project registration calls send the ESB client's own
  User-Agent, `http_source/client.py USER_AGENT`), and `AutoCountDocReader.fetch_records` (a GET door that
  answers a list, a single object or nothing).
- `write_back/primitives.py is_business_refusal` / `vendor_message` - AutoCount's refusal text, redacted.
- `ac_write_operation` (`OperationRepository`) for the idempotency key; `ac_write_action` for the audit row.
- `routers/write_v1.py _frame` / `_status_of` / `_bad` - auth, scope, `Idempotency-Key`, `X-Request-ID`,
  acting user, company resolution, flat errors, the status mapping.
- `OperationService.capabilities` - the capability feed gains the two `project-registrations` entries.

New: `write_back/project_registration.py` (`ProjectRegistrationService`, the field table `FIELDS`, the
read-back comparison), `routers/project_registrations_v1.py` (manifest router, mounted at
`/api/v1/autocount`, public like `write_v1`), the setting `autocount_project_registration_enabled`
(`app/config.py`, default false, read per call), and `deps.get_project_registration_service`.

No new table and no migration: the operation and action rows carry `doc_type "PROJREG"`, `doc_key NULL`
(a NULL never trips the per-document busy index); the ProjNo sits in the operation's `snapshot_json` (used
for the same-ProjNo busy check) and in the call log's `doc_no`.

### Flows

- Create: switch -> company -> idempotency (replay / conflict / release / look-up) -> write connection +
  guard -> GET by ProjNo (exists = `REGISTRATION_EXISTS` with AutoCount's record) -> action row in_flight
  committed -> POST -> read back -> compare.
- Edit: same, but the GET must find the ProjNo (`REGISTRATION_NOT_FOUND` otherwise) and the write is the
  whole-record PUT; `Idempotency-Key` optional.
- Unclear (timeout, connection drop, bare 5xx, unreadable read-back): read the ProjNo; found = compared;
  else `pending_verification`. A same-key resend of a pending create reads first and never sends blind.
- Reads: switch -> company -> guard -> GET (logged); not found is `found: false`, not an error.

## Deferred / open

- AC-71-51 (live): a db3 probe of the four doors before the switch is turned on, including the three
  AutoCount field names the live shape did not show (`DistributorName`, `CustomerName`, `Date`) and
  whether `ProjectRegbyProjNo` answers `[]` or 404 for an unknown number (both are "not found" today).
  The cloud lane cannot reach db3; crew runs it.
- The switch is a deployment setting (env), like the write book list; a per-company switch is not built
  (the CRM's own admin switch decides who sees the buttons).
