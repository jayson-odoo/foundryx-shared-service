# 71 - Link PO: truthful read-back and resume after a stuck write (PO-LINK-STUCK-RECONCILE-B)

Shared Service half of the CRM lane PO-LINK-STUCK-RECONCILE (sorento-crm #2603). UAC:
`71-po-link-stuck-reconcile-acceptance-criteria.md`. Contract changes: `55-autocount-write-link-contract.md`
sections 4.0, 4.0a, 4.1a and 5. The CRM outcome vocabulary is unchanged (done / refused / pending_verification /
vendor_error / needs_attention, `errorCode`); two codes are new: `VENDOR_TIMEOUT` (unknown) and `SUPERSEDED` (final
refusal by an operator).

## Cause (code read, prod rows masked)
- s5 mismatch: the split link's first write was judged by `service.verify_readback`, whose header check compares
  every header field read before the write. A qty move makes AutoCount recompute the header money / tax fields
  (TaxEntityID, totals), so the 20 Nov split parked `READBACK_MISMATCH`. The batch link's comparator
  (`payloads.verify_link_doc`) compares only allow-listed header fields, so the 08:15 batch on the same PO passed.
  The new row's location / date / price were already not judged on the first write (AutoCount resets them; the
  second write restores them). Whether timing also played a part (cause ii) is the db3 probe, AC-71-14.
- s5 date: `payloads.build_link` copied the PO row (the PO date) onto the new tied row.
- s2: `OperationService.resume` answered the stored result for any split link.
- s3/s4: `primitives._look_after_refusal` read once after an AutoCount error answer and, seeing nothing changed,
  answered `VENDOR_REFUSED` (key released). An AutoCount SQL timeout can commit after hapi answers (it did).

## Design (one write module, nothing new beside it)
1. ONE comparator: `payloads.verify_link_doc` (batch, doc batch, and now the split via `service.verify_split`). Its
   header rule is now every header field read before the write except the vendor-derived ones
   (`payloads.vendor_derived_header`: totals, tax, TaxEntityID, stamps; the Remark mirror as before), and the kept row
   must keep its item, unit, location and price. A split that does not verify is read once more after a short wait
   (`SPLIT_REREAD_WAIT_SECONDS`, inside the action deadline) before it is a mismatch.
2. `payloads.with_so_delivery_date`: the new tied row of a split, batch and doc batch carries the SO line's day.
3. Resume of a split (`OperationService._resume_split`): rebuilds a snapshot from the split's stored write action
   (now carrying the operation from its first commit), reads the PO, and decides done / refused / needs_attention
   without ever re-sending the link write; the only write it may send is the one restore of the batch
   (`_restore_rows`). A same-key resend of a parked split goes through the same Resume. "Nothing there" is only
   trusted after `LOOKUP_SETTLE_SECONDS` since the write (the rule the document primitives already use).
4. Timeout: `primitives.is_vendor_timeout` ("Timeout expired" / "wait operation timed out"; a lock wait is not one) ->
   `VENDOR_TIMEOUT`. `OperationService._vendor_stop` is now the one mapping of a vendor error for every row op and
   batch. A stored `VENDOR_TIMEOUT` is reconciled by a same-key look-up or Resume (`_timeout_verdict`).
5. `close_superseded` + route: conditional parked -> refused `SUPERSEDED`, no AutoCount call, key kept so the CRM's
   same-key look-up gets the final answer.
6. `ROW_ALREADY_LINKED`: plan 69's history rule (`_ss_ties`, shared with the doc batch's `ALREADY_LINKED`) extended to
   the split; a tie SS made from the same PO row to the same SO line with the same qty that still stands refuses.

7. Review round 2 (security + reviewer): `close_superseded` takes link operations only (`_resumable_op`, shared with
   Resume) and is conditional on the `updated_at` read; its stored answer carries `closedAt`, `closedBy` and
   `supersededTie`, which the tie-history guard (`_ss_ties`) and `pending_link_qty` read, so a close never hides a tie
   that stands (a partly linked doc batch merges its intended ties into its exact ones; the over-link sum counts a
   closed tie, row links included, until the staged index shows the new row; no time window); a SUPERSEDED row is never released or re-run (`_nothing_landed`, `_create_resend`, `_look_up_primitive`).
   Resume that loses its claim to a close answers `SUPERSEDED`. `_write_settled` of an operation with no owned
   actions uses its `updated_at`. `is_vendor_timeout` judges the raw body chain (see contract section 5). A timed-out
   single-document primitive is looked up on a same-key resend. `_resume_split` logs a write-gate refusal.

## Not done here
- AC-71-14, the db3 probe (no hapi access from the cloud sandbox): crew runs it.
- No admin UI button for close-as-superseded; the CRM (or an operator with the CRM key) calls the route (BL-SS-372).
- AC-71-14 follow-up: how late a timed-out save can land on a large PO, to re-check `LOOKUP_SETTLE_SECONDS` (BL-SS-373).
- A parked `pending_verification` split's tie is not seen by `ROW_ALREADY_LINKED` (only a closed one is, through `supersededTie`) (BL-SS-374).
