# Ideation requester status-update event feed - CRM contract

**Issue:** #94 (round 2) plan section 7, Appendix A. **AC:** AC-94-61..72.

This document is the contract between the shared-service ideation module
(publisher) and the sorento CRM (consumer/sender). This service publishes
events; it holds no WhatsApp credentials and sends nothing itself - the CRM
pulls the feed and sends the "ideation status update" template.

## 1. What produces an event

One `idea_status_events` row per notifiable recipient, written inside the
transaction that caused it:

- **Every stage change** (any status-engine edge fired on an idea) writes a
  `kind = "status_changed"` row for the moved idea, PLUS one for each merged
  child's requester (a survivor's move is announced to every child's
  requester too) - deduped by distinct phone, the survivor's own row winning
  a collision. **Exception:** a move whose FROM status `is_initial` (only
  `draft` today) writes nothing - the live WhatsApp chat already replied to
  capture/cancel/"vote with existing" in that same turn.
- **Merge** writes one `kind = "merged"` row per merged member that has a
  requester (never for the survivor itself).
- **Unmerge** (a child unmerge, a survivor unmerge dissolving its whole
  group, or a survivor delete which unmerges first) writes one
  `kind = "unmerged"` row per restored idea that has a requester, deduped by
  phone within that one unmerge call (never for the former survivor).
- An idea with **no requester** (no `submitter_contact_id`, or the contact
  resolves to no phone, or the stored contact id is not this tenant's - a
  defensive polymorphic-id guard) never gets a row.
- A failing writer never breaks the triggering request - the event write
  rides the CRUD event bus's isolated post-commit dispatch (for
  `status_changed`) or the merge/unmerge service's own transaction; either
  way the status/merge/unmerge change itself always commits.

## 2. The feed

```
GET /ideation/intake/status-events?after=<seq>&limit=<n>&includeTest=<bool>
Authorization: Bearer <workspace API key>
```

- Auth: the same workspace API key already used for
  `POST /ideation/intake/create-idea`. Tenant is derived from the key, never
  from the request. A missing or invalid key is `401`.
- `after` (default `0`): only rows with `seq > after`.
- `limit` (default `100`, max `200`).
- `includeTest` (default `false`): excludes `is_test` rows unless `true`.
- Response:

```json
{ "events": [ { ...one payload per row, see section 3... } ], "next_after": 812 }
```

`next_after` is the last returned `seq` (or the given `after` unchanged when
the page is empty) - the CRM persists it as its cursor and passes it back as
`after` on the next poll.

### Ordering, idempotency and the settle window

- At-least-once delivery. `seq` (a Postgres `SERIAL`) ascends in commit
  order; `event_id` is unique per row - the CRM dedupes on `event_id` and
  processes events ascending.
- The feed **withholds any row younger than 5 seconds** (a settle window).
  Without it, a slower-committing transaction with a lower `seq` could land
  AFTER the CRM's cursor has already moved past a higher `seq` from a
  faster-committing transaction, and be skipped forever. A poller running
  every 60 seconds (Appendix A) never notices the 5-second hold.
- The feed starts at the table's first row - there is no historical replay
  for a CRM that connects late; events simply accumulate harmlessly until
  the CRM side is deployed.

### Test ideas

Console/`--say` test ideas (`is_test = true`) write their event exactly like
a real one (so the test lane can verify the pipeline), but the feed excludes
`is_test` rows unless the caller explicitly passes `includeTest=true`. The
CRM's OWN contract (Appendix A) adds a second guard: never send a real
WhatsApp message when `is_test` is true, even if it somehow saw the row.

## 3. Payload (exact keys - `test_event_payload_exact_keys`)

Snake_case (the server-to-server intake convention), one object per feed
item:

```json
{
  "event_id": "5c9b...-uuid",
  "seq": 812,
  "kind": "status_changed",
  "occurred_at": "2026-09-28T09:10:00Z",
  "idea_id": "idea-uuid",
  "idea_number": "IDEA-0031",
  "idea_title": "Faster quotation",
  "product_id": "product-uuid",
  "status_label": "Discussed",
  "from_status_label": "New",
  "track_url": "https://<frontend>/public/ideas/<token>",
  "requester_phone": "+60123456789",
  "merged_into": null,
  "separated_from": null,
  "is_test": false
}
```

| Field | Notes |
|---|---|
| `kind` | `status_changed` \| `merged` \| `unmerged`. |
| `status_label` / `from_status_label` | The status engine's current LABEL (never a hardcoded key) - `from_status_label` is only meaningful for `status_changed` (`null` for `merged`/`unmerged`). For `status_changed` both are the MOVED idea's edge; every recipient in that fan-out (the moved idea and any merged children) shares the same pair. |
| `idea_id` / `idea_number` / `idea_title` / `track_url` | Always the **recipient's own** idea - a merged child's requester gets ITS OWN idea's number/title/link, not the survivor's. |
| `merged_into` | `null`, or `{"idea_number", "title"}` of the survivor - set only when the recipient is a merged child announcing the survivor's stage change or its own `merged` event. |
| `separated_from` | `null`, or `{"idea_number", "title"}` of the FORMER survivor - set only on an `unmerged` event. |
| `requester_phone` | The recipient's own resolved contact phone (tenant-scoped lookup - never a cross-tenant stored id). |
| `is_test` | Copied from the recipient idea, independent of the idea that triggered the fan-out. |

## 4. Merge and unmerge semantics (owner Q3, 28 Sep 2026)

- **Merge:** B (has a requester) merged into A produces one `merged` event
  for B: `merged_into = {A.idea_number, A.title}`, `status_label` = A's
  CURRENT label (the survivor's stage at merge time). No event for A.
- **Unmerge:** B unmerged from A (via a child unmerge, a survivor unmerge, or
  a survivor delete) produces one `unmerged` event for B:
  `separated_from = {A.idea_number, A.title}` (the FORMER survivor),
  `merged_into = null`, `status_label` = B's OWN restored label (B's status
  never moved while merged - it was frozen, so this is simply B's live
  status at the moment of unmerge). No event for A.
- **A survivor's own stage change** fans out to every merged child's
  requester too (`status_changed`, `merged_into` set for each child),
  deduped by phone across the whole group with the survivor's own row
  winning a collision.

## 5. CRM (sorento) side - summary of Appendix A

(Full brief: plan section "Appendix A", `PLAN-ideation-round-2-merge-unmerge.md`.)

1. New template use case `ideation_status_update` (Utility category,
   approved). Suggested body: `"Update on your idea {{1}}: it is now {{2}}.
   Track it here: {{3}}"` with `{{1}} = idea_number` (fallback `idea_title`),
   `{{2}} = status_label`, or for `kind = "merged"` "combined with
   {merged_into.idea_number}", or for `kind = "unmerged"` "handled
   separately again from {separated_from.idea_number}, now {status_label}",
   `{{3}} = track_url`.
2. A poller calls the feed every 60 seconds, `after=<persisted cursor>`,
   processes events ascending, persists the cursor only after each event is
   handled.
3. Idempotency: unique `event_id` in the CRM's own integration log; skip
   already-seen ids (this feed is at-least-once).
4. Guards before send: `is_test` true never sends (log only); an opted-out
   requester is skipped + logged; the Respond.io contact is resolved by
   `requester_phone`.
5. Always send the approved template (business-initiated, outside the 24h
   customer-service window) - never attempt free text.
6. Every send/skip is logged in the CRM's integration log with `event_id`,
   idea number, template and result.
