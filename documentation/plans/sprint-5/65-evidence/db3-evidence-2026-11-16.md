# Plan 65 db3 evidence, 16 Nov 2026

Code under test: HEAD 99692547. Book: db3 (test book only), own documents `FXT-1116*`. Source: the live suite
`runner.py --suite restore` (run tag 1116I) and `--resume-op`, read from `ac_api_call_log` and `ac_write_action`
of the lane DB. Debtor and creditor names and codes are left out. FOC: db3 reads FOCQty 0 on every row and cannot
write it, so the FOC path is covered by unit tests only.

## 1. Fresh link on the fixed code (run 1116I, op `f3742e75-f6de-4f8b-a7f3-fe1382170fbd`): PASS

Documents: SO `FXT-1116I-SO` (one row of 5 at BRW-AM, delivery date 2026-12-16, header Ref "FXT REF"), PO
`FXT-1116I-PO` (three rows at HQ; source row Seq 16: qty 5, price 2.5, discount 5%, date 2026-11-26).
Operation: `link_batch`, qty 1 of the source row to the SO row.

| Step | Call | Status |
|---|---|---|
| read | GET /PurchaseOrderbydocno | 200 |
| read | GET /SalesOrderbydocno | 200 |
| read | GET /PurchaseOrderbydocno | 200 |
| link PUT | PUT /EditPurchaseOrderbydockey | 200 |
| read-back | GET /PurchaseOrderbydocno | 200 |
| restore PUT (step `move`) | PUT /EditPurchaseOrderbydockey | 200 |
| read-back | GET /PurchaseOrderbydocno | 200 |

Every call has one `ac_api_call_log` row carrying the operation id. Final status `done`, warnings
`TRANSFER_STATE_UNKNOWN` only (db3 hides received quantity), no drift field named by the link verify.

| New linked row | Location | UnitPrice | DeliveryDate | Discount | FOCQty | FromSODtlKey |
|---|---|---|---|---|---|---|
| after the link PUT (AutoCount reset) | HQ | 0 | blank | blank | 0 | yes |
| after the restore PUT (final) | BRW-AM | 2.5 | 2026-12-16 (the SO row's, not the PO row's 2026-11-26) | 5% | 0 | yes |

| Kept source row (Seq 16) | Qty | Location | UnitPrice | DeliveryDate | Discount |
|---|---|---|---|---|---|
| before | 5 | HQ | 2.5 | 2026-11-26 | 5% |
| after | 4 | HQ | 2.5 | 2026-11-26 | 5% |

The other two PO rows read back unchanged. Remark1..4 all read "FXT R1" (the vendor mirror, probe P1). The restore
PUT's `Details` hold only the new row; its body carries FurtherDescription, sent as RTF around this plain text:

`**FXT REF S/O: FXT-1116I-SO DD: 16/12/2026`

(The test SO has a blank debtor name on db3 and a DocNo without a leading "SO", so the name part and the prefix
strip are not exercised live; both are unit-tested.) After this step the suite's cases R03 and R05 overwrite
that row's note with a probe text and its discount, so do NOT use `FXT-1116I-PO` for the screen check.

Suite totals: R00 PASS, R01 PASS, R01B PASS, R02 PASS, R03 PASS (edit PUT with FurtherDescription: 200, row and
link kept), R05 PASS (a second PUT sets Discount; FOCQty stays 0), R04 PASS (half-filled state built).

## 2. Repair by Resume on the half-filled op `d146c832-907e-4040-829b-2308520dd094`: PASS

State before: built on ddb53cbe (run 1116E, PO `FXT-1116E-PO`, SO `FXT-1116E-SO`), `needs_attention`
`COLLATERAL_CHANGE`, snapshot without SO values, link PUT landed, restore never ran. Resume on the fixed code:

| Step | Call | Status |
|---|---|---|
| read | GET /PurchaseOrderbydocno | 200 |
| SO re-read (old snapshot) | GET /SalesOrderbydocno | 200 |
| restore PUT | PUT /EditPurchaseOrderbydockey | 200 |
| read-back | GET /PurchaseOrderbydocno | 200 |

Exactly one PUT, no link PUT, `Details` = the new linked row only (DtlKey 12074, Seq 80). Status `done`,
warnings none.

| New linked row (Seq 80) | Location | UnitPrice | DeliveryDate | Discount | FOCQty | FromSODtlKey |
|---|---|---|---|---|---|---|
| before Resume | HQ | 0 | blank | blank | 0 | yes |
| after Resume | BRW-AM | 2.5 | 2026-12-16 (the SO row's) | blank (its source row had no discount) | 0 | yes |

Kept source row and the other rows: Qty and every compared field identical in the before-read and the read-back
(source row 4 -> 4, linked row of run 1116E unchanged, row B 2 -> 2). The restore PUT carried:

`**FXT REF S/O: FXT-1116E-SO DD: 16/12/2026`

## 3. For the owner's AutoCount screen check (db3)

Open purchase order `FXT-1116E-PO`, the 5th line (Seq 80, DtlKey 12074, item SRTKT38SS). Its further description
should read `**FXT REF S/O: FXT-1116E-SO DD: 16/12/2026`. Nothing touched that row after the Resume.

## 4. What changed in the suite for this run

`runner.py` (tester code, not product): R02 now judges the fixed rule (done, no drift, Location BRW-AM, price,
SO row date, 5% discount, FOCQty 0, link kept, kept row cut by 1) instead of "any drift or not done"; the
`_drifted` call passes the kind (`"PO"`) after the coder's signature change.

## 5. Note retention probe (run 1116J)

Question: does an edit PUT that does not carry FurtherDescription clear a note already on the row (every link PUT
echoes the kept source row without it)? Run: SO `FXT-1116J-SO`, PO `FXT-1116J-PO` (DocKey 12117), the real
`link_batch` (op `86637917-2fe1-4f1c-9342-213b5e40397e`, `done`), whose restore PUT put the note
`**FXT REF S/O: FXT-1116J-SO DD: 16/12/2026` on the new linked row (DtlKey 12122, Seq 64). Then ONE logged edit PUT
(Details = that row as read, normal row, no FurtherDescription key, Desc2 changed to "FXT RETAIN"): 200; re-read:
row kept, link (FromSODtlKey) kept, Desc2 "FXT RETAIN". hapi never returns the note, so whether it survived is
read on the AutoCount screen.

Rows for the owner to open in the AutoCount screen on db3:
1. `FXT-1116E-PO`, Seq 80: the note must read `**FXT REF S/O: FXT-1116E-SO DD: 16/12/2026` (landing check).
2. `FXT-1116J-PO`, Seq 64 (DtlKey 12122): if the note `**FXT REF S/O: FXT-1116J-SO DD: 16/12/2026` is still there,
   a PUT without the note keeps it. If it is blank, every link PUT wipes the kept row's note (a vendor issue).

## 6. Part B regression (17 Nov)

Code: part B head 21591e7f (branch `crew/autocount-link-restore-b`). Book: db3, own documents `FXT-1117A-*`. Fresh
`--suite restore` run, tag 1117A: R00, R01, R01B, R02, R03, R05, R04 all PASS (7 of 7), exit 0.

- Fresh link (op `1f5148c0-853b-413e-9764-8f1bb1d67f65`): `done`. Calls: GET PO, GET SO, GET PO, link PUT, GET PO,
  restore PUT, GET PO, all 200, each with one `ac_api_call_log` row carrying the operation id.
  New linked row (DtlKey 12130): after the link PUT HQ / 0 / blank date / blank discount / FOCQty 0 / link yes; after
  the restore PUT BRW-AM / 2.5 / 2026-12-17 (the SO row's) / 5% / FOCQty 0 / link yes. Kept source row qty 5 to 4,
  other rows unchanged. The restore PUT's Details hold only the new row; note sent:
  `**FXT REF S/O: FXT-1117A-SO DD: 17/12/2026`.
- Resume of the half-filled op built by case R04 (`f6322d02-7719-4685-bea0-26c1decebcda`, the real link halted
  before its restore): `done`, warnings none, ONE PUT (Details = the new row 12132 only), no link PUT. Row went HQ /
  0 / blank to BRW-AM / 2.5 / 2026-12-17, discount blank (its source row had none); every other row identical in
  the read-back; the same note text sent.
- FOC cannot be held on db3 (reads 0, cannot be written), so B1 (`FOC_ON_ROW` on unlink / relink) and B2 (stale
  `in_progress` expiry) are proven by unit tests only. The suite has no unlink case; the FOC-0 link path is the
  one shown here and behaves as on 99692547.
