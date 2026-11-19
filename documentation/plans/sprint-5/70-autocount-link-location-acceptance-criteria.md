# Plan 70 - Link PO: optional location from the CRM (acceptance criteria)

Owner ruling 19 Nov: a PO row linked from an Order Inquiry row lands at the OI row's location (for an
order back = the donor location), not the SO line's location. The CRM decides the location; the shared
service only executes. Supersedes the "a linked PO row sits at its SO row" rule (CRM #2429, 15 Nov) for
calls that pass a location. Without a location, behaviour is unchanged.

| ID | Criterion |
|----|-----------|
| AC-70-01 | [BE][T] Given `location` on `po-links` (whole row), when the link lands, then the linked PO row's Location = that code (not the SO row's) |
| AC-70-02 | [BE][T] Given `location` on `po-links` for part of a row (split), then the new linked row lands at that code |
| AC-70-03 | [BE][T] Given `location` on an entry of `po-links/batch` / `po-links/doc-batch`, then that entry's linked row lands at that code; entries without one land at their SO row's location |
| AC-70-04 | [BE][T] Given `location` on `po-links/relink`, then the relinked row lands at that code |
| AC-70-05 | [BE][T] Given `location` on `po-links/relocate`, then the row moves to that code instead of its SO row's location |
| AC-70-06 | [BE][T] Given an unknown location code, then the call is refused `LOCATION_UNKNOWN` (422) before any AutoCount write; nothing is written; the refusal releases the key (retryable) |
| AC-70-07 | [BE][T] Given no / null / blank `location`, then behaviour, answer body and idempotency hash are today's |
| AC-70-08 | [BE][T] `location` is part of the idempotency body (a resend with another location is a different request) |
| AC-70-09 | [BE][T] The location check reads AutoCount through the logged call path (every AutoCount call logged) |
| AC-70-10 | [DOC] The write-link contract (plan 55) documents `location` on each route |
