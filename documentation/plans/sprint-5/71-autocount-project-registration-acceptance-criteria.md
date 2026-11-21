# Plan 71 - AutoCount project registration routes (acceptance criteria)

Lane AUTOCOUNT-PROJREG-SPO-SS, the Shared Service half of slice 1. Partner CRM lane AUTOCOUNT-PROJREG-SPO
(sorento-crm PR #2648), whose plan Part A ("Contract between the CRM and the Shared Service") is the
contract these criteria fulfil. Owner rulings 21 Nov: projects are numbered only in the CRM and sent to
AutoCount; two CRM buttons, Register / Update in AutoCount; existing AutoCount registrations are linked
back through the read (exact ProjNo match); staff stop using AutoCount's own registration screen.

Test file: `service_backend/tests/test_autocount_project_registration.py` (the test names carry the ids).

| ID | Criterion |
|----|-----------|
| AC-71-01 | [BE][T] The admin switch `AUTOCOUNT_PROJECT_REGISTRATION_ENABLED` is OFF by default |
| AC-71-02 | [BE][T] Switch OFF: create, edit, read by ProjNo and read by date all answer `409 refused VENDOR_UNSUPPORTED` and make no AutoCount call |
| AC-71-03 | [BE][T] `GET /write-capabilities` lists `{op: create_doc, kind: project-registrations}` and `{op: edit_doc, kind: project-registrations}`: off with `VENDOR_UNSUPPORTED` while the switch is OFF, on (reason null) once it is ON; `WRITE_DISABLED` / `WRITE_NOT_ALLOWED` when the company has no usable write connection |
| AC-71-10 | [BE][T] A create without `Idempotency-Key` is `422 IDEMPOTENCY_KEY_REQUIRED`, no call |
| AC-71-11 | [BE][T] A create reads the ProjNo first, sends `POST /NewProjectReg` with the whole record (Part A fields mapped to AutoCount's names, `typeOfBuilding` -> `TypeofBuilding`, `date` as `YYYY-MM-DDT00:00:00`), reads it back by ProjNo and answers `200 done` with `projNo`, `operationId` and `registration` = AutoCount's record after the call; AutoCount's upper-casing is not a difference |
| AC-71-12 | [BE][T] Every wrapper call (the reads too) is one `ac_api_call_log` row carrying the book, `X-Request-ID`, `X-Acting-User-Id` / `-Name`, doc type `PROJREG`, the ProjNo and the operation; the write is one `ac_write_action` row with the same trace |
| AC-71-13 | [BE][T] A create on a ProjNo AutoCount already holds is `409 refused REGISTRATION_EXISTS` with `registration` = AutoCount's record; nothing is sent |
| AC-71-14 | [BE][T] Same key, same body: the stored answer comes back and nothing is sent |
| AC-71-15 | [BE][T] Same key, another body: `409 IDEMPOTENCY_CONFLICT`, nothing is sent |
| AC-71-16 | [BE][T] A create whose POST timed out but landed is read back and answers `done` (one POST) |
| AC-71-17 | [BE][T] A create whose POST timed out and did not land answers `202 pending_verification WRITE_TIMEOUT`; a same-key resend looks the ProjNo up BEFORE any re-send and, still absent, sends it once more and answers `done` |
| AC-71-18 | [BE][T] A create that landed but whose read-back failed answers `202 pending_verification`; the same-key resend finds it with the same fields and answers `done` with no second POST |
| AC-71-19 | [BE][T] AutoCount refusing the create is `409 refused VENDOR_REFUSED` with AutoCount's own reason (redacted, first line, capped); the refusal releases the key: the same key runs again after the cause is fixed |
| AC-71-20 | [BE][T] A field AutoCount holds differently after a create is a warning, not a failure: `200 done`, `warnings ["FIELD_CHANGED"]`, `changedFields [{field, sent, autocount}]` (caller's field names) |
| AC-71-21 | [BE][T] Body checks before any call: no `registration` / no or blank `registration.projNo` = `422 FIELD_REQUIRED`; a field outside the Part A list, a nested value, a malformed `date`, a top-level field other than `companyCode` / `registration` = `422 INVALID_REQUEST` |
| AC-71-22 | [BE][T] A key without the `write_back` scope is `403 SCOPE_REQUIRED`, no call |
| AC-71-23 | [BE][T] A write connection naming a live book (db1) is `403 WRITE_NOT_ALLOWED`, no call (db3 only in the test period) |
| AC-71-30 | [BE][T] An edit reads the ProjNo, sends `PUT /EditProjectRegbyProjNo` with the whole record (ProjNo in the body, no query), reads it back and answers `done` |
| AC-71-31 | [BE][T] An edit of a ProjNo AutoCount does not hold is `409 refused REGISTRATION_NOT_FOUND`, no PUT |
| AC-71-32 | [BE][T] An edit's `Idempotency-Key` is optional; an unclear PUT is judged by reading the record back (same fields = `done`) |
| AC-71-33 | [BE][T] An edit whose `registration.projNo` differs from the path is `422 INVALID_REQUEST` (the number is never renamed) |
| AC-71-40 | [BE][T] `GET /project-registrations/{projNo}?companyCode=` answers `200 done`, `found: true` and `registration` = AutoCount's record; nothing is written |
| AC-71-41 | [BE][T] The same read of a ProjNo AutoCount does not hold answers `200 done`, `found: false`, `registration: null` |
| AC-71-42 | [BE][T] `GET /project-registrations?companyCode=&date=YYYY-MM-DD` calls `GET /ProjectRegbyDate?Date=yyyymmdd` and answers `registrations` (the list); a malformed date is `422 INVALID_REQUEST` |
| AC-71-43 | [BE][T] Every wrapper call carries the ESB client's own User-Agent (`Foundryx-AutoCount-ESB/<version>`), never a library default |
| AC-71-44 | [BE][T] A create stores one `ac_write_operation` row (`op create_doc:PROJREG`, status = the outcome) |
| AC-71-45 | [BE][T] A pending create that was sent while the ProjNo was absent and landed with a field AutoCount did not keep is `done` + `FIELD_CHANGED` on the same-key resend (no second POST), and then locks |
| AC-71-45b | [BE][T] The resend of a create whose run died (not known whether it was sent) finding the ProjNo with OTHER fields is `409 REGISTRATION_EXISTS` with AutoCount's record; nothing sent |
| AC-71-46 | [BE][T] A bare 5xx on create is checked (read back), not assumed: absent = `pending_verification`, and the resend completes it |
| AC-71-47 | [BE][T] A field AutoCount holds differently after an edit is a `FIELD_CHANGED` warning on `done` |
| AC-71-48 | [BE][T] A write of a ProjNo while another write of the same ProjNo runs (another key) is `409 DOC_BUSY`, nothing sent; another ProjNo is not held |
| AC-71-49 | [BE][T] A crashed run (in progress for longer than the busy window) no longer holds the ProjNo |
| AC-71-52 | [BE][T] A keyless edit of a ProjNo with a write in flight is `409 DOC_BUSY`, nothing sent |
| AC-71-53 | [BE][T] The per-ProjNo lock number is in [2^62, 2^63): never a real DocKey; the same ProjNo (trimmed, any case) gives the same lock |
| AC-71-54 | [BE][T] AutoCount's refusal text never carries the connection's API key, in the answer or the stored operation |
| AC-71-55 | [BE][T] A ProjNo with quotes / markup, or a field with a control or invisible character, is `422 INVALID_REQUEST` before any call; line breaks and tabs pass |
| AC-71-56 | [BE][T] A ProjNo holding `/` reads and edits through the path routes (raw or `%2F`) |
| AC-71-57 | [BE][T] A non-2xx answer is judged by the read-back: a create that landed and then answered 500 with a reason is `done` |
| AC-71-58 | [BE][T] An edit AutoCount refused that changed nothing is `409 VENDOR_REFUSED` with AutoCount's reason |
| AC-71-59 | [BE][T] A lower-case ProjNo is found when AutoCount stores it upper-cased (one POST, `done`) |
| AC-71-60 | [BE][T] While another key's create of the ProjNo is `pending_verification`, a create is `409 DOC_BUSY` and nothing is sent |
| AC-71-61 | [BE][T] The action row survives an internal error (the answer's `actionId` exists, `INTERNAL_ERROR`) |
| AC-71-62 | [BE][T] No write is sent past the overall deadline (`409 DEADLINE_EXCEEDED`) |
| AC-71-63 | [BE][T] The by-date read takes `YYYY-MM-DD` only; `registration.date` takes `YYYY-MM-DD` or `YYYY-MM-DDT00:00:00` only |
| AC-71-64 | [BE][T] With the switch OFF a bad body still answers `409 VENDOR_UNSUPPORTED` |
| AC-71-65 | [BE][T] A keyless edit that ended `pending_verification` is sent again on the next press and answers `done` |
| AC-71-66 | [BE][T] A pending create that landed does not hold the ProjNo against an edit |
| AC-71-50 | [DOC] `71-autocount-project-registration-contract.md` documents the routes, bodies, answer, codes and the switch |
| AC-71-51 | [LIVE] db3 probe before the switch is turned on anywhere: create, edit, read and by-date read against db3 only (never db1 / db2), and whether `ProjectRegbyProjNo` answers `[]` or 404 for an unknown number (field names confirmed from a db1 record, 21 Nov) |
