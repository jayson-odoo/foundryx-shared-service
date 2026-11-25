# Plan 73: Link PO writes read-modify-write from the AutoCount database

Lane PO-LINK-KEEP-FURTHER-DESC, branch `crew/po-link-keep-further-desc`, base main bc91fcc9.
Root cause: crew `state/files/po-link-further-desc/root-cause.md` (23 Nov). Crew rulings s1 + s2 (23 Nov), round 2 (24 Nov).

## Problem
Users report the original PO line's Further Description (FD, RTF with pictures) is gone after Link PO, and header fields
such as Remark4 are blanked. hapi's PO GET never returns `FurtherDescription` and returns Remark2-4 as a copy of Remark1
(crew `hapi-vendor-bugs.md` s1), so any body built from the bare GET sends "" for values AutoCount stores.
Every PO / SPO write is affected: Link PO (whole and part qty, document and row batches), unlink, unlink merge, relink,
relocate, restore, edit (also header-only), add line, delete line, and the recover of a failed operation.

## Rule (owner, round 2)
Every PO / SPO write is read-modify-write from the AutoCount database: the header fields and every existing line's fields
(including FurtherDescription) are sent back exactly as stored; never "" for a field we did not read. hapi's own FD is
never trusted alone.

## Rulings
- R1 One reader seam `DocDbSource.read(kind, doc) -> {"header": {}, "rows": {DtlKey: {}}} | None`. The implementation
  `SqlDocDb` runs two bound, read-only, time-boxed SELECTs on the company's optional `line_notes_connection_id` (a
  same-tenant `sql_database` connection, not an entity source, so `guard.assert_test_company` is unchanged): the PO header
  (`DocKey` and `DocNo` bound, exactly one row) and the PODTL rows (`DocKey` bound, DtlKey set equal to the document's).
  `SELECT *`, then the columns are whitelisted after the read (header whitelist without DocKey / DocNo; row whitelist + FD;
  an explicit list could fail every read on a name the database lacks). Values are
  normalised to the hapi wire shape (Decimal to float, datetime to `YYYY-MM-DDTHH:MM:SS`, NULL omitted, a NULL FD is an
  empty note). Any error or mismatch is unknown (None); no value or credential is logged.
- R1a Source choice: the explicit `line_notes_connection_id` wins; when unset the company's own source connection
  (`connection_id`) is used if it is an active same-tenant `sql_database` connection; anything else is unread (R2).
- R2 Fail closed: when the database cannot be read (no source, or the read answers None) NO PO / SPO PUT is sent, whatever
  its shape (a header-only edit, add line and delete line included). Code `AUTOCOUNT_DB_UNREAD`, plain reason "The purchase
  order could not be read from AutoCount, so the change was not made. Try again." The refusal is retry-safe and nothing is
  locked. Exception: the recover of a failed operation re-adds a row the operation already deleted; refusing would strand
  it, so it proceeds (a warning with the code only is logged).
- R3 Never flip PO / SPO: `keep_shipping_po` stays on every body.
- R4a (owner 25 Nov) A split's new linked line carries ONLY the S/O note (`autocount_rtf(note)`), also in the restore PUT; the
  original that keeps a rest keeps its FD byte for byte. Only when the original goes away (rest 0: whole link, a fully taken
  batch row) the FIRST new row carries the original FD + note (R4); later new rows of it are note only. One helper decides
  it (`payloads.inherits_original_note`). Relink, unlink, relocate and edit are unchanged.
- R4 The S/O link note stays in the FurtherDescription of the NEW linked row, appended after the stored FD (RTF: before
  the final `}`; plain text: new line; empty: AutoCount's wrapper). Idempotent. A relink appends the new note; unlink keeps
  the FD as is.
- R5 Vendor note in the PR body: please make the PO GET return the stored header (Remark2-4) and `FurtherDescription`.
- R6 db3 proof = owner screen check (no db3 SQL route exists, crew `db3-sql-route.md`); never db1 / db2. AutoCount UDF_*
  columns are out of scope until a db3 test proves hapi's PUT accepts them.

## Design
- D1 `NotesReader` wraps the frame's reader (`_reader_for`): for PO / SPO documents (`get_document`, `get_by_doc_no`) it
  lays the stored header values and each row's stored values + FD over the GET (`attach_db_doc`). When the database was
  not read it drops any FD the GET carried and marks the document (`_dbUnread`, never sent). Every builder, snapshot and
  read-back then sees stored values.
- D2 Builders copy the document header and every re-sent row as read, FD included (`_row_fields` / `_vendor_line` /
  `_doc_new_row` / unlink copy). Read-back compares keep ignoring FD and the header fields the vendor mirrors
  (`UNREADABLE_ROW_KEYS`, existing collateral tolerance).
- D3 Guards: `require_line_notes(rows)` (a re-sent or copied row without FD) and `require_db_read(doc)` (called from
  `keep_shipping_po`, so every PO / SPO body) both raise `AUTOCOUNT_DB_UNREAD`. Deleted-only rows need no FD.
- D4 A restore value that is only a note in AutoCount's wrapper is merged after the row's own FD, never replaces it. After
  a landed link PUT the restore takes the new row's FD from the row PUT 1 sent when the read-back has none; a refusal
  there ends as a clean mismatch, never INTERNAL_ERROR.
- D5 Company column `line_notes_connection_id` (module migration 0049 + crew SQL), set through the operator CLI
  in the app (plan 74, `CompanyService.set_line_notes_connection`; the operator CLI `write_back.admin set-line-notes-connection` calls the same function), same-tenant `sql_database` connection resolved WITH tenant_id.

## Tests
Builders: stored header and FD on every body; an unread row or document refuses before any PUT; header-only edit, add
line, delete line refused with zero PUTs; SO / QT unaffected. Reader: overlay on PO / SPO only. `SqlDocDb`: tenant-scoped
resolve, exact row set, DocNo bound, explicit columns, case-insensitive columns, error = None. Operations: refusal before
any PUT, restore after a landed PUT never INTERNAL_ERROR, resume keeps FD. Kill tests by the reviewer.

## Open PRs needing the same rule
#324 (unlink returns qty to source: re-sends the source row, deletes the tied row), #325 (SPO move/split:
FOLLOW_KEPT_FIELDS from LINE_KEYS), #326 (resume re-sends restore rows, merged here). Crew note on each after this merges.

## B2 release guard
Plan 73 refuses every PO / SPO write whose line notes database cannot be read, so a release must not go live while a
write-enabled company has none. `python -m modules.autocount.write_back.admin check-line-notes` resolves, for every active
company with a write connection (all tenants), the source exactly as a write does (explicit connection, else the company's
own `sql_database` source, resolved with tenant_id) and runs one read-only probe (`SELECT TOP 1` on the PO and PODTL tables)
through it. It prints one line per company (id and `OK`, `NO_CONNECTION` or `READ_FAILED`; never a host, database name,
value or credential) and exits 1 unless every company is OK (0 also when no company can write). `scripts/blue_green_deploy.sh`
runs it in the NEW backend container after the health wait and before the Caddy swap; on failure the new color is stopped and
the old color keeps serving.

## Legacy mode (crew ruling s20)
A write never refuses before a line notes connection is set. When no source resolves (no explicit
`line_notes_connection_id`, and the company's own source is not an active same-tenant `sql_database` connection) the
document is read in legacy mode: no DB read, no `AUTOCOUNT_DB_UNREAD`, kept and re-sent rows carry no FurtherDescription,
the S/O note on the new linked row is AutoCount's default wrapper holding the note (as before plan 73), and the header
omits every text field the read returned blank (never `""`). No `STORED_FIELDS_CHANGED` check. Only a resolved source whose
read fails is a refusal (DB mode). `check-line-notes` prints `NO_CONNECTION` for a company in legacy mode but exits 0; it
exits 1 only on `READ_FAILED`.

