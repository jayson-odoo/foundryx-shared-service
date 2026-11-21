# 71 - SPO line move / split: acceptance criteria

Fixture (fake): SPO-9 line L3 qty 60 tied to PO-A row A1 (qty 60, also linked to SO-2); PO-B row B1, same
item and unit, qty 100, nothing received, nothing else tied to it.

| ID | Tag | Given / When / Then |
|----|-----|---------------------|
| AC-71-01 | [BE][T] | Given the switch on, When move L3 -> B1 qty 24, Then ONE PUT on the SPO edit door carries L3 kept at 36 with its own link to A1 and one new row of 24 linked to B1; answer `done`, `moved {spoDtlKey:new, fromPoDtlKey:A1, toPoDtlKey:B1, qty:24}`, `remainder {spoDtlKey:L3, poDtlKey:A1, qty:36}`. |
| AC-71-02 | [BE][T] | When qty >= 60 (e.g. 60 or 80), Then ONE PUT carries L3 `"D"` and one new row of 60 linked to B1; `remainder: null`, `moved.qty` 60. |
| AC-71-03 | [BE][T] | PO-A (and its SO-2 link) is never written: no call to a PO door. |
| AC-71-04 | [BE][T] | Refused, nothing sent: L3 not linked (`ROW_NOT_LINKED`), target = A1 (`NO_CHANGE`), other item (`ITEM_MISMATCH`), other unit (`UOM_MISMATCH`), B1 fully received (`TARGET_RECEIVED`), B1 room below the take (`QTY_ABOVE_OUTSTANDING`), L3 fully received (`ROW_RECEIVED`), qty <= 0, above 1e9 or more than 8 decimals (`QTY_INVALID`), missing key (`INVALID_REQUEST`), PO-B cancelled (`DOC_CANCELLED`). |
| AC-71-05 | [BE][T] | A refusal releases the idempotency key: the same key with a fixed request runs again. |
| AC-71-06 | [BE][T] | AutoCount refuses the PUT (business refusal) -> `vendor_error`, nothing changed, key released. |
| AC-71-07 | [BE][T] | The PUT times out / 5xx -> `pending_verification`; `GET /write-operations/{id}` reads it; resume reads AutoCount and answers `done` when the new row is there, never sends a second PUT when it is. |
| AC-71-08 | [BE][T] | Same key + same body after `done` replays the stored answer (moved / remainder included), no vendor call. Same key + other body -> `IDEMPOTENCY_CONFLICT`. |
| AC-71-09 | [BE][T] | Switch off -> `VENDOR_UNSUPPORTED`, nothing sent. Non-test book -> the write-connection refusal. |
| AC-71-10 | [BE][T] | Every vendor call is in the call log (masked) under the operation id. |
| AC-71-11 | [BE][T] | The SPO -> PO index (`ac_spo_po_link`) reads the new rows after `done` (B1 shows 24 taken, A1 36). |
| AC-71-12 | [E2E] | db3 probe: split then whole move on a real SPO, read back as AC-71-01/02 (masked evidence in the PR). |
| AC-71-13 | [BE][T] | Slice 2: `/po-links/batch` of 40 on a PO line of 100 that an SPO line of 40 sits on -> `done`; PO PUT first, then ONE SPO PUT (old line `"D"`, new line of 40 tied to the NEW PO line); `spoLines` names it; the index follows. |
| AC-71-14 | [BE][T] | Slice 2 refusals, nothing sent, `ROW_ON_SPO`: switch off; no SPO line of a link's quantity; the link takes the whole PO line; the kept PO line cannot hold the SPO lines that stay. |
| AC-71-15 | [BE][T] | Slice 2: another SPO line the kept PO line can hold stays where it is. |
| AC-71-16 | [BE][T] | Slice 2: the SPO PUT is refused or its outcome is unknown -> `needs_attention` / `SPO_NOT_FOLLOWED`, the PO links answered, the SPO line still on the kept PO line; Resume finishes it (no second link PUT, no second SPO PUT when it had landed); an SPO line changed by hand stays with a person, nothing sent. |
| AC-71-17 | [BE][T] | Slice 2: both PUTs are action rows of the one operation; the route answers `spoLines` (empty on a refusal). |
| AC-71-18 | [BE][T] | Review round 2, live book (the sync job owns the SPO's staged copy): after `/spo-links/move` and after a follow the SPO index reads AutoCount's read-back; the CRM Save (move 80 onto B1, then `/po-links/batch` 80 on B1) carries the SPO line onto the new PO line, nothing left on the cut B1. |
| AC-71-19 | [BE][T] | Resume of `SPO_NOT_FOLLOWED` sends the SPO PUT only while the SPO line reads as planned on every field the PUT sends again, with nothing received on it; a hand edit (price, location, description) or a receipt -> stays `SPO_NOT_FOLLOWED`, nothing sent, the edit kept. |
| AC-71-20 | [BE][T] | A `/spo-links/move` onto the PO line whose outcome is unknown counts against the kept line, also when the index has no row there yet; it does not fit -> `ROW_ON_SPO`, nothing sent. |
| AC-71-21 | [BE][T] | The follow never writes an SPO another SS operation is writing: busy at the plan -> `DOC_BUSY`; busy at the follow or its Resume -> not now (`SPO_NOT_FOLLOWED`), Resume finishes once free. Every SPO operation takes the SPO document's lock; the edit after the follow PUT is built on a fresh read. |
| AC-71-22 | [BE][T] | A follow PUT whose outcome is unknown is not sent again before the 420 s settle window; after it, Resume finishes. |
| AC-71-23 | [BE][T] | The follower needs room on the new PO line when it is sent; a link, move or relink of another SPO line onto the new PO line an SPO line is still to follow onto -> `ROW_NEEDS_ATTENTION`, nothing sent (a new PO line nothing is to follow onto stays free); after Resume the usual room check applies. |
| AC-71-24 | [BE][T] | A batch whose SPO lines all followed (e.g. `RESTORE_NOT_LANDED` after the follow) does not hold the PO line; the needs-attention alert names the SPO lines a person checks. |
