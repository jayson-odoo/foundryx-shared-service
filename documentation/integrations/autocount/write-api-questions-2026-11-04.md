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
