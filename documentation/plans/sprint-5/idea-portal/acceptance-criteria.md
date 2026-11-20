# IDEA-PORTAL acceptance criteria

Contract for lane IDEA-PORTAL. Tags: [BE] backend, [FE] frontend, [E2E] browser, [T] test-only.
Owner answers (13 Oct): staff only, dealers cannot sign in (Q1); Q2/Q4 crew defaults; Q3 (a) with a manager-editable note; Q5 (b).

## A. Sign-in (portal session)
- AC-P-01 [BE] Given a staff user signed in to shared-service, when they POST `/portal/ideas/session/staff`, then they get a portal token (kind `staff`, role "Staff") for their own tenant. 403 when the ideation module is not active for the tenant.
- AC-P-02 [BE] Given a valid ideation embed token (Sorento CRM user), when it is posted to `/portal/ideas/session/embed`, then a portal token (kind `crm`) comes back with the same tenant and product scope. An invalid token returns 401.
- AC-P-03 [BE] Dealers cannot sign in: there is no link / phone sign-in route.
- AC-P-04 [BE] Every `/portal/ideas/*` read or write without a valid portal token returns 401. A core JWT is not a portal token. A portal token from a tenant whose sign-in is blocked, or whose ideation module is inactive, returns 401.

## B. Visibility
- AC-P-10 [BE] The portal never shows: draft ideas, `is_test` ideas, merged children, or another tenant's ideas.
  - A merged child's id resolves to its survivor on the idea page.
  - An embed (crm) principal on a product-scoped connection sees only that product.
- AC-P-11 [BE] An idea with `portal_hidden=true` is visible only to managers and to its own submitter. `PUT /{id}/hidden` is managers only (403 otherwise).
- AC-P-12 [BE] Managers = shared-service staff with `ideation.triage.manage`, or a Sorento CRM user unless `ideas_manage=false`. `/me` returns `canManage`.

## C. Roadmap
- AC-P-20 [BE] `GET /portal/ideas/roadmap` returns columns in this order:
  - Under review (New, Triaged)
  - Planned (Linked to BR)
  - In progress (Building)
  - Complete (Delivered, Closed)

  Rejected, Duplicate and Archived ideas are not on it.
- AC-P-21 [BE] A tenant status that is not in the default mapping (not initial, not archived) gets its own column, placed by sort order, titled with its label. No idea disappears.
- AC-P-22 [BE] Each card carries: id, idea number, title (falls back to the problem), upvotes, comment count, `isMine`, `myVote`. Cards are sorted by upvotes, highest first. `?mine=true` keeps only the viewer's own ideas; `?productId=` filters by product.

## D. Feedback list and submit
- AC-P-30 [BE] `GET /portal/ideas` supports:
  - `q`: searches the title and the problem
  - `column` (repeatable)
  - `sort=top|new`
  - `mine`
  - `productId`
  - `includeClosed`: shows off-ramp ideas, with their own label

  Results are paginated with `page` / `pageSize` ≤ 100.
- AC-P-31 [BE] `POST /portal/ideas` with title, business problem (required), desired outcome and product creates an idea at captured. The submitter is the viewer: contact or CRM user ownership, or the staff name. Invalid input returns 422.

## E. Changelog
- AC-P-40 [BE] `GET /portal/ideas/changelog` lists delivered ideas, newest first, each with its delivered date and note.
- AC-P-41 [BE] `PUT /portal/ideas/{id}/note` (managers only, ≤ 500 characters) sets the changelog note; a blank note clears it.

## F. Idea page
- AC-P-50 [BE] `GET /portal/ideas/{id}` returns:
  - number, title, status label and colour, column key
  - Business problem (`problem`) and `desiredOutcome` / `useCases` / `currentWorkaround` (null until IDEA-CORE ships them)
  - submitter first name (never a phone number or email), submitted date, product name
  - upvotes, `myVote`, `isMine`
  - a "where is it" timeline over the roadmap columns

  It never returns proposed solution, impact, department, raw text, contact ids or phone numbers.
- AC-P-51 [BE] `POST /portal/ideas/{id}/vote` toggles the viewer's single upvote. Staff vote with their user id and Sorento users with `embed-user:<sub>`: the same ids the operator board and the embed already use, so it is one vote everywhere. Voting on a merged child returns 409.
- AC-P-52 [BE] `GET /portal/ideas/{id}/voters` lists each voter's first name (or null for a legacy vote) and role "Staff", never a phone number or email.
- AC-P-53 [BE] Comments: GET / POST / DELETE (own comment, or any comment for staff). A like toggle on a comment.
  - Comment count is capped at 20 per principal per hour (429).
  - The body is 1 to 2000 characters.
- AC-P-54 [BE] `GET /portal/ideas/{id}/activity?order=desc|asc` returns:
  - submitted
  - status changes (from/to label), backfilled from the existing status-event rows
  - comments and replies
  - upvotes grouped per day
  - comment likes

  The default order is newest first.

## G. Frontend
- AC-P-60 [FE] `/portal/ideas` (Roadmap), `/portal/ideas/feedback`, `/portal/ideas/changelog` and `/portal/ideas/{id}` render the mock-v2 layout at 375 and 1280 with no horizontal scroll.
- AC-P-61 [FE] With no session, the portal shows the sign-in screen ("Staff sign in", which returns to the same portal page). A signed-in shared-service staff user goes straight in.
- AC-P-62 [FE] `/embed/ideas/portal` renders the same tabs inside the Sorento iframe via the existing embed session, with no tenant header.
- AC-P-63 [E2E] A browser pass with real clicks: sign in, Roadmap, open the idea, upvote, comment, reply, like, hide switch, changelog note.

## H. Security
- AC-P-70 [T] A security review of every unauthenticated or portal-token route. Findings are fixed or justified in the PR.
