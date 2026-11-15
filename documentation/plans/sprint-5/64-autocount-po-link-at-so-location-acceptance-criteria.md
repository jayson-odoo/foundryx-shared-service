# 64 - po-links: the linked row at the SO location (acceptance criteria)

Lane OI-PO-LINK-SS, the shared-service half of the CRM order-inquiry PO-link lane (CRM UAC section P-5,
crew answer (a)). Contract of record: `55-autocount-write-link-contract.md` sections 4.1, 4.5, 5.
No UI in this repo. Additive only: every existing caller keeps its body, status and fields.

## Link at the SO location

| ID | Criterion |
|---|---|
| AC-64-01 | [BE][T] Given a whole-row `POST /api/v1/autocount/po-links` to an SO row whose location differs from the PO row's, when the replace and the move land, then the answer is `200 done`, `errorCode` null, no `LOCATION_NOT_MOVED` warning, and a new top-level `detail` object is the new linked PO row as read back (vendor field names) with `detail.Location` = the SO row's location and `detail.DtlKey` = the new row key in `replacedLines` |
| AC-64-02 | [BE][T] The move is made inside the same `po-links` call (no separate `po-links/relocate` call needed): one replace PUT, then one move edit, both under the same operation |
| AC-64-03 | [BE][T] Given the move does not land, then the answer is still `200 done` with `LOCATION_NOT_MOVED` in `warnings` (unchanged), and `detail.Location` is the location the row really sits at (never the SO location it did not reach) |
| AC-64-04 | [BE][T] Given the PO row has goods received against it (whole row received), then the answer is `409 refused`, `errorCode` `ROW_RECEIVED`, with a plain `message` the CRM shows as-is, `detail` null, and nothing is sent to AutoCount; the key is released so a resend after fixing the cause runs fresh |
| AC-64-05 | [BE][T] A replay of a stored `done` (same `Idempotency-Key`, same body) answers the same `detail` |
| AC-64-06 | [BE][T] Split link (`qty` below the row) answers `detail` = the new linked row the same way (the row the link landed on) |
| AC-64-07 | [BE][T] Old callers unchanged: every existing field (`actionId`, `outcome`, `errorCode`, `document`, `operationId`, `message`, `warnings`, `docKey`, `docNo`, `replacedLines`) keeps its value; `detail` is the only new key on `po-links` and is `null` on every non-`done` answer; the other routes' bodies are unchanged |
| AC-64-08 | [T] Existing link / unlink / split / refusal / retry suites stay green |
