# IDEA-PORTAL behaviour card v1

Mock: `mock-v1.html` (open in a browser; screens 0 to 5 in the top bar).
Screenshots at 1280 and 375: `evidence/mock-v1-*.png`.
The sample ideas are made up. The sandbox cannot reach the dev database, so I wrote realistic Sorento dealer ideas instead.

## Already decided (owner, 13 Oct)
- **Who sees the portal:** sign in required (option b). That means staff plus dealers/contacts. No anonymous voting or commenting.
- **Idea page fields:** Business problem, Desired outcome, Use cases, Current workaround. Proposed solution, Impact and Department are no longer shown.

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
- **The chatbot link** (`/public/ideas/<token>`, and the tenant link template) now opens this idea page inside the portal.
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

**Q2. Which statuses map to which roadmap columns?**
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

**Q4. Voting and comment identity, and spam.**
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
