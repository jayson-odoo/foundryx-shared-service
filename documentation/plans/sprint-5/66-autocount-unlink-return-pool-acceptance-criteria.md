# 66 - Unlink returns the quantity to the pool (acceptance criteria)

Card: `66-autocount-unlink-return-pool-card.md`. Contract: `55-autocount-write-link-contract.md` section 4.2.
Tests: `service_backend/tests/test_autocount_write_back_unlink_pool.py`.

| ID | Criterion |
|---|---|
| AC-66-01 | [BE][T] Given `poolLocation` and a free PO row at that exact location with the same ItemCode + UOM, when a linked row is unlinked, then ONE PUT deletes the linked row and raises that pool row's Qty by the freed qty; `replacedLines` = [(linked, pool row)]; the pool row keeps its own UnitPrice and DeliveryDate |
| AC-66-02 | [BE][T] Given `poolLocation` and no such pool row (none, linked, other item/UOM, on an SPO, received, or at another code such as BRW-BB for BRW), then the unlinked row is replaced by a free row moved to `poolLocation`, same qty, price and delivery date |
| AC-66-03 | [BE][T] Given `poolLocation`, a same-location free row (plan 62 D7 target) is NOT merged into: the qty goes to the pool |
| AC-66-04 | [BE][T] Given a partly received linked row, the received part stays at its location and the new row with the rest is at `poolLocation` |
| AC-66-05 | [BE][T] Given no / null / blank `poolLocation`, behaviour, answer body (no `detail`) and idempotency hash are today's (plan 62 D7, AC-64-07) |
| AC-66-06 | [BE][T] Given `poolLocation`, the answer carries `detail` = the row holding the freed qty (`detail.Location` = pool); `detail` is null on a refusal |
| AC-66-07 | [BE][T] `poolLocation` not text or longer than 64 characters = 422 `INVALID_REQUEST`, nothing sent; it is part of the idempotency body |
| AC-66-08 | [BE][T] A move that does not land = `done` + `LOCATION_NOT_MOVED`; Resume of a pending replace moves to the pool; Resume of a pending merge answers the pool row; recovery re-adds the old linked row at its original location |
| AC-66-09 | [BE][T] `relink_row` ignores `pool_location` |
| AC-66-10 | [Live] db3 (test book only): one merge (pool row at another price) and one move to the pool land as above (deferred: no db3 access from the cloud sandbox; crew hand test) |
