# AutoCount write API: questions from Foundryx (4 Nov 2026)

Context: Foundryx will write PO line links (PO line <-> SO line, SPO line <-> PO line) and later
Quotation / Sales Order create, edit and cancel through the hapi wrapper, testing on `db3` only.
Every observation below is from read-only GETs on 4 Nov 2026; doc numbers refer to your test set.

## Endpoints

1. Edit endpoints for Sales Order, Purchase Order (and Shipping PO) and Request Quotation: are they
   `PUT /EditSalesOrderbydockey`, `PUT /EditPurchaseOrderbydockey`, `PUT /EditRequestQuotationbydockey`?
2. Cancel (and un-cancel) for Quotation, Sales Order and Purchase Order: which endpoint or field
   (`Cancelled "T"` on the edit PUT, or a separate route)? We will never delete documents.
3. A GET for one document by DocKey (today `/purchaseorderbydockey` and `/salesorderbydocno` return
   404). After every write we read the document back; by DocDate works but returns the whole day.

## Edit (PUT) semantics

4. Detail rows not listed in the PUT body: kept or removed? (QT-004194 kept its 3 rows after the edit
   that listed only DtlKey 11986.) How is one detail row removed?
5. Header on PUT: must every header field be resent, or only DocKey plus changed fields? Are omitted
   fields blanked?
6. Is a PUT all-or-nothing (one bad row rejects the whole edit, nothing saved)?

## PO line <-> SO line link

7. Link on edit: PUT a PO row with `DtlKey > 0` and `FromDocType "SO"`, `FromDocNo`, `FromDocDtlKey`:
   supported, or only on new rows (`DtlKey 0`)?
8. Unlink: PUT the PO row (`DtlKey > 0`) with `FromDocType ""`, `FromDocNo ""`, `FromDocDtlKey 0`:
   does that clear `FromSODtlKey` / `FromSODocList` and release the SO line's transferred qty?
9. Location on transferred rows: the PO 202602-S0007 example body sent `Location "BRW-AM"` on the three
   SO rows; db3 reads them back as `HQ` (created and last modified at the same time). Does transfer
   from SO override the row location? We need the row to keep the location we send.
10. Partial qty: may a PO row with qty smaller than the SO row link to it, may several PO rows link to
    one SO row, and what happens when linked qty exceeds the SO row's outstanding qty?
11. Transferred qty: SO GET has no transferred-to-PO qty and PO GET has no transferred qty (to SPO or
    GRN). Can these be added (e.g. `TransferedPOQty` on SO rows, `TransferedQty` on PO rows)?
12. PO GET rows carry `FromSODtlKey` and `FromSODocList` but not the SO DocKey: can `FromSODocKey` be added?

## Shipping PO (SPO)

13. A PO row already transferred into an SPO row: can its SO link still be changed? To release it,
    do we PUT the SPO row with empty `FromDocType` / `FromDocNo` / `FromDocDtlKey`, or remove the SPO row?
14. Rows already received (GRN) or delivered: which edits are refused, and with what error?
14a. db3 has no SPO yet. Does `POST /NewPurchaseOrder` with header `ShippingPO "T"` and rows
    `FromDocType "PO"` create an SPO, so we can test the SPO cases on db3?

## Quotation -> Sales Order

15. SO390188 row reads `FromDocType "QT"`, `FromDocNo "QT-004193"` but `FromDocDtlKey 0` although the
    POST sent 11983. Expected?

## Errors, concurrency, retries

16. Error format: HTTP status and body for validation errors (duplicate DocNo, unknown DtlKey, locked
    or cancelled document, unknown item / location).
17. Concurrency: a user editing the same document in AutoCount while our PUT arrives: is there a lock,
    and can we send a `LastModified` check so a stale edit is refused?
18. Retries: if a POST times out and we retry, is a second document created, or does the duplicate
    DocNo reject it? Can we ask AutoCount to assign the next DocNo?
19. Audit: writes show `LastModifiedUserID "FOUNDRYX"`. Can we pass the acting user's name?
20. Authentication scheme for the write endpoints on the live databases, and whether db3 will stay
    available as the test database.

## Found in our first db3 run (4 Nov 2026)

21. Empty dates: GET returns `"0001-01-01T00:00:00"` for an empty row date (e.g. PO 202602-S0007 row
    12013 `DeliveryDate`), and a PUT that sends it back fails with HTTP 500 "SqlDateTime overflow". We
    now omit such dates on write. Is omitting the field the right way to keep a date empty on edit?
22. `POST /NewPurchaseOrder` with a short body: 500 "Column 'DisplayTerm' does not allow nulls", then
    500 SQL error 8178 until `CurrencyCode` / `CurrencyRate` were added, then 200 "Created Successful"
    but the document read back with no rows (our probe FXT-PROBE-1, DocKey 12023, left in place; we never delete in AutoCount).
    Which header and row fields are required, and can a POST that drops rows return an error instead?

## Delete API (you told us on 4 Nov that a line's link can never be edited after it is created)

We understand the way to change or remove a line's link is: delete the line, then add a new line with the
right link (or none). We are building our side now so that your delete API plugs in. To match it:

23. Endpoint, method and body for deleting one detail row, per document type (Quotation, Sales Order,
    Purchase Order, Shipping PO): for example `DELETE /DeletePurchaseOrderDetailbydtlkey` with
    `{DocKey, DtlKey}`, or a row flag on the existing `Edit...bydockey` PUT? And the same for a whole
    document (we will not use document delete in normal work; cancel stays the way a document ends).
24. (Withdrawn 4 Nov: we design for a separate delete then add, with our own recovery if the add fails.)
25. Deleting a row that has something downstream: a PO row already received (GRN) or partially received,
    a PO row an SPO row points at, an SO row a PO row is linked to, an SO row already delivered (DO). Is
    the delete refused, and with what HTTP status and error text?
26. After deleting a PO row linked to an SO row, is the SO row's transferred quantity released at once,
    so a new PO row can link to the full SO quantity in the next call?
27. What does the delete answer return: the remaining rows, the new `LastModified`, or only a message?
28. Line position: can the new row take the deleted row's position (`Seq`), so printed documents keep
    the same line order?
29. A new row linked to an SO row comes back at location `HQ` even when we send another location (our
    test FXT-1104d-1 row 12046), so today a link needs a second edit to move it. Can the add keep the
    location we send?
30. Deleting the last row of a document, or a row of a cancelled document: allowed or refused?

## Found in our Quotation / Sales Order run (4 Nov 2026, db3)

31. Sales Order from a Quotation row: `POST /NewSalesOrder` FXT-1104q-SO1 (DocKey 12072) sent the row with
    `FromDocType "QT"`, `FromDocNo "FXT-1104q-QT1"`, `FromDocDtlKey 12061`, `FullTransferOption " "`,
    `FullTransferFromDocList ""` (qty 1 of the quotation row's 2). The SO row reads back `FromDocDtlKey 0`
    and the quotation shows `ToDocType ""`, `ToDocKey 0` on the header and every row. Your SO390188 left
    QT-004193 with `ToDocType SO`. Is a partial transfer from a quotation row supported, and which field
    shows the quotation row's transferred quantity?
32. Cancel: `Cancelled "T"` in the header of `PUT /EditQuotationbydockey` (FXT-1104q-QT3, DocKey 12076) and
    `PUT /EditSalesOrderbydockey` (FXT-1104q-SO2, DocKey 12078) answer 200 and change nothing (`Cancelled`
    reads back "F"). Please add a cancel (and un-cancel) door, or say which field the edit door honours (AQ2).
33. `PUT /EditSalesOrderbydockey` exists and applied qty, unit price, discount and a new `DtlKey 0` row on
    FXT-1104q-SO1. Please confirm it is supported (it is not in your notes).
34. Clean-up on db3: please cancel our test documents FXT-1104q-* and the quotation numbered `SO390188`
    (DocKey 12067, Ref `P-DOC1-FXT1104q`), which our probe created by mistake with a wrong DocNo, and
    quotation QT-000001 (DocKey 12069, Ref `P-DOC2-FXT1104q`, our test of `DocNo "<<New>>"`), and the
    runner documents of 4 Nov: QT-000002 to QT-000005, FXT-1104r-*, FXT-1104s-* (including FXT-FXT-1104s-SO,
    which has no row), FXT-1104t-*, FXT-1104u-*, FXT-1104v-*. We cannot
    cancel through the API today and never delete. Your sales order SO390188 was not touched.

## Sales order line with a linked purchase order line (db3, 4 Nov 2026, FXT-1104r-SO1 / FXT-1104r-PO1)

35. Cutting such a line below the linked qty is refused with HTTP 500 and the clear message "The quantity of
    the item code ... is less than the quantity it was partially transferred to Purchase Order, save
    aborted." Will your delete API refuse deleting that sales order line the same way (status and message),
    and refuse deleting a purchase order line that is received (GRN) or on a Shipping PO?
36. Changing the ItemCode of that linked sales order line was ACCEPTED (200): the line now reads another item
    while the purchase order line stays linked to it. Should AutoCount refuse an item change on a line that
    has a linked purchase order line? (We never send item changes on existing lines.)
37. Business refusals arrive as HTTP 500 with `ExceptionMessage` (credit limit, transferred qty). Could they
    use 4xx, so a refusal is told apart from a server fault?

## Found by our runner (4 Nov 2026, db3)

38. A sales order line without the full row shape of your sample (`FullTransferOption " "`,
    `FullTransferFromDocList ""`, `YourPONo`, `ProjNo`, `FOCQty`, `Discount`, `TaxCode`, `Desc2`) is answered 200
    but reads back with no row. Could such a body be refused with an error instead of dropping the row?
39. A sales order line taken from a quotation line takes that line's unit price and location whatever we send.
    Intended? Can a different price or location be sent on the transfer?
