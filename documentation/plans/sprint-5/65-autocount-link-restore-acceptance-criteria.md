# Plan 65 UAC: AutoCount Link PO restore + Resume repair

Plan: `65-autocount-link-restore.md`. Each AC names its test (unit = pytest on fixtures; live = db3 script
`runner.py --suite restore`). Fixtures are shaped like the incident with masked values (no customer data).

## Link verify (D1)

- AC-65-01 A link PUT whose read-back differs from the before-read ONLY by the AutoCount-side drift probe P1
  proved (expected: Remark2..4 read back as Remark1) verifies DONE. [unit]
- AC-65-02 Any other header field drift, or any field drift on a row other than the source row, is still
  `COLLATERAL_CHANGE`; a Remark2..4 drift to a value that is NOT Remark1 is still `COLLATERAL_CHANGE`. [unit]
- AC-65-03 The restore step's verify (verify_edit, no header change) applies the same tolerance: the proven
  drift alone never turns a landed restore into "not landed". [unit]
- AC-65-04 Live: the incident-shaped link on db3 (four different remarks, sub-location SO row) ends DONE on
  the fixed code; on ddb53cbe it ends `needs_attention` with the code P1 names. [live]

## Restore values (D2, D4)

- AC-65-05 After a link, the new linked row reads back with Location = the SO row's location, UnitPrice =
  the old PO row's, DeliveryDate = the SO row's delivery date (not the PO row's). [unit + live]
- AC-65-06 SO row with no delivery date: the restore sends no date (the row stays blank), never the PO row's
  date. [unit]
- AC-65-07 The restore PUT carries `FurtherDescription` on the new linked row only: AutoCount's RTF wrapper
  (plan D4) around `**<DebtorName>/<SO Ref> S/O: <SO DocNo without leading "SO"> DD: <dd/mm/yyyy>`;
  `/<SO Ref>` left out when Ref is blank; ` DD: ...` left out when the SO row has no date; date zero-padded;
  `\`, `{`, `}` escaped, non-ASCII encoded. [unit; live: PUT accepted, row and link kept]
- AC-65-08 Part link: the linked row has FOCQty 0 and the kept row keeps its FOCQty. Whole-row link: the first
  linked row gets the old row's FOCQty. Discount is copied only when it is a percentage (e.g. "5%",
  "5%+2%"), else blank. The PO total before and after the link is the same. [unit + live]
- AC-65-09 The restore PUT's Details hold only the new linked rows; no other row and no header field is sent
  for change. [unit]
- AC-65-10 The snapshot stores, per link, the SO row's delivery date and the note text at link time. [unit]

## Restore verified (D3)

- AC-65-11 A restore whose read-back does not show every restored field (other than the note, which hapi cannot
  read) leaves the operation `needs_attention` with a plain code, resumable; never DONE with warnings. [unit]
- AC-65-12 A restore skipped because the request deadline passed leaves the operation `needs_attention`. [unit]

## Resume repair (D5)

- AC-65-13 Resume on a batch link whose link PUT landed and whose restore never ran: re-reads the PO, sends ONE
  restore PUT on the new row(s) only (D2 values), verifies it, ends DONE; the link PUT is never re-sent. [unit +
  live P4]
- AC-65-14 Resume re-judges the stored link step (before_json vs after_json) with the D1 tolerance: real
  collateral drift -> stays `needs_attention`, no PUT. [unit]
- AC-65-15 Resume checks the fresh PO: kept row qty = snapshot qty - linked qty (or the row is gone when all
  was taken), one new row per link; otherwise `needs_attention`, no PUT. [unit]
- AC-65-16 Resume of an older snapshot (no SO date / note stored) re-reads the SO through the logged reader
  and restores with the SO row's date and the note. [unit]
- AC-65-17 Resume when the new row already shows the restored location, price and SO date still sends the note
  (one PUT) and ends DONE; it never moves the date back to the PO row's. [unit]

## Unlink while unresolved (D6)

- AC-65-18 `unlink_row`, `relink_row` and `delete_line` on a PO row covered by a `needs_attention` or
  `pending_verification` link operation (its source row, or a new row linked to one of its SO rows) are
  refused `ROW_NEEDS_ATTENTION` with no vendor call. [unit]
- AC-65-19 The same ops on another row of that PO are not refused for this reason; a new Link PO on another
  row still runs. [unit]
- AC-65-20 After Resume ends DONE the refusal lifts. [unit]

## Logging and books (D7)

- AC-65-21 Every GET/PUT of the link, restore and Resume paths writes one `ac_api_call_log` row (operation id,
  acting user). [unit]
- AC-65-22 The live script refuses to start unless the write connection is the db3 test book. [unit]

## Owner standing rules applied

Retry after failure (AC-65-11..13), ERP calls logged (AC-65-21), reuse one restore function (plan D8), no
borrowed values (AC-65-06), rows matched only by FromSODtlKey + qty (AC-65-15).
