# 71 - AutoCount: move / split an SPO line onto another PO line (SPO-LINK-PO-SS)

Status: Build. Partner lane: CRM SPO-LINK-PO (the CRM Save calls this, then the existing Link PO).
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
  the `TRANSFER_STATE_UNKNOWN` warning, same as relink). `qty <= 0` = `INVALID_PARAMS`.
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
