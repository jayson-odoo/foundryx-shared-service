# Feedback item: Share + Follow - behaviour card (lane FEEDBACK-SUBSCRIBE)

Owner 17 Nov ~12:30: "can I send this link to my stakeholder on this request for them to track ... we should add
like subscribe feature also ... they should subscribe it so they get notified".
Owner 17 Nov ~12:35: "wah if every comment view as me, very susah for me to share link eh".
Owner 17 Nov ~12:37 (design, answers card Q1): "generate a general share link, then if they want to like subscribe
or comment or do anything, we prompt something to ask for their phone number, verify if it is linked to the
contacts from CRM then if yes okay they can continue".

Status: card v2 (owner design applied). 3 open questions below. Red tests for the parts no answer changes are next.

## What the code does today (read, not guessed)

- Personal board link `/public/feedback/board/{token}/{FB-n}`: one live link per contact
  (`modules/ideation/services/feedback_links.py` `get_or_create_link`, `mint_board_link`), valid until staff cancel.
  Whoever opens it IS that contact: upvote, comment, "Yours" (`services/portal.py`, principal kind `contact`).
  PR #252 (SS-MULTI-PRODUCT-BOARD) makes it one live link per contact PER PRODUCT; this lane builds on that.
- Per-item status page `/public/feedback/{statusToken}` (`track_url`, `services/sinks.py:62` `mint_idea_link`) is
  also forwardable, and a comment posted there is stamped with the SUBMITTER's name
  (`routers/public_ideas.py:113`, `author_name=...comment_author_name(idea)`). So both links a submitter receives
  today make "every comment view as me".
- WhatsApp status updates: each status change / merge / unmerge writes one `idea_status_events` row per requester
  phone (`services/status_events.py` `_fan_out_recipients` + `_write_event`) with that person's own `board_url`;
  the CRM pulls the feed (and is poked, `services/crm_poke.py`) and sends the WhatsApp message (CRM #2433).
  Comments notify nobody today.
- SS reaches a tenant's CRM through the tenant's `sorento` consumer connection (base URL + `X-API-Key`,
  `services/crm_poke.py:94`). There is no "ask the product about a phone" call yet, and no OTP code in ideation.
- Phone matching is digits-only (`modules/omnichannel/phone.py:17` `digits_only`, used by
  `services/ownership.py:43` `find_contacts_by_phone`): "012-345 6789" and "+60 12-345 6789" do NOT match today.

## Rules

R1. Every item page (board item page, per-item status page, operator item) has a **Share** action that copies the
    item's **share link** `/public/feedback/share/{shareToken}`. One share link per item, the same for everyone;
    it carries no person.
R2. The share link opens the item **read-only for anyone**: title, status pill, details, status timeline, activity,
    comments, upvote count, follower count. Names exactly as the board already shows them (first names), never a
    phone number.
R3. **Any action** on the share view (Follow, Comment, Upvote) first asks for the visitor's **phone number**.
    SS asks **the item's product** whether that phone is one of its contacts (Sorento: a CRM contact with that
    phone). Match -> the visitor is proven (Q1) and **continues as that contact**, on the same item, with their
    own personal board link from then on (own vote, own name, own "Yours"). No match -> Q2.
R4. "Ask the product" is generic, never Sorento code: each product's own connection answers
    `phone -> contact (name, product contact id) | none`. Sorento answers from its CRM contacts (CRM-side endpoint
    needed, see "CRM side"). A product with no lookup configured answers from the SS contacts of that tenant
    (same-phone rule as `find_contacts_by_phone`).
R5. **Phone normalisation** (same spirit as the CRM "dash/space = same code" rule): spaces, dashes, brackets and a
    leading "+" are ignored; a number typed with a leading "0" is read with the tenant's country code
    (Malaysia: "012-345 6789" = "+60 12 345 6789"). One shared function, used by the lookup and the
    existing `find_contacts_by_phone`.
R6. **Follow** is its own button next to Upvote on the item page (reuses the `upvote-box.tsx` sizing and the
    shared `Button`, label "Follow" / "Following"; tapping "Following" unfollows). The follower count shows next
    to it. Upvote does not follow; Follow does not vote.
R7. A follower gets the **same WhatsApp status update** as the submitter, through the same feed and the same CRM
    route (closed 24h window -> the same approved template), with their own board link. Status change, merge and
    unmerge only; comments do not notify. The feed row carries `recipient_role: "requester" | "follower"` so the
    CRM can word it differently later without an SS change.
R8. The submitter is always followed (as today) and never gets a second copy: one message per person per change,
    deduped by phone across submitter, merged children's submitters and followers.
R9. Staff can add a follower on the operator idea detail ("Add follower", shared searchable contact picker,
    tenant contacts only) and remove one (right-click the row -> Remove).
R10. Followers are per item and so per product. A merged item's followers follow the surviving item (same as the
    submitter's update); unmerge leaves them on the item they followed. A follower's link opens that item's
    product board (PR #252), so EcoHub works the same with no product-specific code.
R11. The per-item status page becomes read-only like the share view: its comment box asks for the phone first
    (R3), so nobody comments as the submitter any more. The submitter comments from his own board link.
R12. Test items (`is_test`) have no share link and no Follow. Staff can "Stop sharing" an item (operator "...");
    the next Share mints a new link; an old one shows the existing "link not valid" page. A hidden item's share
    link shows "not found".

## Examples

E1. Dealer A submitted FB-0042 (Sorento). He taps Share, sends the link to his manager B. B opens it: title,
    "Planned", comments by first name, counts; the buttons are there but each asks for a phone.
E2. B taps Follow, types "012-345 6789". Sorento's CRM has a contact with +60 12 345 6789 -> B proves it (Q1) ->
    "Following", count 1, and B is now on FB-0042 through his own board link. A's vote and comments untouched.
E3. Staff move FB-0042 to "In progress": two feed rows (A requester, B follower), each with their own board link;
    the CRM sends both the status update.
E4. FB-0042 is merged into FB-0030: A and B get the existing merged update; B now follows FB-0030.
E5. B taps Follow on EcoHub item FB-0101: EcoHub is asked about his phone, and his update opens his EcoHub board.

## Edge cases

- Lookup unreachable / slow (product down): "We could not check your number right now. Try again." with Try again;
  never let them through unchecked.
- Typing A's own phone on A's share link: A is proven like anyone (Q1) and continues as himself.
- Several product contacts with the same phone: one person (first match by id, same as `find_contacts_by_phone`).
- A product contact with no SS contact row yet: the SS contact is created from the lookup answer (name + phone),
  linked to the product contact id, so the WhatsApp updates have a recipient.
- Cancelling the submitter's link (`cancel_feedback_link_for_idea`) does not touch followers' links.
- Throttle: the phone step has its own bucket (per IP + per phone), never the login bucket; the answer for an
  unknown number never reveals more than Q2 allows.
- Followers list (names) is staff-only; visitors see the count.

## Open questions (owner)

Q1. **Proving the phone is theirs.** Without it, anyone who knows a dealer's number can comment and vote as him.
    (a) WhatsApp 6-digit code: the product sends "Your code is 123456" to that phone, visitor types it on the page,
    continues in place; (b) WhatsApp a link to their own board instead, tapping it proves the phone (visitor
    leaves the page); (c) no proof, phone match alone.
    **Recommend (a)** - matches "prompt, verify, continue" and keeps them on the page. Needs one Meta
    "authentication" template on the product's WhatsApp number (CRM side sends it, same route as status updates);
    code valid 10 minutes, 5 tries. (c) is not safe for upvote/comment.
Q2. **Unknown phone (not a contact of the product).** (a) "This number isn't registered with Sorento. Ask your
    Sorento contact to add you." and nothing else happens; (b) let them in as a new contact (ask their name).
    **Recommend (a)** - it is the owner's "if yes okay they can continue"; staff can add them as a contact and
    they retry. The message names the product, not the reason in tech terms.
Q3. **Does the submitter's personal link change?** (a) no: it stays private and opens his board directly with no
    phone step, exactly as today; Share is a separate link; (b) retire personal links, everyone goes through
    share + phone.
    **Recommend (a)** - zero change for links already sent over WhatsApp; the share link is what gets forwarded.

## CRM side (needed, Sorento only as the first answering product)

- A contact lookup endpoint on the CRM's external API (same `X-API-Key` connection as the status poke):
  `phone -> {contactId, name} | 404`, normalised per R5.
- If Q1 (a): send the code over WhatsApp with an authentication template (same send route as status updates).
- Optional: word follower updates using `recipient_role` (R7).

## Acceptance criteria (draft; ids final once Q1-Q3 are answered)

- AC-FS-1 [BE] Share: one live share token per item; test items refused; Stop sharing cancels it.
- AC-FS-2 [BE] `GET /public/feedback/share/{token}` = read-only item view, no phones; cancelled/hidden = uniform 404.
- AC-FS-3 [BE] Phone step: R5 normalisation; asks the item's product (generic lookup seam, SS-contacts fallback);
  throttled; lookup failure = retryable error, never a pass.
- AC-FS-4 [BE] Proof per Q1, then a contact portal session for that contact on that item's product board.
- AC-FS-5 [BE] Follow/unfollow (contact session), idempotent; follower count on the item.
- AC-FS-6 [BE] Status change / merge / unmerge write one feed row per follower (own `board_url`,
  `recipient_role="follower"`), deduped by phone with requesters; merge moves followers to the survivor.
- AC-FS-7 [BE] Staff add/remove follower; tenant contacts only (422 otherwise); stored contact ids resolved with the
  idea's tenant.
- AC-FS-8 [BE] Status-page comment requires the phone step (R11).
- AC-FS-9 [FE] Item page: Share (copies link), Follow/Following + count; share view with phone prompt dialog;
  375px and 1280px.
- AC-FS-10 [FE] Operator idea detail: Followers list, Add follower picker, right-click Remove.
- AC-FS-11 [E2E] Share -> read-only -> Follow -> phone -> proven -> status change -> follower feed row with own link.
