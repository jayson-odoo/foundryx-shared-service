# 67 - AutoCount stranded operations, part B (behaviour card)

Lane AUTOCOUNT-STRANDED-OPS-B. Follows ss#250 (AUTOCOUNT-STRANDED-OPS), whose report left three items open.
Owner rules on record: a failed write is retryable, a refusal releases its key, only a confirmed success
locks, an unknown outcome is looked up before a retry, every AutoCount call is logged, no extra guards.
Every example below is db3-shaped (the test book); no live book is touched by this lane.

## Rules

R1 (B). A single-document write (edit document, add line, delete line, cancel) whose answer is unknown
(`pending_verification`: the crash sweep flipped it, or the call timed out / the read-back failed) is looked
up before the same-key resend is answered. The lookup reads the document once (logged under the operation)
and asks only whether THIS write's change is there (`payloads.change_landed`): asked values read back as
asked, the added line is among the new rows, the deleted line is gone, the document reads cancelled. It never
judges the rest of the document: another person may have edited it since, and judging that would add a line
twice.
- the change is in AutoCount -> the operation ends `done` and stays locked; the answer carries the document;
- the change is not in AutoCount -> the operation ends `recovered` / `OPERATION_NOT_APPLIED`, its key is
  released, and the resend runs fresh (re-read, re-guarded);
- the document cannot be read -> the stored answer stands (`pending_verification`), never "in progress";
- the write never reached AutoCount (no request sent) -> released at once, no read.
A crashed run that is still `in_progress` past the busy window is first flipped to `pending_verification`
by the same-key resend (as operations already do, C.a), then looked up.

R2 (C). Every refusal keeps releasing the key (unchanged, pinned by a test for the shipping-PO case).
The shipping-PO refusal (`ROW_ON_SPO`) now always carries plain reason text in `message`, on the link
operations, the batch link and the single-line primitives alike, from ONE shared function:
"This purchase order line is on shipping purchase order SPO-0001, so the change was not made. Remove it from
that shipping purchase order first, then try again." (document number named when the index knows it,
otherwise "a shipping purchase order").

R3 (A). Time budget: the server keeps its 270 s operation deadline. Recommendation: accept + poll, using
what already exists: when the CRM's 60 s wait ends it shows "Still working in AutoCount" and resends the
SAME key (or GETs `/write-operations/{operationId}`) every 10 s, up to 5 minutes. While the run is live the
resend answers `409 OPERATION_IN_PROGRESS` without calling AutoCount; once it ends the resend replays the
stored answer. No SS change is needed for this; the CRM slice (item D) owns it.

## Examples (db3-shaped)

1. Edit PO 7001 (Remark) is sent; the worker is killed after the PUT. Sweep flips it pending. CRM presses
   Try again with the same key: SS reads PO 7001, the Remark matches -> `done`, locked. No second PUT.
2. Add line to PO 7001; worker killed after the action went in flight but AutoCount never saved. Same-key
   resend: SS reads PO 7001, no new matching line -> `recovered`, key released, the line is added fresh
   (one POST), answer `done` with the new line key.
3. Delete line 9002 of PO 7001 times out (`pending_verification`, TIMEOUT). Same-key resend: line 9002 is
   gone -> `done`. If the line is still there -> released, the delete runs fresh.
4. Link PO row 9001 that an SPO row points at: `409 ROW_ON_SPO`, message names the SPO. The user removes it
   from the SPO, presses Try again with the SAME key: the key was released, the link runs fresh -> `done`.
5. Edit lookup while AutoCount is unreachable: answer stays `pending_verification` with the plain message
   "AutoCount could not be reached to check this change. Please try again shortly."

## Edge cases

- A timed-out PUT may still land in AutoCount after the timeout. "Not found" is trusted only once the write is
  older than the vendor's write timeout plus margin (150 s); before that the answer stays
  `pending_verification` ("AutoCount has not confirmed this change yet...") and nothing is sent again.
- A write whose own action already confirmed `done` (the worker died before the operation stored it) locks
  as `done` without a re-read: only a confirmed success locks, and that one is confirmed.

- Another body under the same key is still `IDEMPOTENCY_CONFLICT`; no lookup runs.
- A young `in_progress` run (inside the busy window) still answers `OPERATION_IN_PROGRESS`.
- Rows written before this lane carry no operation link on their action: the lookup finds the in-flight action by
  key, kind, document and time window; zero or several candidates -> the stored answer stands (nothing proves
  either way).
- Create keeps its own lookup (plan 62); delete document is out of scope (its read-back is a not-found).
- An edit AutoCount partly ignored (`FIELD_IGNORED` on re-check) counts as "not in AutoCount": the fresh run
  reports the mismatch itself.

## Answers (crew, from the owner's 11 Nov rulings)

Q1 (a) accept + poll; Q2 every pending single-document write; Q3 (a) release the key and run fresh;
Q4 yes, name the SPO document number. The CRM card part (shipping-PO reason, Try again with the same key,
polling) is a separate CRM slice; its contract is in the crew ask on the PR.

## Questions (each with a recommendation)

1. Time budget: (a) accept + poll with the same key, (b) a sub-60 s server budget. Recommend (a): a 60 s
   budget turns every slow AutoCount PUT into `pending_verification` and a lookup; polling costs nothing.
2. Look up every pending single-document write, or only sweep-flipped ones? Recommend every pending one: the
   owner rule says an unknown outcome is checked before retrying, whatever made it unknown.
3. Change not found on lookup: release and run fresh, or mark needs attention? Recommend release: nothing
   proves the change landed, and the fresh run is re-read and re-guarded (owner: no extra refusals).
4. Shipping-PO wording: name the SPO number when known? Recommend yes (a document number, not an id).
