# AutoCount write-back test report 2026-11-04

Book: db3. Run tag: 1104a. PASS 4, FAIL 2, SKIPPED 6.

## C01 Create the test PO: FAIL

- Expected: test PO created with two SRTKT38SS rows (50 and 10 at HQ)
- Observed: create refused by the vendor, status 500

- GET /purchaseorderbydocdate -> 200 (baseline pull docs=3)
- GET /purchaseorderbydocdate -> 200 (FXT-1104a-1 absent)
- POST /NewPurchaseOrder -> 500
  - request: `{"DocNo":"FXT-1104a-1","CreditorCode":"400-N004","DocDate":"2026-11-04T00:00:00","ShippingPO":"F","Details":[{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":50},{"ItemCode":"SRTKT38SS","Location":"HQ","UOM":"UNIT","Qty":10}]}`

## C02 Pull SO then PO into staging: SKIPPED

- Expected: SO days then PO days pulled; the test PO is staged
- Observed: prerequisite C01 did not pass


## C03 Link with split: SKIPPED

- Expected: split: 40 stay at HQ, a new 10 row at BRW-AM linked to SO row 11989
- Observed: prerequisite C02 did not pass


## C04 Link same quantity, location moves: SKIPPED

- Expected: same quantity: the row moves to BRW-AM in place, no row added
- Observed: prerequisite C03 did not pass


## C05 Over-link refused: PASS

- Expected: link refused: the SO row is fully covered (QTY_ABOVE_OUTSTANDING)
- Observed: refused QTY_ABOVE_OUTSTANDING
- Action: f999f750-c154-434c-ac9f-7b2ccb82992c


## C06 Quantity above the PO row refused: PASS

- Expected: link refused: quantity above the PO row (QTY_ABOVE_FREE)
- Observed: refused QTY_ABOVE_FREE
- Action: 2da4e55c-dfd6-41b4-9047-336c005b9a8d


## C07 Unlink a linked real row: FAIL

- Expected: unlink of the linked real row 12013 is done
- Observed: vendor_error VENDOR_ERROR
- Action: 5161bf59-a5d1-4acb-adcd-f17adecc7c01

- PUT /EditPurchaseOrderbydockey -> 500
  - request: `{"DocKey":12008,"DocNo":"202602-S0007","Details":[{"DtlKey":12013,"ItemCode":"SRTKS7090","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]}`
  - before: `[{"DtlKey":12013,"ItemCode":"SRTKS7090","Location":"HQ","UOM":"UNIT","Qty":10.0,"FromSODtlKey":11993,"FromDocType":"","FromDocNo":"","FromDocDtlKey":0}]`
  - after: `[]`

## C08 Relink the real row: SKIPPED

- Expected: relink of row 12013 to SO row 11993 is done and reads back linked
- Observed: prerequisite C07 did not pass


## C09 Stale document refused: PASS

- Expected: stale document refused (DOC_STALE)
- Observed: refused DOC_STALE
- Action: 573733b5-a9c7-443f-abca-d7315e5ad15f


## C10 SPO precondition: SKIPPED

- Expected: SPO created pointing at the split row; unlinking that PO row is refused (ROW_ON_SPO)
- Observed: prerequisite C03 did not pass


## C11 SPO unlink then PO unlink: SKIPPED

- Expected: SPO row unlinked, then the PO row unlinked, both done
- Observed: prerequisite C10 did not pass


## C12 Other book refused with no request: PASS

- Expected: a client for another book is refused at construction with no request (WRITE_NOT_ALLOWED)
- Observed: refused WRITE_NOT_ALLOWED, 0 requests


## Observations for AutoCount

The suite stopped early: two vendor errors blocked the chain (C01, C07). Cases that depend on them are
SKIPPED, not failed. Read-only checks afterwards confirm the book matches this report: PO 202602-S0007
is unchanged (row 12013 still linked to SO row 11993, no write was applied by the failed PUT in C07), and
the day list for 20261104 holds no document from this run.

1. C07 (questions 5, 8): `PUT /EditPurchaseOrderbydockey` that echoes the row exactly as read back is
   rejected with status 500, `SqlDateTime overflow. Must be between 1/1/1753 ... and 12/31/9999`. The
   linked rows 12011, 12013 and 12015 read back `DeliveryDate "0001-01-01T00:00:00"`, a value the
   wrapper itself refuses on write. Question: should a read-back minimum date be treated as "no date" on
   PUT, or must we omit `DeliveryDate` for such rows? Until answered, the unlink of those rows is blocked.
2. C01 (questions 14a, 5): `POST /NewPurchaseOrder` returned 500 `Column 'DisplayTerm' does not allow
   nulls` for a body with DocNo, CreditorCode, DocDate, ShippingPO and two rows. A further probe with
   `DisplayTerm` added returned 500 (SQL error 8178, a parameterized query "expects the parameter @p1"),
   which cleared once `CurrencyCode` and `CurrencyRate` were also sent. Question: which header fields are
   mandatory on create, and can defaults (DisplayTerm, currency) be applied server side?
3. C01 (question 4): that third probe returned 200 "Created Successful" (DocNo FXT-PROBE-1, DocKey
   12023) but reading it back shows `Details []`: the two rows we sent (SRTKT38SS qty 50 and 10 at HQ,
   UOM UNIT) were not saved and no error was returned. Question: what makes a created row persist
   (required row fields, `Seq`, `UserUOM`, `Rate`, `UnitPrice`)? FXT-PROBE-1 is a leftover empty test
   document in db3 and can be deleted on your side.
4. C09/C05/C06 behaved as designed (refused locally with no write sent). C12 sent no request.
5. Not yet observed because the chain stopped: the location override on transfer (question 9), the SPO
   behaviour with `ShippingPO "T"` (questions 13, 14a), partial and over-link quantities (question 10) and
   `FromDocDtlKey` on unlink (question 8). C10 was SKIPPED, so we still do not know whether `ShippingPO
   "T"` is honoured.
