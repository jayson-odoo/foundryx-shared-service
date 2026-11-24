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
  Explicit column lists built from code constants (header whitelist without DocKey / DocNo; row whitelist + FD). Values are
  normalised to the hapi wire shape (Decimal to float, datetime to `YYYY-MM-DDTHH:MM:SS`, NULL omitted, a NULL FD is an
  empty note). Any error or mismatch is unknown (None); no value or credential is logged.
- R2 Fail closed: when the database cannot be read (no source, or the read answers None) NO PO / SPO PUT is sent, whatever
  its shape (a header-only edit, add line and delete line included). Code `AUTOCOUNT_DB_UNREAD`, plain reason "The purchase
  order could not be read from AutoCount, so the change was not made. Try again." The refusal is retry-safe and nothing is
  locked. Exception: the recover of a failed operation re-adds a row the operation already deleted; refusing would strand
  it, so it proceeds (a warning with the code only is logged).
- R3 Never flip PO / SPO: `keep_shipping_po` stays on every body.
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
  (`write_back.admin set-line-notes-connection`), same-tenant `sql_database` connection resolved WITH tenant_id.

## Tests
Builders: stored header and FD on every body; an unread row or document refuses before any PUT; header-only edit, add
line, delete line refused with zero PUTs; SO / QT unaffected. Reader: overlay on PO / SPO only. `SqlDocDb`: tenant-scoped
resolve, exact row set, DocNo bound, explicit columns, case-insensitive columns, error = None. Operations: refusal before
any PUT, restore after a landed PUT never INTERNAL_ERROR, resume keeps FD. Kill tests by the reviewer.

## Open PRs needing the same rule
#324 (unlink returns qty to source: re-sends the source row, deletes the tied row), #325 (SPO move/split:
FOLLOW_KEPT_FIELDS from LINE_KEYS), #326 (resume re-sends restore rows, merged here). Crew note on each after this merges.
