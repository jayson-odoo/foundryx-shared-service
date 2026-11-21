# 71 - AutoCount: move / split an SPO line onto another PO line (SPO-LINK-PO-SS)

Status: Built behind the OFF switch; db3 probe deferred by the owner (20 Nov), tracked as BL-SS-372. Partner lane: CRM SPO-LINK-PO (the CRM Save calls this, then the existing Link PO).
UAC: `71-autocount-spo-link-move-acceptance-criteria.md`.

## Why

The tie "this shipping-PO (SPO) line ships this PO line" lives only in AutoCount, on the SPO detail
(`FromDocType "PO"`, `FromDocNo`, `FromDocDtlKey`). The CRM reads it through the sync; nothing writes it.
Owner rulings (20 Nov): when an SO needs less than an SPO line carries, split the SPO line; the taken
part moves to the chosen PO line (same product, any supplier, not fully received); the rest stays on the
old PO line, which keeps its own SO link. Invariant: every SPO line stays tied to a PO line.

## Contract

`POST /api/v1/autocount/spo-links/move` - the same frame as `/po-links/*` (API key, `Idempotency-Key`,
`X-Request-ID`, the operation answer: `operationId`, `outcome`, `errorCode`, `message`, `warnings`,
`docKey`, `docNo`, `replacedLines`, `document`, `requestedAt`, `linkedAt`, `finishedAt`).

Body (camelCase, all keys integers):

```
{ companyCode, spoDocKey, spoDtlKey, toPoDocKey, toPoDtlKey, qty,
  docDate?, poDocDate?, expectedLastModified? }        # the last three: as on /spo-links/relink
```

Answer adds:

```
moved:     { spoDtlKey, fromPoDtlKey, toPoDtlKey, qty } | null     # null unless outcome = done
remainder: { spoDtlKey, poDtlKey, qty } | null                     # the part left on the old PO line
```

`outcome` uses the house vocabulary of `/po-links` (the CRM client already maps it):
`done` | `refused` (nothing changed, the key is released) | `pending_verification` (= "unknown": the
PUT may have landed; `GET /write-operations/{id}` / `resume` reads AutoCount before any retry) |
`vendor_error` (AutoCount said no, nothing landed) | `needs_attention`.

## Rules

- **take** = `min(qty, open)`, `open` = SPO line qty - its received qty (unknown received = 0, with
  the `TRANSFER_STATE_UNKNOWN` warning, same as relink). A qty outside the house rule (above 0, at most 1e9, at most 8 decimal places) = `QTY_INVALID`.
- take = the whole line (nothing received, take = line qty): the line is moved whole, `remainder: null`.
- otherwise split: the old line keeps `qty - take` on its old PO line (that is the `remainder`), a new
  line of `take` is tied to the target PO line.
- ONE PUT on the SPO edit door for both shapes (`build_link_doc` with one group: the old row `"D"` when
  all of it is taken, else kept with its rest and its own link, plus one `DtlKey 0` row linked to the
  target). AutoCount applies a PUT all or nothing (plan 61 F8), so no step can leave a line without a
  PO line or lose qty (U13). The new row's location / price / delivery date are put back with the
  existing move step when AutoCount resets them (warning only, the link stays).
- Refusals (nothing sent): `ROW_NOT_FOUND`, `DOC_CANCELLED`, `DOC_KIND_MISMATCH`, `ROW_NOT_LINKED`
  (the SPO line has no PO line), `NO_CHANGE` (target = current PO line), `ROW_RECEIVED` (nothing open),
  `ITEM_MISMATCH` / `UOM_MISMATCH` (same product), `TARGET_RECEIVED` (target PO line fully received),
  `QTY_ABOVE_OUTSTANDING` (the target PO line has less room than the take: its qty minus every SPO line
  already on it, the same guard as `/spo-links/relink`), `DOC_STALE`, `DOC_BUSY`, `VENDOR_UNSUPPORTED`
  (switch off), the write-connection refusals (writes off, non-test book).
- The source PO line keeps its SO link; this op never touches a PO document.
- Locks: the operation's in-progress row holds the SPO; the target PO document lock (`link_locks`) is
  held from the capacity guard to the end, so two moves cannot over-fill one PO line.
- Every vendor call goes through `PrimitiveService` (one call log row per HTTP leg, masked), under the
  operation's idempotency key; replay / resend / resume follow plan 57 / 65 unchanged.

## Switch

`capabilities.VENDOR_CAPABILITIES["spo_move"]`, **False** until the db3 probe proves the SPO PUT
(F14: an SPO cannot be created through the API on db3, so no SPO write was ever probed). Off = refused
`VENDOR_UNSUPPORTED`, nothing sent. Write connections stay test-book only (`guard.assert_test_company`).

## db3 probe (record masked evidence in the PR)

Needs an SPO made in AutoCount on db3 with one line tied to a PO line, plus a second PO line of the same
item. Steps: read; split (take < qty); read back (old line qty - take on PO-A, new line take on PO-B);
whole move of the new line back to PO-A; read back. Tool: `scripts/autocount_spo_move_probe.py`
(refuses any book but db3).

## Slice 2 (crew ruling 20 Nov): the SPO line follows a PO split

The CRM Save runs `/spo-links/move` (the SPO line of the SO's quantity now sits on the chosen PO line), then
Link PO (`/po-links/batch`), which SPLITS that PO line: the linked quantity lands on a NEW PO line. Until this
slice the second call was refused `ROW_ON_SPO`. Now, with the `spo_move` switch on:

- `/po-links/batch` on a PO line that SPO lines sit on is allowed when (a) the split keeps a rest, (b) at least
  one SPO line on the PO line has the SAME quantity as a link (one SPO line per link, request order), (c) the
  kept PO line still has room for the SPO lines that stay on it, and (d) each follower can move as a whole
  (nothing received, not changed since the index, its SPO not busy). Otherwise `ROW_ON_SPO`, nothing sent, as
  before. Switch off = `ROW_ON_SPO`, as before.
- After the PO link PUT (and its restore PUT) the SAME operation sends ONE PUT per follower on its SPO: the old
  SPO line `"D"`, one new line of the same quantity tied to the NEW PO line (the whole-move shape of
  `/spo-links/move`, `PrimitiveService.batch_link`, steps `follow_spo<n>`: one call-log row per HTTP leg).
- The answer gains `spoLines: [{spoDocKey, fromSpoDtlKey, spoDtlKey, fromPoDtlKey, toPoDtlKey, qty}]` (empty
  when nothing followed).
- A follow that did not land: `needs_attention` / `SPO_NOT_FOLLOWED`. The PO links stand and are answered; the
  SPO line still sits on the kept PO line (never without a PO line). Resume reads the SPO first: the new line
  there = confirmed, no PUT; the old line exactly as planned = the one PUT; anything else stays with a person.
  The link PUT is never sent twice.
- Review round 1: an earlier link on the same PO line whose SPO line has not followed yet holds the line (a new
  `/po-links/batch` on it is `ROW_NEEDS_ATTENTION`, nothing sent, until that one is resumed), so a second split
  can never take the SPO line the first planned. Past the operation's time budget no SPO PUT is sent on the
  first run (`SPO_NOT_FOLLOWED`, Resume finishes it). Pending `/spo-links/move` operations onto the PO line
  count against the kept line's room. A follower whose SPO is busy is `DOC_BUSY`.
- Not in this slice (still `ROW_ON_SPO`): a link that takes the WHOLE PO line (AutoCount would have to delete a
  PO line an SPO line points at, unproven, F15), `/po-links/doc-batch` and the single part-row `/po-links`.

### Slice 2 review round 2 (21 Nov, second reviewer + security review; crew ruling: fix on the PR)

- **B1, live book.** The sync job owns every SPO's staged copy on a live book, so the write-back staging left it
  alone and refreshed only the PO index: the SPO index never saw a move or a follow, and the CRM Save (move, then
  split) found no SPO line to carry and left it on the cut PO line. The SPO index now follows the verified
  read-back too (`refresh_spo_links_from_doc`). The db3 test book cannot show this (its test-company guard
  refuses sync-staged companies, so write-back owns the copy there): it is pinned by tests only.
- **Resume re-checks before the SPO PUT** (`_follow_sendable`): every field the PUT sends again
  (`FOLLOW_KEPT_FIELDS` = `payloads.LINE_KEYS` less the transfer markers) still reads as planned, so a hand edit
  is never undone; nothing received on the line (the primitive's own transfer guard does not cover an SPO batch
  PUT); no earlier follow PUT of it with an unknown outcome younger than `LOOKUP_SETTLE_SECONDS` (420 s); room on
  the new PO line (other SPO lines and pending moves counted). Otherwise nothing is sent and a person looks.
- **Pending moves** onto the PO line are counted before the index is consulted (a pending move never updates the
  index), so the round-1 room rule also holds when the index has no row there.
- **The SPO document is held.** Every SPO operation now takes a per-SPO-document lock (`link_locks(spo_doc_keys)`,
  after the PO document locks, before the SO rows), the follow takes it per SPO and re-checks that no other SS
  operation is writing it, and the edit that puts the new SPO line back is built on a fresh read
  (`reuse_read=False`). A move or relink onto the new PO line of a batch with an SPO line still to follow is
  `ROW_NEEDS_ATTENTION` until that batch is resumed.
- **Narrower hold, clearer alert.** The round-1 hold now applies only while an SPO line is still to follow (a
  batch that ended `RESTORE_NOT_LANDED` after its follow landed no longer holds the PO line); the alert names the
  SPO lines a person checks. AC-71-18..24.
