# Plan 73: Link PO keeps the PO line Further Description

Lane PO-LINK-KEEP-FURTHER-DESC, branch `crew/po-link-keep-further-desc`, base main bc91fcc9.
Root cause: crew `state/files/po-link-further-desc/root-cause.md` (23 Nov). Crew rulings s1 + s2 (23 Nov).

## Problem
Users report the original PO line's Further Description (FD, RTF with pictures) is gone after Link PO.
Every PO/SPO write copies rows through `payloads._row_fields` (ROW_KEYS, `write_back/payloads.py:39`), which has
no `FurtherDescription`, and hapi's PO GET never returns FD (`UNREADABLE_ROW_KEYS`, `payloads.py:386`).
- Delete + re-add paths lose FD for sure: whole-qty `build_link` (:295-300), `build_link_doc` rest 0 (:819-822,
  `operations._doc_new_row` :2018), `build_row_replace` (:780, relink / unlink / spo ops), `build_unlink_row` (:509),
  `build_add_line` recover (:756, operations.py:1266), `build_unlink_merge` deleted row (:832).
- Re-sent kept rows send no FD: `build_link` edited (:301), `build_relocate` (:307), `build_restore_transfer_row`
  (:494), `build_edit` (:720, edit_doc / cut / move / restore / recover), `build_link_doc` kept (:823),
  `build_unlink_merge` raised (:839). Whether AutoCount now blanks FD on such a PUT is UNVERIFIED (vendor FD fix 23 Nov).

## Rulings (crew s1, s2)
- R1 A line-notes reader behind ONE interface: `notes(kind, doc) -> {DtlKey: FD}` or "unknown".
  (1) SQL impl: optional per-company read-only `line_notes_connection_id` (a `sql_database` connection),
  `SELECT DtlKey, FurtherDescription FROM PODTL WHERE DocKey = :k`; NOT an entity source, so
  `guard.assert_test_company` is unchanged. (2) hapi impl: takes FD from the PO GET rows when the vendor adds the
  key (every row carries it). Tests use a fake.
- R2 Fail closed: a write that re-sends or re-adds an existing row whose FD is unknown is refused before any PUT,
  code `LINE_NOTES_UNKNOWN`, plain reason "The line notes of this purchase order could not be read, so the change
  was not made. Try again later." Nothing is sent; the retry rule (refusal releases) holds.
- R3 Never flip PO/SPO: `keep_shipping_po` stays on every body.
- R4 Vendor note in the PR body: please add `FurtherDescription` to the PO GET rows.
- R5 db3 proof = owner screen check (no db3 SQL route exists, crew `db3-sql-route.md`); never db1/db2.

## Design
- D1 Enrich at the read choke point: the frame's `_reader_for` returns a reader wrapper; for PO / SPO documents
  (`get_document`, `get_by_doc_no`) it sets `row["FurtherDescription"]` on every row from the line-notes reader.
  Every builder, snapshot and read-back then sees FD. Unknown = key absent.
- D2 `FurtherDescription` joins the row copy (`_row_fields` / `_vendor_line` / `_doc_new_row` / unlink copy), so it is
  sent unchanged with every re-sent row and carried onto every re-added row. Read-back compare keeps ignoring it
  (`UNREADABLE_ROW_KEYS`).
- D3 One guard `payloads.require_line_notes(rows)`: any row we re-send or copy without the key -> `WriteRefusal
  ("LINE_NOTES_UNKNOWN")`. Deleted-only rows ("D") need no FD.
- D4 The S/O note is appended after the existing FD (`with_link_note`, `transfer_restore`): RTF FD -> the note
  paragraph is inserted before the final `}`; plain FD -> `autocount_rtf(fd + "\n" + note)`; empty FD -> today's
  `autocount_rtf(note)`. Relink appends the new note; unlink keeps FD as is (no new note). Idempotent: a FD that
  already ends with the same note is not appended again (restore PUT re-sends the merged value).
- D5 Company column `line_notes_connection_id` (module migration 0049 + crew SQL), set through the existing
  write-connection admin route shape, same-tenant `sql_database` connection resolved WITH tenant_id.

## Tests (tester first, red)
Pure builders: each path above, FD (text + `{\pict ...}` hex) byte-identical on the re-sent / re-added row; note
appended after FD; missing FD -> LINE_NOTES_UNKNOWN and zero PUTs. Wrapper: fake notes reader enriches PO/SPO
only, SO untouched. SQL impl: tenant-scoped connection resolve, unset = unknown. Kill tests by the reviewer.

## Open PRs needing the same rule
#324 (unlink returns qty to source: re-sends the source row, deletes the tied row), #325 (SPO move/split:
FOLLOW_KEPT_FIELDS from LINE_KEYS), #326 (resume re-sends restore rows). Crew note on each after this merges.
