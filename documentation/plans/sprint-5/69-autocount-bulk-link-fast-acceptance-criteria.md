# UAC 69: Bulk PO-SO link, fast

Plan: `69-autocount-bulk-link-fast.md`. Tags: [BE] backend, [T] test, [DB3] live probe on the db3 test book only.

## Slice A - one PUT per PO document, no cap

- AC-69-01 [BE][T] Given one PO document with 3 rows each linked to 2 SO rows in one request, when
  `POST /po-links/doc-batch` runs, then exactly ONE link PUT and at most ONE restore PUT are sent, and the
  PO is read before the link PUT (the re-read is kept).
- AC-69-02 [BE][T] Given 45 links on one PO document, when the request runs, then it is NOT refused for its
  size; all 45 are linked using ceil(45 / MAX_LINES_PER_PUT) link PUTs.
- AC-69-03 [BE][T] Given one link whose quantity is above the SO outstanding, then that line is `skipped`
  with its code and every other line is `linked`.
- AC-69-04 [BE][T] Given chunk 2 is refused by AutoCount, then chunk 1's lines read `linked`, chunk 2's read
  `failed` with the plain reason, the operation can be retried for the failed lines only.
- AC-69-05 [BE][T] `POST /po-links/batch` answers as before (plan 62 contract) and runs through the same
  function; its 20-entry cap is removed.
- AC-69-06 [BE][T] Every answer carries `requestedAt`, `linkedAt` (null until a link PUT landed) and
  `finishedAt`, ISO-Z; `GET /write-operations/{id}` carries the same.

## Slice B - unknown outcome is read, never assumed

- AC-69-10 [BE][T] Given a link PUT answers 500 with an AutoCount message AND the PO read afterwards shows
  the links landed, then the operation continues (restore, stage) and ends `done`.
- AC-69-11 [BE][T] Given a link PUT answers 500 with a message AND the read shows nothing changed, then the
  operation is refused with the plain AutoCount reason and the key is released (Try again works).
- AC-69-12 [BE][T] Given the read after a failed PUT cannot be done, then the operation is
  `pending_verification` (never refused), and Resume decides.

## Slice C - first-write values

- AC-69-20 [DB3] Probe report: for each of Location / UnitPrice / DeliveryDate / Discount / note on a new
  SO-linked PO row, whether PUT 1 keeps it on today's hapi build (evidence: call-log ids, masked).
- AC-69-21 [BE][T] When the link PUT's read-back already shows the wanted values, no restore PUT is sent.
