# Plan 65: AutoCount Link PO restore + Resume repair (lane AUTOCOUNT-LINK-RESTORE)

Status: PLAN (16 Nov 2026). Size M, LEAD pattern. UAC: `65-autocount-link-restore-acceptance-criteria.md`.
Branch `crew/autocount-link-restore` off origin/main ddb53cbe. Public repo: no customer names, prices or keys.

## 1. Incident (first live Link PO, 16 Nov)

One `link_batch` (plan 62) on a live PO: the link PUT landed (old row cut by 1, one new row linked to the SO
row), the read-back verify said MISMATCH, so the operation went `needs_attention` and the restore PUT never ran.
The new row was left as AutoCount resets a new SO-linked row (F5): no unit price, no delivery date, the
book's default location, and no further-description note.

Code facts (ddb53cbe):
- `verify_link_batch` (`payloads.py:842-871`) ends with `_drifted` over the header and every other row
  (`payloads.py:725-740`, fields `:397-398`). It has no tolerance for AutoCount-side drift.
  `verify_edit` forgives one drift only: Remark2..4 mirrored from a Remark1 the edit changed
  (`_remark_mirror`, `payloads.py:772-783`). Every 11-12 Nov db3 batch run used blank remarks
  (`documentation/integrations/autocount/test-report-2026-11-11-po-link-batch.md`), so remark drift on a
  link PUT was never exercised.
- The restore values come from `transfer_restore(snap["row"], location)` (`payloads.py:294-303`):
  location = SO row's, unit price AND delivery date = the OLD PO ROW's. No note: FurtherDescription is in no
  write_back list (`ROW_KEYS` `payloads.py:37-41`, `EDIT_LINE_KEYS` `payloads.py:387`; `build_edit` refuses
  any other key `FIELD_NOT_EDITABLE` `payloads.py:556-557`).
- The hapi PO and SO reads carry no `FurtherDescription` key (db3 read 16 Nov, call log
  `/PurchaseOrderbydocno`, `/SalesOrderbydocno`; header and row key lists in the lane evidence).
- Resume (`operations.py:348-383` -> `_resume_batch` `:1333-1357`) re-reads the PO and, when the new rows are
  there, goes straight to `_batch_done` (`:1308-1331`): no re-check of the kept row, the deletion or other
  rows, then the same (wrong) restore.
- Unlink (`operations.py:122`) is guarded by `_check_not_busy` (`:583-594`): standalone actions, young
  `pending_verification` ops, other `in_progress` ops. A `needs_attention` link on the same row does not
  hold it, so an unlink of the half-restored row sends live PUTs (root-cause report section 3).

## 2. Probes on db3 (before code; the db3 live repro script, also the red proof of the live path)

All through SS's logged client/reader (every call in `ac_api_call_log`), against the db3 test book only
(`guard.TEST_BOOKS`), on own `FXT-<date><letter>-` documents.
- P1 (incident shape): test SO with one row at a sub-location with a delivery date; test PO whose header
  carries four DIFFERENT non-empty remarks and a description, several rows, the source row with a unit price,
  a discount and a delivery date. Run `link_batch` qty 1 through `OperationService` on current code. Record
  the outcome, `error_code`, and every field `_drifted` names (before_json vs after_json of step `link`).
  Expected on ddb53cbe: `needs_attention` + the failing code. This names the exact AutoCount-side drift.
- P2 (restore fields): on the new linked row, which of Location / UnitPrice / DeliveryDate / Discount /
  FOCQty survive the link PUT and which a second edit PUT can set (F5 covered the first three only).
- P3 (note): does an edit PUT accept `FurtherDescription` on a row (200, row kept, link kept)? The read shape
  has no such key, so landing can only be confirmed outside the API (AutoCount screen on db3) or by a vendor
  read door. Result decides D4.
- P4 (repair): link, then stop before the restore (the half-filled state), set the op `needs_attention`, then
  Resume on the fixed code: one restore PUT on the linked row only, verified, op DONE.

## 3. Decisions

- D1 Verify tolerance: one shared helper names the AutoCount-side drift P1 proves (expected: Remark2..4
  re-written from Remark1 by the vendor wrapper on an edit PUT), used by `verify_link_batch`, `verify_edit`
  (the restore step) and the Resume re-check. Nothing broader: any other header or row drift is still
  `COLLATERAL_CHANGE`. If P1 shows the remarks are LOST (overwritten with Remark1 on a PO where they
  differ), that is real data loss on every PO edit: the lane asks crew before tolerating it.
- D2 Restore values for a new SO-linked row (one shared function, used by the first run, Resume and the
  row operations' relink restore where the same rule applies):
  Location = SO row's location; UnitPrice = old PO row's; DeliveryDate = the SO ROW's delivery date
  (owner ruling 16 Nov; blank when the SO row has none, never borrowed from the PO row);
  Discount / FOCQty per P2 and crew's answer (Q2); FurtherDescription = the note (D4).
  The SO row's date and the note sources are kept in the operation snapshot (`links[]`) at link time, so
  Resume needs no guess; an older snapshot without them re-reads the SO (bydocno, logged).
- D3 Restore verified: the restore PUT's read-back must show every restored field (verify_edit with D1's
  tolerance). A restore that did not land (vendor error, mismatch, deadline) leaves the operation
  `needs_attention` (resumable), not DONE-with-warnings: owner rule "every failed write can be retried"; Resume
  re-runs only the restore.
- D4 Note: `FurtherDescription` added to the edit row whitelist for the restore only (not to the public edit
  door). Text "**<CUSTOMER>/<PROJECT> S/O: <SO DocNo> DD: <dd/mm/yyyy>" (owner's hand format). Field
  sources: crew ask Q1 (recommendation: CUSTOMER = SO DebtorName, PROJECT = SO Ref, SO number = the SO's
  DocNo as AutoCount holds it, DD = the SO row's delivery date). The note cannot be read back through hapi
  (P3): verify covers every other restored field; the note's landing is shown once on the db3 screen and
  recorded in the evidence.
- D5 Resume repair (batch): (1) re-judge the stored link PUT (step `link` before_json vs after_json) with
  D1 (pure, no call): still MISMATCH -> stays `needs_attention`, no PUT; (2) fresh read: the kept row at its
  expected qty (or gone when all taken) and one new row per link, nothing else linked to the batch SO rows ->
  else `needs_attention`, no PUT; (3) restore PUT (D2) on the new rows only, verified (D3); (4) DONE, staged,
  link index refreshed. Never re-sends the link PUT. A stored link step with no read-back (timeout) compares
  its before_json with the fresh read instead.
- D6 Unlink / relink / delete line refused (`ROW_NEEDS_ATTENTION`, nothing sent) on a PO row that an
  unresolved (`needs_attention` / `pending_verification`) link operation covers: its source row or a new row
  linked to one of its SO rows. Evidence: root-cause report section 3 (unlink of a half-restored row = up to 3
  live PUTs, PO a unit short). After D5, Resume is the repair; the unlink is not needed. Other rows of the PO
  stay writable (owner: no pause of Link PO). The CRM hides the action on the matching code (cross-repo note).
- D7 Logging and books: no new vendor door; every call through the logged client/reader; tests and scripts
  db3 only; db1 writes only from the production deploy (unchanged guard).
- D8 Reuse (owner 12 Nov): `transfer_restore` / `transfer_row_drift` / `_move_rows` stay the one restore path
  (extended, not copied); `verify_link_batch` is reused by Resume; `_check_not_busy` gets the D6 row check.

## 4. Slices

- S0 (lead): plan + UAC; P1-P3 probes via the tester's db3 script; crew ask Q1-Q2.
- S1 red tests (tester): unit tests per UAC (verify tolerance, restore values, note text, Resume repair,
  unlink refusal), fixtures shaped like the incident (masked); the db3 live script (`runner.py --suite
  restore`, cases R00..Rnn) red on current code for P1 and P4.
- S2 code (coder): D1-D6 until S1 is green; no edits to the tester's assertions without lead sign-off.
- S3 kill proof, reviewer (Opus) + security glance, db3 evidence table (no customer data), PR.
- S4 release by crew; then the owner presses Resume on the db1 operation, only after crew says so.

## 5. Standing rules that apply

"Every failed write ... can be retried" (D3, D5); "Features that write to the ERP ... every ERP call is logged"
(D7); "Reuse functions" (D8); "A value that cannot be worked out shows '-' / never borrowed" (D2 blank SO
date stays blank); "Plain business words only" (refusal codes map to plain CRM wording, cross-repo); "No
automatic joining" (rows matched by FromSODtlKey + qty only).

## 6. Open

- Q1 note field sources (crew ask). Q2 Discount / FOCQty on the linked row (crew ask after P2).
- CRM (sorento_crm, cross-repo): hide Unlink on `ROW_NEEDS_ATTENTION`; Resume wording unchanged.
