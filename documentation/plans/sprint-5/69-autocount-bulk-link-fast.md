# Plan 69: Bulk PO-SO link, fast (lane BULK-LINK-FAST)

Status: PLAN (19 Nov 2026), contract ask to crew. Size L. UAC: `69-autocount-bulk-link-fast-acceptance-criteria.md`.
Branch off origin/main 8a33b0df. Public repo: no customer names, prices, keys or real document numbers.

## 1. Owner ask (19 Nov ~11:35)

Linking is slow and sometimes fails. Rulings: keep the PO re-read before the write; no 20-line cap error
(any size succeeds by splitting internally); send location / delivery date / note in the FIRST write if
AutoCount keeps them (verify on db3); one `EditPurchaseOrderbydockey` PUT per PO document carrying every
line being linked, instead of one PUT (plus reads) per PO line.

## 2. What the code does today (origin/main 8a33b0df)

Per CRM press, per PO LINE, one `POST /po-links/batch` (`routers/write_v1.py:489-536`, one PO row to 1..20
SO rows, cap `write_v1.py:502-503` + `MAX_BATCH_LINKS = 20` `write_back/operations.py:115`,
refused `INVALID_PARAMS` `operations.py:1344-1345`). Inside one operation (`_batch_link` `operations.py:1366`):

| # | call | where |
|---|------|-------|
| 1 | GET PO (operation read, guards, stale check) | `_batch_locked` `operations.py:1388` |
| 2 | GET SO (once per SO doc, cached in `sources`) | `_line_skip` `operations.py:1505-1510` |
| 3 | GET PO (the primitive's own re-read before the PUT - owner: KEEP) | `primitives._run -> _prepare` `primitives.py:374` |
| 4 | PUT link (old row "D"/cut + one new row per SO row) | `payloads.build_link_batch` `payloads.py:747`, `_send` `primitives.py:772` |
| 5 | GET PO read-back + verify | `_read_back` `primitives.py:822`, `verify_link_batch` `payloads.py:1023` |
| 6 | PUT restore (location, unit price, delivery date, discount, note) | `_restore_rows` `operations.py:1115-1143` |
| 7 | GET PO read-back of the restore | `edit_doc(..., restore=True)` |
| - | push of the whole PO to the CRM sink (not a hapi call) | `prims._stage` `operations.py:1550` |

That is exactly the owner's 11:02 call trace (GET PO, GET SO, GET PO, PUT, GET PO, PUT, GET PO). A PO with
10 lines to link = 10 operations = 20 PUTs + 50 GETs, run serially by the CRM's one worker.

## 3. Answers to the lane questions (evidence)

### Q1 - the ~33 s "Refused by AutoCount" 500s, and can a refused PUT still have applied?

- hapi's own SQL command timeout is 30 s (ADO.NET default); a PUT that waits on a row/table lock held by
  another AutoCount session (a user with the PO open/saving, the CRM's parallel sync read, or our own
  previous PUT still committing) answers a 500 carrying an `ExceptionMessage` after ~30 s + overhead. 33.8 s
  and 32.9 s match that, and the 10:28/10:30 PUTs of 1.9-2.4 s match the un-contended path. UNVERIFIED until
  the two call-log rows' stored `response_json.message` / `vendor_class` are read (crew data ask below:
  `ac_api_call_log` + `ac_write_actions` for that request id, message text masked).
- Today SS treats ANY 5xx JSON body with an `ExceptionMessage` as a business refusal ("nothing landed"):
  `is_business_refusal` `primitives.py:211-220` -> `VENDOR_REFUSED` `primitives.py:796-801` -> operation
  `VENDOR_ERROR`, key released, no read (`operations.py:1446-1448`). That is right for a credit-limit style
  refusal and WRONG for a timeout: AutoCount's PUT is one DB transaction, but a client-side command timeout
  can fire after the server committed, or hapi can fail after its own save. Owner rule (11 Nov): an unknown
  outcome is checked by a read before it is called refused.
- Fix (D3): every non-2xx answer to a link/restore PUT is followed by ONE read of the PO; the stored
  before-read vs that read decides: unchanged -> refused (released, plain reason, Try again); fully landed
  -> carry on as success (restore, stage); anything else -> `needs_attention` (Resume repairs, plan 65 D5).
  No message-word list: the read decides, never the text. Cost: one GET on the failure path only.

### Q2 - dropped

Owner correction 19 Nov ~11:40: the lines did show as linked after 11:02 (the screenshot was older).

### Q3 - the batched contract

See section 4.

### Q4 - press time vs AutoCount time

SS records `ac_write_operations.created_at` (request reached SS) and `updated_at`; each vendor call has its
own row in `ac_write_actions` / `ac_api_call_log` with start + duration. The answer today carries no time.
D5 adds `requestedAt`, `linkedAt` (the link PUT read back as landed) and `finishedAt` (ISO-Z) to every
link answer and to `GET /write-operations/{id}`. The CRM stores its own press time on its job row and shows
"Pressed dd/mm/yyyy, h:mm am/pm" + "Linked in AutoCount dd/mm/yyyy, h:mm am/pm" (paired CRM lane).

### Q5 - expected speed

From the owner's trace (GET 0.2-0.9 s, PUT 1.9-3.2 s un-contended), per PO document:
GET PO + one GET per distinct SO + GET PO (re-read) + PUT link + GET + PUT restore + GET
= 2 PUTs + (3 + distinct SOs) GETs, whatever the line count.

| lines (one PO doc, 1-3 SOs) | today (per line, serial) | after |
|---|---|---|
| 10 | ~10 x 8 s = ~80 s | ~8-12 s (PUT time grows a little with body size) |
| 50 | ~400 s (and >20 per row refused) | ~2 chunks x ~12 s = ~25-30 s |

(PUT size grows with the body; a chunk of `MAX_LINES_PER_PUT` keeps one PUT well under the 30 s lock
window. 50 lines spread over 10 PO documents = 10 doc operations; the CRM may run 2-3 in parallel across
DIFFERENT PO documents (D1), never two on the same document.)

## 4. Decisions / contract (the crew ask)

- D1 New route `POST /po-links/doc-batch` (one PO DOCUMENT, any number of PO rows, each to 1..N SO rows):
  ```json
  {"poDocKey": 1, "docDate": "2026-11-19", "expectedLastModified": null,
   "links": [{"poDtlKey": 11, "soDocKey": 7, "soDtlKey": 71, "qty": "2", "soDocDate": "2026-11-18"}, ...]}
  ```
  Answer (every outcome, 200 / 207-style per-line result inside a 200 when anything landed):
  ```json
  {"operationId": "...", "outcome": "done|needs_attention|pending_verification|refused|vendor_error",
   "errorCode": null, "message": "", "docKey": 1, "docNo": "...",
   "requestedAt": "...Z", "linkedAt": "...Z", "finishedAt": "...Z",
   "lines": [{"poDtlKey": 11, "soDocKey": 7, "soDtlKey": 71, "qty": "2",
              "result": "linked|skipped|failed|checking", "code": null, "message": "", "newPoDtlKey": 99}],
   "freeLines": [{"poDtlKey": 11, "qty": "3"}], "warnings": []}
  ```
  One idempotency key per press per PO document. `po-links/batch` stays unchanged for old callers (it
  becomes a thin call of the same function with one PO row - owner rule: bulk and single share ONE function).
- D2 No cap error. The route accepts any number of links (a body-size guard only, 2000 lines, far above a
  PO's row count). Internally the PO's lines are grouped into chunks of `MAX_LINES_PER_PUT` (default 40 new
  rows per PUT, setting) - each chunk = one link PUT + one restore PUT under the same operation, re-reading
  the PO between chunks (the re-read IS the next chunk's "verify before write"). A chunk that fails stops
  the later chunks (they are `failed` with `NOT_SENT`, retryable); landed chunks stay landed. Per-line skip
  rules (plan 62) are unchanged: a bad line is `skipped` + named, never fails the batch.
- D3 Unknown-outcome read (Q1): non-2xx on any link/restore PUT -> one read, decided by the read (above).
- D4 First-write values. Today PUT 1 already sends the SO row's Location and the note
  (`operations.py:1424-1428`); plan 65 P2 (db3 16 Nov, FXT-1116A..F) found AutoCount resets Location,
  UnitPrice, DeliveryDate and Discount on a NEW SO-linked row whatever PUT 1 sends, so the restore PUT
  exists. Re-probe on db3 (owner: verify): P1 header `Location`/`DeliveryDate` vs row values in PUT 1;
  P2 any extra row field on `EditPurchaseOrderbydockey`'s model (read the hapi swagger on db3) that
  controls the transfer defaults; P3 re-run plan 65 P2 on today's hapi build (a vendor update may have
  fixed the reset). If any shape keeps them, the restore PUT is
  skipped automatically: `_restore_rows` already sends nothing when the read-back shows no drift
  (`operations.py:1127-1131`), so the second write + read-back go away with no new branch. If none keeps
  them, the restore stays but is ONE PUT per chunk (not per line) - the speed win comes from D1/D2.
- D5 Times on the answer (Q4).
- D6 Lock order: SO-row locks for every link in the chunk (sorted, existing `so_row_locks`), plus the PO
  document busy guard (`_check_not_busy`), so two presses on one PO document never interleave.

## 5. Build order (red first)

1. Red: `tests/test_autocount_write_back_doc_batch.py` - 3 PO rows x 2 SO rows = ONE link PUT + ONE restore
   PUT (fake transport counts calls); 45 lines -> 2 chunks, all linked, no cap error; one skipped line named;
   chunk 2 vendor refusal -> chunk 1 lines `linked`, chunk 2 `failed` retryable; 500-after-landing -> read
   shows landed -> `done`; 500-nothing-landed -> refused + released; times present.
2. `payloads.build_link_doc` / `verify_link_doc` (generalize `build_link_batch` / `verify_link_batch` to N
   old rows; the single-row versions call them).
3. `OperationService._doc_batch_*` reusing `_line_skip`, `_restore_rows`, `_batch_done` logic.
4. Router + contract doc `documentation/integrations/autocount/` write API section.
5. db3 probe script for D4 (crew runs on the owner machine: this sandbox has no route to db3 and must never
   reach db1/db2).

## 6. Paired CRM lane (after this contract is approved)

- Group a press by PO document; ONE `po-links/doc-batch` call per PO document (no client-side 20 split).
- Show each line's `result` / plain `message` from `lines[]`; `checking` lines poll
  `GET /write-operations/{id}`; Try again re-sends only `failed`/refused lines with a new key.
- Run 2-3 workers in parallel across different PO documents (never two on one document).
- Store + show press time and `linkedAt` (dd/mm/yyyy, h:mm am/pm).
- Behind the existing ERP write switch; every call already logged SS-side.
