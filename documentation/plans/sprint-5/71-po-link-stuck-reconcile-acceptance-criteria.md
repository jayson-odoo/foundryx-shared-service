# 71 - Link PO stuck reconcile: acceptance criteria (PO-LINK-STUCK-RECONCILE-B)

Shared Service half of the CRM lane PO-LINK-STUCK-RECONCILE (sorento-crm #2603). Plan: `71-po-link-stuck-reconcile.md`.
Tests: `service_backend/tests/test_autocount_write_back_po_link_stuck.py` (fake AutoCount vendor; db3 probe = AC-71-14).

## s5 - the split read-back
- **AC-71-01** [BE][T] Given a split link whose save makes AutoCount recompute the header money / tax fields (totals, TaxEntityID) and put the new tied row at the parent location, When it is read back, Then it is `done` and the restore puts the row at the asked sub-location with the SO line's date.
- **AC-71-02** [BE][T] Given a split link and a batch link, When each is verified, Then both are judged by the one comparator `payloads.verify_link_doc`.
- **AC-71-03** [BE][T] Given a split whose read-back has a wrong qty, an extra or missing row, a changed untouched row, a kept row at the wrong qty / location / price, or the wrong SO line, Then it is not `done` (`pending_verification` / `READBACK_MISMATCH`) and no restore is sent.
- **AC-71-04** [BE][T] Given a header field we did not send that reads back changed, Then it is still a mismatch.
- **AC-71-05** [BE][T] Given a first read-back that does not yet show the save, When it is read once more after a short wait, Then it is judged on that read.

## s5 - the delivery date
- **AC-71-06** [BE][T] Given a split or batch link, When the link write is sent, Then the new tied row carries the SO line's delivery date (none when the SO line has none), never the PO's date.

## s2 - Resume, resend, close, ROW_ALREADY_LINKED
- **AC-71-07** [BE][T] Given a parked split whose tied row stands (as sent, or as AutoCount derived it), When it is resumed, Then it is `done` with the read-back; a restore write is sent only when a readable value is not as asked; the link write is never sent again.
- **AC-71-08** [BE][T] Given a parked split with nothing of it in AutoCount, When it is resumed after the write had time to finish saving, Then it is `refused` `OPERATION_NOT_APPLIED` and the key is released; before that it stays parked.
- **AC-71-09** [BE][T] Given a parked split that is partly there, Then Resume answers `needs_attention` with a plain message, nothing sent.
- **AC-71-10** [BE][T] Given a parked split, When the same key + body is sent again, Then it is re-verified (no second link write); a `done` result is then locked.
- **AC-71-11** [BE][T] Given a parked operation, When an operator closes it as superseded, Then it is a final `refused` `SUPERSEDED`, no AutoCount call is made, and a same-key look-up gets that answer back without a write. A final operation is left as it is.
- **AC-71-12** [BE][T] Given SS already tied qty Q of a PO row to an SO line and that tied row still stands, When a split or batch asks the same again, Then it is refused `ROW_ALREADY_LINKED` (batch: skipped), nothing written; after an unlink of that tie the link is allowed.

## s3/s4 - AutoCount SQL timeout
- **AC-71-13** [BE][T] Given a link write AutoCount answers with its SQL timeout, Then: the write is there -> `done`; nothing yet -> `vendor_error` `VENDOR_TIMEOUT` (key kept), a look-up before the save settled answers the same, after it `refused` `OPERATION_NOT_APPLIED` (released); a save that lands later is found `done` by the look-up; the PO cannot be read -> `needs_attention` `VENDOR_TIMEOUT`. No second link write in any case. A lock wait stays `VENDOR_REFUSED`.

- **AC-71-16** [BE][T] Close-superseded is for link operations only: a parked document primitive answers `OPERATION_NOT_RESUMABLE`, unchanged, and its same-key resend is looked up, never released. The close stores `closedAt` and `closedBy`; a resume that loses the claim to a close answers `SUPERSEDED`; a legacy operation with no owned actions is settled by its own `updated_at`; a closed split's tie still refuses a new-key split of the same row, SO line and qty (`ROW_ALREADY_LINKED`) while it stands.

## s3/s4 - raw timeout text and primitives
- **AC-71-17** [BE][T] A timeout is recognised on AutoCount's raw answer in any shape (later line, inner exception, Win32 class); a lock wait stays a refusal. A timed-out add line / edit is looked up on a same-key resend: landed -> `done`, absent after the settle time -> released, before -> `VENDOR_TIMEOUT` again, no second PUT before the read.

## Proof on db3
- **AC-71-14** [E2E] On db3 only (never db1/db2), every hapi call logged: a split link on a PO with an SO-tied new row at a sub-location (BRW-NTC) shows which cause made op 15587ab3 mismatch: (i) AutoCount normalises / derives the row values or recomputes the header, or (ii) the read ran before the save finished.
  - Crew-run evidence (20 Nov, hapi /api/db3 only, direct HTTP replay of the split body, test documents created by crew and cancelled after; one run on a 2-row PO): crew's verdict is cause (ii). Reads at +0.5 s, +5.7 s and +15.8 s after the PUT were identical on every field. New tied row, sent vs read: Location BRW-NTC -> HQ; DeliveryDate 2026-12-05 -> empty (0001-01-01); Desc2 (the note) -> empty; UnitPrice 1.0 -> 0.0; Description (the item code) -> the item master name plus the code. Held: the link to the SO row, Qty (new 4, old row 6). Header: TaxEntityID stayed 0; totals 10.0 -> 6.0, because the new row is priced 0.
  - What this means for the fix: within 16 s nothing changed, so this run shows the known reset of a new tied row (location, price, date, note), which the first-write check never judges. The prod mismatch came from the header: totals and TaxEntityID moved, and the old split check compared every header field. The second write puts back the location, the UnitPrice (the old PO row's price, so the totals come back too), the SO line's date and the note. Not ruled out (crew caveat): a later derivation on a ~96-row prod PO. That case is covered by the short re-read and by Resume. Not restored: AutoCount's own Description (item master name plus code). It is not judged and is left as AutoCount sets it.

## Routes
- **AC-71-15** [BE][T] `POST /write-operations/{id}/close-superseded` answers 200 `refused` `SUPERSEDED`; unknown id 404. `POST /write-operations/{id}/resume` on a parked split answers 200 `done` with `document`.
