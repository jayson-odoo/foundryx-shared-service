# SS AutoCount: per-PO-document write lock (lane AUTOCOUNT-SS-POLOCK)

Shared-service half of AUTOCOUNT-ASYNC-RESERVE. Closes the race where the same PO row is linked to two
DIFFERENT SO rows at overlapping times: the existing advisory lock is per SO row only, so two callers on
different SO rows never meet.

## Acceptance criteria

- **POL-01 [BE][T]** Given two `po-links/batch` calls on the same PO row onto two different SO rows at the same
  time, when both run, then exactly ONE PUT reaches AutoCount; the other answers `DOC_BUSY` and is NOT stored
  under its idempotency key (a resend with the same key runs fresh).
- **POL-02 [BE][T]** Every operation that writes a PO (`link_row`, `split_link`, `link_batch`, `relink_row`,
  `unlink_row`, plan 55 link / unlink / relocate, `resume`) holds a per-PO-document advisory lock around read,
  guard and PUT. Lock order: PO document first, then SO rows. Same 30 s wait, then `DOC_BUSY`. Nested takes of
  the same lock inside one operation (an operation running the plan 55 split link) reuse the held lock.
- **POL-03 [BE][T]** The lock is released on every exit path: success, refusal, exception, and a lock wait that
  timed out (nothing half-held).
- **POL-04 [BE][T]** The busy check counts `in_progress` operations on the same PO (other than the caller's own):
  a standalone plan 55 action on a PO that an operation is writing is refused `DOC_BUSY`.
- **POL-05 [BE][T]** PO-side pending qty: quantity of the PO row that `pending_verification` link operations may
  already have linked counts against the row's free qty (`QTY_ABOVE_FREE`), not only against the SO side.
- **POL-06 [BE][T]** (confirm) A stored `DOC_BUSY` is never replayed under its key, and a key whose stored answer is a
  definite refusal is released (plan 62 D6).

Out of scope: `expectedLastModified` from the CRM (later), speed-ups (SS-AUTOCOUNT-SPEEDUP), response shapes.
