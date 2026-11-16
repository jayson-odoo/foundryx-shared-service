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
