# 71 - Unlink returns the quantity to its source PO row: acceptance criteria

Plan: `71-unlink-return-to-source.md`. Tests: `service_backend/tests/test_autocount_write_back_unlink_return_to_source.py`.

| AC | Tag | Given / When / Then |
|---|---|---|
| AC-71-01 | [BE][T] | Given a tied PO row and a free source row of the same item and unit, when unlink is sent with `returnToDtlKey` = the source row, then ONE PUT deletes the tied row and raises the source row by the tied qty; no new row, no move step |
| AC-71-02 | [BE][T] | The source row keeps its own Location, UnitPrice and DeliveryDate (location is not matched) |
| AC-71-03 | [BE][T] | The source row wins over a pool row; it is used with or without `poolLocation` |
| AC-71-04 | [BE][T] | A partly received (or unknown receipt) source row still takes the qty; a fully received one does not (`RETURN_ROW_CLOSED`) |
| AC-71-05 | [BE][T] | Not usable (not on the PO, tied / the tied row itself, other item or unit, SPO row on it, unresolved op on it): the unlink is `done` the plan 66 / plan 62 way and `warnings` names why (`RETURN_ROW_*`) |
| AC-71-06 | [BE][T] | A partly received tied row: today's cut + add, `RETURN_PARTLY_RECEIVED`, the source row untouched |
| AC-71-07 | [BE][T] | The route answer with `returnToDtlKey` carries `detail` = the row now holding the qty; `replacedLines` = [[tied, source]] |
| AC-71-08 | [BE][T] | `returnToDtlKey` not a positive integer = 422, nothing sent; null / absent = today's body, params and hash |
| AC-71-09 | [BE][T] | `returnToDtlKey` is part of the idempotency body (same key, other row = `IDEMPOTENCY_CONFLICT`) |
| AC-71-10 | [BE][T] | A merge answered 5xx is `pending_verification`; Resume finds it landed and answers the source row |
| AC-71-11 | [BE][T] | Relink ignores `returnToDtlKey` |
| AC-71-12 | [BE] | Live db3: a merge into a free and into a partly received source row at another price and date keeps its Location, price and date (DEFERRED: no db3 from the cloud sandbox) |
| AC-71-13 | [BE][T] | A Resume of a fallback that went pending still carries its `RETURN_*` warning |
