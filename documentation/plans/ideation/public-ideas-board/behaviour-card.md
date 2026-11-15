# PUBLIC-IDEAS-BOARD behaviour card v2 (waiting for owner answers)

Owner ask (15 Nov): a Canny-like public page, no login, where a contact sees all items with their status and also
"my issue / my feature / my request / my feedback". Every link we send a contact about an idea goes there.

Mock: `mock-v1.html` (5 screens in the top bar, width toggle 1280 / 375). Screenshots: `evidence/mock-v1-*-{1280,375}.png` (v2 mock follows this card).
Examples come from masked dev rows (crew extract 15 Nov: main dev DB + two lane copies; no production data).

## What exists today (cited on origin/main)
- Per-IDEA public page `/public/ideas/{status_token}`, no login (`routers/public_ideas.py:37`,
  `services/public_status.py`): status, timeline, next step, upvotes, comments, submitter first name only
  (`project_first_name`, `public_status.py:70`).
- WhatsApp intake replies "Track it here: {link}" with that per-idea link (`services/sinks.py:62 mint_idea_link`,
  `services/intake.py:1072`); status-change messages reuse it (`services/status_events.py:112`).
- The list / roadmap is the staff portal `/portal/ideas` (sign-in, staff only - owner Q1 of 13 Oct,
  `documentation/plans/sprint-5/idea-portal/behaviour-card.md`). Visibility rules there: never draft, `is_test`,
  merged child; `portal_hidden` only for managers + own submitter (`services/portal.py:446`).
- `Idea.submitter_contact_id` (omnichannel contact, per workspace) links an idea to the contact who filed it.
  Contacts are per workspace, so one phone can be several contact rows in one tenant (`Contact.phone_digits`).
- Types: `idea_types` catalog, today `idea` and `issue` (`models.py:123`, PR #235).

## Mock element -> component it reuses
| Mock element | Reused component |
|---|---|
| Header (tenant logo or tenant NAME), footer | `app/(public)/public/ideas/[token]/components/public-idea-header.tsx`, `public-idea-footer.tsx` |
| All / My requests tabs | `components/ui/tabs.tsx` |
| List + one toolbar row (Search, Filters, Columns), server sort/filter/pagination | standard DataGrid `components/ui/data-grid*.tsx` (+ `data-grid-column-visibility.tsx`); no Create button, the board is read-only |
| Status pill | `components/platform/idea-portal/portal-status-pill.tsx` |
| Item popup | `components/ui/dialog.tsx` wrapping `idea-hero.tsx`, `next-step-callout.tsx`, `idea-status-timeline.tsx`, `idea-detail-sections.tsx` from the public idea page |
| "No requests yet", "This link is not valid" | `components/platform/idea-portal/portal-states.tsx` |
| Backend visibility + first-name rules | `PortalService._visible` (`services/portal.py:446`), `project_first_name` (`services/public_status.py:70`), timeline/next-step from `PublicIdeaStatusService` |

## Rules (proposed)
1. **New page `/public/ideas/board/{contactToken}`** (shared-service frontend, tenant branding, no login).
   - Tabs: **All** and **My requests**. Toolbar: Search, Type filter (multi), Status filter (multi), Sort (Top, Newest).
   - Click an item: its detail opens in a centred popup: number + status pill, type, title, first name, submitted date,
     Business problem, timeline, next step, upvotes. `?idea=IDEA-0012` in the address bar opens it directly.
2. **All** = every idea the staff portal shows a non-manager: not draft, not `is_test`, not a merged child (its
   survivor is listed), not `portal_hidden`, not an off-ramp status unless the Status filter picks it. Same tenant only.
3. **My requests** = ideas whose `submitter_contact_id` is one of the token's contacts (rule 6). Shows hidden
   (`portal_hidden`) ones too, because they are the contact's own. A merged child shows with its survivor's status and
   "Merged into IDEA-00xx".
4. **What never leaves the server:** phone, email, contact id, internal notes, assignee, priority, BR links, CRM ids,
   other submitters' full names (first name only, via the existing `project_first_name`). The list response carries no
   field the item popup does not show.
5. **Contact token:** random (`secrets.token_urlsafe(24)`, same as `status_token`), stored per (tenant, contact) in a new
   module table `app_ideation.idea_contact_links` with `revoked_at`. Read-only: it can view, nothing else (no vote,
   no comment, no submit from the board). Wrong / revoked / unknown token, suspended tenant, module off = the same 404
   page as today. `noindex`, `no-store`, `no-referrer`, throttled per IP.
6. **Who "me" is:** the contact the token was minted for, plus any contact in the same tenant with the exact same
   normalized phone (`phone_digits`). Never by name.
7. **Links we send:** `mint_idea_link` returns `/public/ideas/board/{contactToken}?idea={ideaNumber}` when the idea has a
   `submitter_contact_id`; otherwise the old per-idea link. Old `/public/ideas/{status_token}` links keep working
   unchanged. No message wording changes.
8. **Ideas with no number** (staff, web and embed creates are not numbered today; only WhatsApp captures are) still
   list, with Number "-", and open by click. Only numbered ideas can be opened straight from a link.
9. **Draft and test ideas never show, not even in My requests.** A contact's own draft or test idea is left out.

## Examples (masked dev rows)
1. **WhatsApp dealer, one idea.** Dealer A sent "Remind me before a DO SLA breaches" (Feature request, New). Their link
   opens the board with that idea's popup. My requests: 1 row. All: every non-hidden tenant idea, first names only.
2. **Same phone, two contacts.** Dealer B's phone belongs to 2 contact rows (two workspaces). Dealer B filed "I want a
   mobile app so field staff can log deliveries offline" from one of them. Opening Dealer B's link from either contact
   shows it under My requests (exact phone match, never name).
3. **Two ideas, shared phone.** Dealer C filed "add an Export-to-Excel button on the orders list" and "a dark mode
   toggle for the whole app"; their phone is also on a second contact. My requests: 2 rows.
4. **Test ideas are never public.** Dealer E's two WhatsApp ideas (IDEA-0016 "The AI assistant currently cannot
   retrieve or provide invoices..." Feature request; IDEA-0049 "Asking for the <Brand> promo returns the <Brand B>
   promo instead." Issue) are both marked test. Dealer E's My requests: "No requests yet". All: neither row.
5. **Drafts are never public.** "a brand new test idea about export scheduling" is a Draft linked to a contact: it is
   not in that contact's My requests and not in All.
6. **Staff / web ideas with no contact.** "Let CS bulk-export orders to Excel - with column presets" (manual) and the
   four "ZZT CP2 235 ..." rows (manual, no number) have a submitter name but no contact: they show in All (Number "-",
   first name only) and in nobody's My requests (see Q4).
7. **Rows titled "test" that are not marked test** (manual / embed rows, `is_test` off): they show in All like any idea.
   The board never guesses from the title; staff mark them test or hide them.

## Edge cases
- **Token expiry / revoke:** no expiry (same as `status_token` today, links in old chats keep working); staff revoke
  from the contact (new token minted on the next link). See Q3.
- **Contact with no items:** empty My requests with plain "No requests yet"; All still works.
- **Private / internal items:** `portal_hidden`, draft, `is_test` never on All. See Q2.
- **Filed by staff on behalf of a contact:** shows in My requests only when the idea's `submitter_contact_id` is set;
  a staff create with only `submitter_name` is not linked to anyone (no joining by name). See Q4.
- **Multiple contacts, same phone:** real in dev (2 of 5 linked dealers share a phone with another contact); joined by
  exact `phone_digits` within the tenant (rule 6).
- **One contact, many companies:** companies live in the CRM, the board knows the contact only: all of that contact's
  ideas show, whatever company they were raised for.
- **Forwarded link:** whoever holds it sees that contact's My requests (same exposure as today's per-idea link). No
  phone or email is ever shown, so the leak is limited to idea content.
- **Tenant whose `public_link_base_url` is a CRM template** (`{token}` placeholder, `sinks.py:54`): keeps today's link
  untouched until the CRM side adopts a `{contactToken}` placeholder (second PR, sorento_crm).

## Questions (one answer each, recommendation first)
**Q1. Who can open the board?**
(a) Only through a link we sent (contact token in the URL); no bare tenant URL. (b) Anyone with the tenant's board URL,
token only adds My requests.
**Recommendation (a):** idea text then only reaches contacts we already talk to, not search engines or competitors.

**Q2. Which ideas does All show?**
(a) The same set as the staff portal, minus ideas staff hid with the existing "Hide from portal" switch (one switch,
relabelled "Hide from portal and public board"). (b) A new per-idea "Show on public board" switch, default off.
**Recommendation (a):** one switch, no backlog of ideas to approve one by one. Note: this publishes the Business problem
of every non-hidden idea to every contact with a link.

**Q3. Contact link lifetime?**
(a) Never expires; staff can revoke it per contact. (b) Expires after 90 days; a new message carries a fresh one.
**Recommendation (a):** dealers open old WhatsApp links weeks later; a dead link there reads as broken.

**Q4. Ideas staff file for a dealer.**
(a) Add a "Submitter contact" picker to the staff create / edit form so they land in that dealer's My requests.
(b) Leave staff-filed ideas out of My requests in this lane.
**Recommendation (b) now, (a) as a follow-up:** keeps this lane to the board; nothing links by name.

**Q5. Type labels and filter.**
(a) Use the existing catalog: "Feature request" (key `idea`) and "Issue" (key `issue`); "feedback" and "request" are
not separate types. (b) Add Feedback and Request as new types.
**Recommendation (a):** the intake classifies into these two today; new types need intake and CRM changes.
