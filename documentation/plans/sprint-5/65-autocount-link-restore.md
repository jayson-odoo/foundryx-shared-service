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

### Probe results (db3, 16 Nov, runs FXT-1116A..F, lane DB call log)

- P1: hapi rewrites PO Remark2..4 to Remark1 on EVERY create and edit PUT (Remark1 unchanged, omitted, blank
  or changed: same). A PO with different remarks cannot be built through the API, so the db1 mismatch cannot be
  replayed live; on API-made POs the incident-shaped link verifies DONE (drift list empty). The db1 PO's
  remarks were hand-set: the link PUT replaced Remark2..4 with Remark1 (the expected COLLATERAL_CHANGE; the
  owner confirms with query C of the root-cause report). Description sticks on edit.
- P2: on the new linked row the link PUT's Location, UnitPrice, DeliveryDate AND Discount are reset; a second
  edit PUT sets all four. FOCQty cannot be written through hapi at all (create, edit, second PUT: reads 0).
- P3: an edit PUT with FurtherDescription answers 200, keeps the row and its link; reads never return it.
- P4: the half-filled state is built by the live suite's case R04 (the real link, halted where the incident
  stopped): new row HQ / price 0 / no date, op `needs_attention`. Kept op for the post-fix Resume:
  `d146c832-907e-4040-829b-2308520dd094` (lane DB). Resume on ddb53cbe: 1 PUT, DONE, old PO row's date, no note.
- Live red already visible: R02 on ddb53cbe restored the PO row's date, not the SO row's (AC-65-05).

### Phase 1 contract (names the tester's tests and the coder share)

- `payloads.so_link_note(so: Doc, so_row: Doc) -> str`: the plain note text (D4).
- `payloads.autocount_rtf(text: str) -> str`: AutoCount's RTF wrapper around plain text (D4).
- `payloads.link_discount(value) -> str`: the value when every `+`-term ends in `%`, else "" (D2a).
- Snapshot `links[]` gains `soDeliveryDate` (`YYYY-MM-DD` or null) and `note` (plain text) at link time.
- New codes: `RESTORE_NOT_LANDED` (D3, op `needs_attention`), `ROW_NEEDS_ATTENTION` (D6 refusal),
  `FOC_ON_ROW` (D2a skip).
- The vendor remark mirror is tolerated by one helper used by every PO verify (D1).

## 3. Decisions

- D1 Verify tolerance (P1 proven): a Remark2..4 that reads back equal to the read-back Remark1 is the vendor
  mirror, tolerated by one helper in `verify_link_batch`, `verify_edit` (the restore step, no header change)
  and the Resume re-check. Nothing broader: Remark2..4 drifting to anything else, any other header field, or
  any other row is still `COLLATERAL_CHANGE`. D1b, a NEW link on a PO whose Remark2..4 differ from Remark1
  (the PUT will overwrite them): owner ruling 16 Nov ~21:42, link as normal, NO user-facing warning ("if it's
  wrong, then we ask AutoCount to fix"); the old texts stay in the op's stored before-read and one server-side
  log line; the vendor bug report goes to crew (`crew/state/files/autocount-link/hapi-vendor-bugs.md`).
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
- D4 Note (crew decision 16 Nov from the owner's real hand-made notes on the incident PO, masked shapes like
  "**CUSTA/PROJECT X S/O: 425879 DD: 31/12/2026"): text = `**` + SO DebtorName + (`/` + SO Ref when Ref is
  not blank) + ` S/O: ` + the SO DocNo without a leading `SO` + (` DD: ` + SO row date `dd/mm/yyyy`
  zero-padded, when the SO row has a date). "DD: ORDER BACK" only when the SO marks the row order-back: the
  hapi SO read carries no such marker (row keys, db3 16 Nov), so the DD part is left out when there is no
  date (UNVERIFIED marker source, reported to crew). Stored as RTF in AutoCount's own default wrapper, the shape
  37 of 40 staged SO-line FurtherDescription samples carry (local staged copy, masked):
  `{\rtf1\ansi\ansicpg1252\deff0\deflang1033{\fonttbl{\f0\fswiss\fcharset0 Arial;}}\viewkind4\uc1\pard\f0\fs20 <text>\par\r\n}`
  with `\`, `{`, `}` escaped and non-ASCII as `\'hh` (cp1252) or `\uN?`. `FurtherDescription` (and
  `FOCQty`) join the edit row whitelist for the restore only, never the public edit door. The note cannot be
  read back through hapi (P3): verify covers every other restored field; the note's landing is shown once on
  the db3 screen and recorded in the evidence.
- D2a FOC / discount (crew decision 16 Nov, option a; the PO total never changes): a PART link puts FOCQty 0
  on the linked row and the FOC stays on the kept row; Discount is restored on the linked row only when it is
  a percentage (every `+`-term ends in `%`), else blank (P2: the link PUT resets it, the restore sets it). A
  WHOLE-row link of a row with FOCQty > 0 cannot move the FOC (P2: hapi cannot write FOCQty): crew decision
  Q4 (a) 16 Nov: the line that would take the whole row is skipped `FOC_ON_ROW` (batch rule: skipped + named),
  never a silent quantity change.
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
- D3a Single part-row link (CRM `po-links`, op `split_link` over the plan 55 path): same restore values (D2) via
  the same function (`payloads.so_link_values` -> `transfer_restore`). A split operation is not resumable
  (`resume` returns the stored answer for `split_link`), so its restore keeps the plan 55 rule: not landed =
  DONE with `LOCATION_NOT_MOVED` / `ROW_VALUES_NOT_KEPT`. Making it resumable is a follow-up (backlog), not this lane.
  The plan 55 header check (`service.py` `_header_unchanged`) gets the same D1 tolerance (AC-65-01b), so a
  single link or a relocate on a PO with hand-typed remarks does not stop half way either.
- Review round 1 rulings (lead, 16 Nov, reviewer on e383d608):
  - R1 (D6): an unlink merge never picks a row covered by an unresolved link op as its merge target (else the
    kept source row grows and the op's Resume can never match); such a candidate is skipped.
  - R2 (D3): `link_row` / `relink_row` are resumable operations, so their restore not landing also ends
    `needs_attention` `RESTORE_NOT_LANDED` (owner rule: a failed write can be retried); Resume re-runs the restore.
    The split path keeps D3a.
  - R3 (D5): Resume of a `link_row` / `relink_row` snapshot stored before plan 65 (no SO values) re-reads the SO
    through the logged reader, like the batch (AC-65-16); never the PO row's date.
  - R4 (D1): the mirror tolerance applies only to the kinds where it is proven: PO / SPO (db3 16 Nov) and QT
    (F13); SO verifies stay strict.
  - R5 (D4): note parts joined by "/" from the non-blank DebtorName and Ref; the leading "SO" strip ignores case.
  - R6: contract `documentation/plans/sprint-5/55-autocount-write-link-contract.md` updated in this PR (SO row
    date, note, % discount, RESTORE_NOT_LANDED, ROW_NEEDS_ATTENTION, FOC_ON_ROW, remark mirror).
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

- Q1 / Q2 / Q4 answered by crew 16 Nov (D4, D2a). Q3 owner ruling 16 Nov (D1b, no warning). Order-back marker: not in the
  hapi SO read (UNVERIFIED source).
- Owner screen check of the note on db3 (P3): evidence run names the PO, row and note text; crew asks at PR time.
- CRM (sorento_crm, cross-repo): hide Unlink on `ROW_NEEDS_ATTENTION`; Resume wording unchanged.

## Part B (17 Nov, owner GO ~01:00; branch crew/autocount-link-restore-b, new PR)

Two SS-only fixes found after #247 went live (crew-note on #247, blockers c and e1). Size S.
- B1 (BL-SS-364 for unlink / relink): `unlink_row` (merge or replace) and `relink_row` delete the linked row
  ("D"); hapi cannot write FOCQty (probe P2), so a row carrying a free quantity loses it. Owner Q4 (never change
  PO quantities silently): refuse `FOC_ON_ROW` before any PUT when the row being removed has FOCQty > 0, with
  the same check as the batch (`payloads.foc_on_row`). Rows without FOC run as today.
- B2 (stale in_progress): a request that dies mid-way leaves its op `in_progress`; today only a NEW op on that
  PO expires it (`run`, operations.py:332-334 at 778e2ed8), never Resume (:359-364), so the PO's other open op
  cannot be resumed (`uq_ac_write_operation_one_in_progress` -> DOC_BUSY) and a Resume of the stuck op answers
  OPERATION_IN_PROGRESS for ever (17:28 incident, op db9d9b1b). Resume now first runs the same
  `expire_stale_in_progress` for that document (same 600 s window, updated_at kept), then goes on as today.
  A young `in_progress` op (< 600 s) is still respected (DOC_BUSY / OPERATION_IN_PROGRESS).
- Contract 55 gets both rules. Evidence: unit tests (db3 cannot hold FOC, probe P2) + a db3 regression run of the
  restore suite on the new head.
- B3 (17 Nov ~01:20, the 01:00 Unlink replay): an operation answered `recovered` left the PO as it was, but only
  `recovered` + `OPERATION_NOT_APPLIED` released its idempotency key (`_nothing_landed`, operations.py:437-441), so a
  `recovered` stored with any other code (a failed check undone by `_recover`, or a hand-set row) is replayed for
  ever to the CRM, which resends the same key for the same line. Owner rule "only a confirmed success locks": every
  `recovered` answer releases the key; the next press runs fresh (re-read, re-guarded, so it cannot write twice).

