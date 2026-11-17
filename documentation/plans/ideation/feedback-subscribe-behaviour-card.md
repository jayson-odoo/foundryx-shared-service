# Feedback item: Share + Follow - behaviour card (lane FEEDBACK-SUBSCRIBE)

Owner 17 Nov ~12:30: "can I send this link to my stakeholder on this request for them to track ... we should add
like subscribe feature also ... they should subscribe it so they get notified".
Owner 17 Nov ~12:35: "wah if every comment view as me, very susah for me to share link eh" - loosens the 15 Nov
"personal link only, no open board URL" rule FOR SHARING ONE ITEM.

Status: behaviour card, waiting on the crew-ask answers. No code yet.

## What the code does today (read, not guessed)

- Personal board link `/public/feedback/board/{token}/{FB-n}`: one live link per contact
  (`modules/ideation/services/feedback_links.py` `get_or_create_link`, `mint_board_link`), valid until staff cancel.
  Whoever opens it IS that contact: upvote, comment, "Yours" (`services/portal.py` kind `contact`).
  PR #252 (SS-MULTI-PRODUCT-BOARD) makes it one live link per contact PER PRODUCT; this lane builds on that.
- Per-item status page `/public/feedback/{statusToken}` (the `track_url`, `services/sinks.py:62` `mint_idea_link`)
  is ALSO forwardable, and a comment posted there is stamped with the SUBMITTER's name
  (`routers/public_ideas.py:85-118`, `author_name=...comment_author_name(idea)`). So today BOTH links a submitter
  receives let a stakeholder speak as the submitter. That is the owner's "every comment view as me".
- WhatsApp status updates: every status change / merge / unmerge writes one `idea_status_events` row per
  requester phone (`services/status_events.py` `_fan_out_recipients`, `_write_event`), with that person's own
  `board_url`; the CRM reads the feed and sends the WhatsApp message (CRM #2433). Comments notify nobody today.
- There is no OTP / verification-code code anywhere in ideation; WhatsApp sending for the board lives in the CRM.

## Rules

R1. Every item page (board item page and per-item status page) gets a **Share** action that copies a **share link**
    `/public/feedback/share/{shareToken}` for that one item. The share link carries no person.
R2. A share link opens the item **read-only**: title, status pill, the item's details, status timeline, activity and
    comments, upvote count, follower count. It shows exactly the names the item page already shows (first names
    of commenters, never phone numbers). No upvote, comment or Follow is possible on the read-only view.
R3. To **upvote, comment or follow** from a share link, the visitor taps the action, enters their phone and proves
    it (see Q2). They then land on the same item through **their own** personal board link (their own "Yours",
    their own vote, their own name on comments). The submitter's personal link is never shown or handed out.
R4. **Follow** is a separate button next to Upvote on the item page (reuses `upvote-box.tsx` sizing + `Button`
    variant `outline`; label "Follow" / "Following"). Tapping "Following" unfollows (no confirm). The follower
    count shows next to it. Upvoting does NOT follow; following does NOT vote.
R5. A follower gets the **same WhatsApp status update** as the submitter, through the same feed and the same CRM
    route (closed 24h window -> the same approved template), with **their own** board link in it. Status changes,
    merge and unmerge only; comments do not notify (standing rule "notify only when the receiver has something
    to do").
R6. The submitter is always followed (implicitly, as today) and is never sent a second copy. One person = one
    message per change: recipients are deduped by phone across submitter, merged children's submitters and
    followers.
R7. Staff can add a follower from the operator idea detail ("Add follower", the shared searchable contact picker,
    tenant contacts only) and remove one (right-click the follower row -> Remove). Same rules as a self-follow.
R8. Followers are per item. When an item is merged, its followers follow the surviving item (same as the
    submitter's update already does); unmerge keeps them on the item they followed.
R9. Multi-product: an item belongs to one product, so a follow is per product item; the follower's link is minted
    for that item's product (PR #252 `mint_board_link`), so an EcoHub follower lands on the EcoHub board.
    Nothing is Sorento-specific.
R10. Test items (`is_test`) cannot be shared or followed (no share link, Follow hidden); their feed rows are
    already filtered.
R11. Staff can cancel an item's share link (operator item "..." -> "Stop sharing"); the next Share mints a fresh one.
    Opening a cancelled share link shows the existing "link not valid" page.

## Examples

E1. Dealer A submitted FB-0042 (Sorento). He taps Share on its board page, copies the link and sends it to his
    manager B. B opens it: sees title, "Planned", comments by first name; no Upvote/Comment/Follow active, a
    single "Follow / comment" button.
E2. B taps Follow, enters his phone, proves it (Q2). B lands on FB-0042 on his own Sorento board, button shows
    "Following", count 1. A's board is unchanged; A's vote is not B's.
E3. Staff move FB-0042 to "In progress". The feed gets two rows: A (requester) and B (follower), each with their
    own board link. The CRM sends both the same status template. B's message reads per Q4.
E4. FB-0042 is merged into FB-0030. A gets the existing "merged" update; B gets the same, linking FB-0030 on B's
    own board. B now follows FB-0030.
E5. B is also an EcoHub user and follows EH item FB-0101: that update links B's EcoHub board (green), not Sorento.

## Edge cases

- Phone not known to the tenant (never chatted): see Q3.
- The person proving the phone is the submitter himself: he lands on his own link (no follow row needed).
- A follower whose contact is later deleted: no row is written (same as a requester with no contact today).
- Same person, several contact rows with the same phone (`ownership.find_contacts_by_phone`): treated as one
  follower; cancelling the submitter's link (`cancel_feedback_link_for_idea`) does not touch followers' links.
- Share link of an item later hidden by staff: shows "not found" (same as the board's hidden rule).
- Rate limits: the phone step uses its own throttle bucket (per IP + per phone), never the login bucket.
- Followers list is staff-only (contacts see the count, not the names/phones).

## Questions for the owner (one recommendation each)

Q1. **Share link = read-only for anyone, act as yourself after a phone check?** (owner 12:35 loosening.)
    (a) yes: per-item share link, read-only; Follow/Upvote/Comment asks for the phone and opens the visitor's own
    link; (b) no share link, staff add followers only.
    **Recommend (a)** - it is exactly the "send this link to my stakeholder" ask and keeps the 15 Nov rule that a
    personal link is never shared. Nothing in the code blocks it: `PublicIdeaStatusService` already serves a
    tokened read-only item view we can reuse for the read part.
Q2. **How does the visitor prove the phone?** (a) we WhatsApp them their own personal link ("Tap to follow
    FB-0042"), the tap proves the phone; (b) a 6-digit WhatsApp code typed on the page.
    **Recommend (a)** - same proof (only the phone's owner receives it), no new code screen, and it rides the
    route the CRM already uses for board links; (b) needs a separate Meta "authentication" template approved per
    WhatsApp number plus a code store/expiry, for no extra safety. Either way the reply is the same uniform
    "Check WhatsApp" whether or not the number is known (no number probing).
Q3. **Phone the tenant has never seen?** (a) create the contact (name asked on the page) and send the link;
    (b) only existing contacts, others see "Check WhatsApp" and nothing arrives.
    **Recommend (a)** - a stakeholder is often not yet a contact (the manager never chatted with the business).
    Flag: this lets a public page create contacts, so it is throttled per IP + per phone, and the contact is only
    marked as following once the WhatsApp link is tapped.
Q4. **Follower wording.** (a) same template, the CRM adds "(you follow this request)"; (b) a separate follower
    template "Update on FB-0042 you follow: now In progress. View: <link>".
    **Recommend (a)** for the first cut: the feed row carries `recipient_role: "requester" | "follower"`, the CRM
    can pick wording later without an SS change; closed-window sends go through the same approved template.
Q5. **Should the existing per-item status page stop letting visitors comment as the submitter?** (a) yes: its
    comment box becomes the same "Follow / comment" phone step (read-only otherwise); (b) leave it as is.
    **Recommend (a)** - the status page link (`track_url`) is forwarded just as easily, and today it stamps every
    visitor comment with the submitter's name (`routers/public_ideas.py:113`), the exact "comment view as me"
    problem. The submitter keeps commenting from his own board link.

## Acceptance criteria (draft, keyed after the answers)

- AC-FS-1 [BE] `POST` share on an item mints/returns one live share token per item; test items refused.
- AC-FS-2 [BE] `GET /public/feedback/share/{token}` returns the read-only item view; no phone numbers; cancelled
  or hidden = uniform 404.
- AC-FS-3 [BE] Phone step: uniform response, throttled, sends the visitor's own board link (Q2/Q3).
- AC-FS-4 [BE] Follow / unfollow from a contact portal session; idempotent; follower count on the item.
- AC-FS-5 [BE] Status change, merge, unmerge write one feed row per follower (own `board_url`,
  `recipient_role="follower"`), deduped by phone with the requester.
- AC-FS-6 [BE] Merge moves followers to the survivor; tenant-scoped everywhere (stored contact ids resolved with
  the idea's tenant).
- AC-FS-7 [BE] Staff add/remove follower (perm `ideation.ideas.manage`), tenant contacts only (422 otherwise).
- AC-FS-8 [FE] Item page: Share (copies link), Follow/Following toggle + count; read-only share view with one
  "Follow / comment" button; 375px and 1280px.
- AC-FS-9 [FE] Operator idea detail: Followers list + Add follower picker + right-click Remove.
- AC-FS-10 [E2E] Share -> open read-only -> follow by phone -> status change -> follower feed row with own link.
