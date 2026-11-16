# PUBLIC-IDEAS-BOARD acceptance criteria (shared-service slice)

Owner answers 15 Nov ~10:27: QA a, QB a, QC a, QD a, QE b. Earlier rulings: personal link only, one upvote per contact
(toggle), "Feedback" wording and paths. Design: `reuse-proposal.md`; plan: `plan.md`.
Tags: [BE] backend pytest, [FE] vitest, [E2E] recorded agent-browser run, [T] contract/doc.

## A. Personal link (the credential)
- **AC-FB-01 [BE]** Given a contact in tenant T, when a link is requested for it, then one active link row exists with a
  random URL-safe token (>= 32 chars). Asking again returns the SAME token (no new row).
- **AC-FB-02 [BE]** Given the link was cancelled, when a link is requested again, then a NEW token is minted and the
  old one stays dead.
- **AC-FB-03 [BE]** Given a link for a contact of tenant T, when the stored contact id points at another tenant's
  contact (planted), then no link resolves (tenant-scoped resolution).

## B. Session from the link
- **AC-FB-10 [BE]** `POST /portal/ideas/session/link {token}` with a valid link returns a portal token + principal
  `{kind:"contact", role:"Dealer", name:<first name or null>, canManage:false}`.
- **AC-FB-11 [BE]** Unknown, malformed, or cancelled link -> 401 with the uniform body; suspended tenant or ideation
  module inactive -> 401. Responses carry `no-store`, `noindex`, `no-referrer`.
- **AC-FB-12 [BE]** Cancelling the link kills a portal token already minted from it on its next request (401).
- **AC-FB-13 [BE]** Failed exchanges are throttled per IP (429 + Retry-After after the limit).
- **AC-FB-14 [BE]** A contact principal's first name never carries a phone / email shape (`project_first_name`).

## C. What the contact sees and does
- **AC-FB-20 [BE]** All (list + roadmap) = the staff-portal non-manager set: no draft, test, merged child, or
  `portal_hidden` item (QC a); same tenant only.
- **AC-FB-21 [BE]** `mine=true` = items whose `submitter_contact_id` is the contact or any same-tenant contact with the
  same phone digits; never by name; a hidden own item IS listed; `isMine` marks them.
- **AC-FB-22 [BE]** Upvote = one vote per PERSON: the contact plus every same-tenant contact with the same exact
  phone (the My-requests rule) count as one voter, so a second contact row cannot add a second vote; a WhatsApp
  vote by any of them is "my vote"; voting again removes it; new votes are stored under one canonical contact id so
  two of the person's links racing still collide on the unique vote guard.
- **AC-FB-23 [BE]** The contact can comment (role "Dealer", first name) and delete its own comment; cannot delete
  others'.
- **AC-FB-24 [BE]** Submit, hide, and changelog-note are refused for a contact (403) (QB a).
- **AC-FB-25 [BE]** Detail of an item from another tenant, or a draft/test/hidden-not-mine item -> 404.

- **AC-FB-26 [BE][FE]** Owner ruling (b), strict (15 Nov + crew-pass): on items the link owner did not create the
  API OMITS (never null) `problem`, `desiredOutcome`, `useCases`, `currentWorkaround`, `submitterFirstName`,
  `submittedAt`, `productName` (cards: `submittedAt`, `productName`), drops the "submitted by" activity line, never
  falls back to the problem text as a title (the number stands in), and search never matches others' text. The page
  then shows only title, status, steps, votes and comments. Own items and staff unchanged.
- **AC-FB-27 [FE]** Item links in the Feedback list, Roadmap and Changelog carry the item NUMBER (the row id only
  for an item with no number yet).

## D. Links we send
- **AC-FB-30 [BE]** `mint_board_link(idea)` = `{base}/public/feedback/board/{linkToken}/{ideaNumber}` for an idea with a
  same-tenant submitter contact; `None` when the idea has no contact. Tenant base with a `{token}` template ->
  `{origin of the template}/feedback/{linkToken}/{ideaNumber}` (the CRM public page).
- **AC-FB-31 [BE]** Every `idea_status_events` payload carries `board_url` (the requester contact's link) next to the
  unchanged `track_url`.
- **AC-FB-32 [BE]** The WhatsApp intake reply's "Track it here" link is the REPLYING contact's board link (never the
  idea author's when the replier has no contact), else the old per-idea link. Test ideas never mint a link
  (superseded 17 Nov: see `test-filing-board-link-acceptance-criteria.md`). The
  one-shot / own-similar APIs keep the per-idea link (they answer the host). Old `/public/ideas/{token}` pages keep
  working.
- **AC-FB-33 [BE]** `POST /ideation/ideas/{id}/feedback-link/cancel` (`ideation.triage.manage`, plus the grace-window
  action "Cancel feedback link" on the staff idea page) cancels the links of the idea's submitter contact and its
  same-phone sibling contacts; tenant-scoped; 404 for another tenant's idea. One live link per contact is
  database-enforced.

## E. Frontend (shared-service board, link mode)
- **AC-FB-40 [FE]** `/public/feedback/board/{token}` exchanges the link once and renders the existing Roadmap / Feedback /
  Changelog / item views; the Submit form is absent; the toggle reads "My requests"; wording says "Feedback".
- **AC-FB-41 [FE]** `/public/feedback/board/{token}/{number}` opens that item; a bad link shows "This link is not valid".
- **AC-FB-42 [FE]** The token is kept in memory only (never localStorage).
- **AC-FB-43 [E2E]** Real clicks at 375 and 1280: open a link -> item -> upvote on/off -> My requests -> comment.

## F. Contract
- **AC-FB-50 [T]** `board_url` documented for lane FEEDBACK-STATUS-WA; CRM `/feedback/board/{token}` page contract written.
