# IDEA-PORTAL behaviour card v3 (all questions answered)

Mock: `mock-v2.html` (screens 0 to 6 in the top bar). Screenshots at 1280 and 375: `evidence/mock-v2-*.png`. v1 is kept as `mock-v1.html` for history.
Real ideas: IDEA-0010 "Order status tracking for dealers" and IDEA-0014 "Quotation knowledge capture". Everything tagged `sample` is filler, including IDEA-0010's Desired outcome, Use cases and Current workaround: those fields do not exist yet (lane IDEA-CORE).

## Already decided (owner, 13 Oct)
- **Who sees the portal:** sign in required (option b). That means staff plus dealers/contacts. No anonymous voting or commenting.
- **Idea page fields:** Business problem, Desired outcome, Use cases, Current workaround. Proposed solution, Impact and Department are no longer shown.

- **Q1 (owner, 13 Oct): staff only.** The portal is for salespeople and office staff. Dealers / WhatsApp contacts can NOT sign in. Sign-in = the existing staff login: shared-service login, or Sorento CRM users through the existing embed SSO. The dealer identity design below (last 4 digits) is dropped.
- **Q2:** roadmap columns as proposed (crew default).
- **Q3 (owner): (a).** Delivered ideas appear automatically. A manager can edit a one-line changelog note.
- **Q4:** votes and comments as proposed (crew default). Voters show first name + role; every portal user is "Staff".
- **Q5 (owner): (b).** A "Hide from portal" switch on each idea, default off.
- **Managers** (shared-service `ideation.triage.manage`, or a Sorento user whose embed `ideas_manage` claim is not false) can hide ideas, edit the changelog note and delete any comment. Everyone else can only delete their own comments.
- The portal also shows inside Sorento CRM (owner note on mock v1).

## What it does
- **One portal per tenant**, at `/portal/ideas` on the shared-service frontend, with the tenant's branding. It has three tabs, and each tab is its own URL:
  - **Roadmap:** read-only columns with cards. Each card has an upvote box, the idea number, the title, and "Yours" on the viewer's own ideas. There is a Product filter and a "My ideas" toggle.
  - **Feedback:** a Submit form (Title, Business problem, Desired outcome, Product), plus search, a status filter, sort (Top / Newest), and "My ideas".
  - **Changelog:** delivered ideas grouped by month.
- **Idea page `/portal/ideas/<idea number>`** shows:
  - the number, title, status pill, submitted-by first name, date and "Your idea";
  - the four fields;
  - a "Where is it" timeline;
  - voters (first name and role only);
  - a comment box;
  - one activity feed, newest first: submitted, status changes, comments and replies, upvotes grouped by day, likes on comments.
- **Inside Sorento CRM** (screen 5): the same three tabs and idea page, served from `/embed/ideas/portal` through the existing iframe SSO (`app/embed/ideas/embed-app.tsx`). There is no tenant header, and staff and CRM users act as themselves. Sorento only changes the URL its `components/ideas/IdeationEmbed.tsx` loads (or adds a tab next to the current Ideas list).
- **The chatbot link** sent to dealers (`/public/ideas/<token>`) stays the existing public status page (unchanged); dealers are not portal users.
- **The submitter finds their own ideas** through the "Yours" marks, the "My ideas" filter and the timeline.
- **Not shown on the portal:**
  - draft ideas;
  - test ideas (`is_test`);
  - merged children (their link goes to the surviving idea);
  - ideas with an off-ramp status (Rejected, Duplicate, Archived). These appear only in Feedback with the Closed filter on, and on their own idea page.
- **Field names.** I am proposing these to IDEA-CORE and will use whatever they ship:
  - `problem` stays as the column and is labelled "Business problem";
  - new fields `desired_outcome`, `use_cases`, `current_workaround`;
  - on the wire: `desiredOutcome`, `useCases`, `currentWorkaround`.

## Questions (each has a recommendation)

**Q1. How does a WhatsApp contact sign in?**
Staff sign in with their shared-service login. Sorento CRM users arrive through the existing embed SSO.
- (a) The chatbot link alone signs you in as that idea's submitter. This is the easiest, but anyone the link is forwarded to becomes that dealer and sees the whole portal.
- (b) The link, plus "Confirm your WhatsApp number" (the last 4 digits). This needs no new sending channel and stops a plain forward. Wrong tries are throttled per idea and per IP. The session lasts 30 days.
- (c) The link, plus a one-time code that the chatbot sends over WhatsApp. This is the strongest, but it needs a Sorento change, because WhatsApp sending lives in Sorento/Respond.io, not shared-service.

**Recommendation: (b) now, (c) as a follow-up.** It keeps the change inside shared-service and closes the forwarded-link leak.

**Q2 (answered: yes). Which statuses map to which roadmap columns?**
- Under review = New and Triaged
- Planned = Linked to BR
- In progress = Building
- Complete = Delivered and Closed

Rejected, Duplicate and Archived are not on the roadmap. A status a tenant adds later goes into its own column, placed by its sort order, so nothing disappears.

**Recommendation: yes.** The mapping is a code default keyed on the platform status keys, with a fallback for unknown keys.

**Q3. What goes in the Changelog?**
- (a) Delivered ideas only, automatically, with a one-line "what changed" note that staff can edit.
- (b) Manual entries only.
- (c) Both.

**Recommendation: (a).** There is nothing new to author, and it can never go stale. Manual entries go to the backlog.

**Q4 (answered: yes). Voting and comment identity, and spam.**
- One upvote per signed-in person: a staff user, a CRM user, or a contact. Votes can be toggled.
- Downvotes are hidden on the portal.
- The voter list shows first name and role ("Dealer" / "Staff"), never a phone number or email.
- Comments and comment likes are posted as that person.
- Each person is limited to 20 comments per hour. Staff can delete any comment.

**Recommendation: yes.** Comment likes need one new table, `idea_comment_likes`.

**Q5. Ideas with internal detail: should every signed-in dealer see every idea?**
- (a) Yes, every idea of the tenant.
- (b) Add a staff toggle "Hide from portal" on each idea, default off. A hidden idea is visible only to its submitter and to staff.
- (c) Dealers see only their own ideas plus ideas staff marked "Show on portal".

**Recommendation: (b).** It is safe for the ideas that need hiding and needs no extra work for the rest.
