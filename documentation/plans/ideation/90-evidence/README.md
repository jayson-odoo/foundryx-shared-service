# Issue #90 browser evidence run log

Worktree `foundryx-shared-service-ideapage`, branch `fix/public-idea-page-and-br-template`,
head `65fbabe3`. Private lane: backend `:8015` (venv from the main checkout,
`service_backend/.env` is a lane COPY, not a symlink), frontend `:3015`
(`npx next start -p 3015` against `.next` built from this branch), Postgres
DB `foundryx_service_ideapage` (created with `createdb -O foundryx`), Redis
db 15. `agent-browser --session s52`, viewports 375x812 and 1280x900.

Logged in as `demo@example.com` / `demo1234` at `localhost:3015` (default
tenant, Admin). Installed the `ideation` module for the default tenant via
the App Store UI (Actions -> Install), real clicks - it showed
"Module not installed" on `/ideation/ideas` before that.

## Data setup (what's real-click vs DB-assisted)

Three ideas were captured through the app's "Capture idea" dialog (real
clicks): product "Dreamz EMS Reports Module" was created first (also via
the UI, Products > Add product), since the capture dialog requires one.

| Idea | Problem | Submitter | idea_number / token |
|---|---|---|---|
| IDEA-0001 | Customers cannot filter reports by date range | Aisha Rahman | `mfGsQf0Pf6uYnqlgVicJlbO1Mz5VU8j0` |
| IDEA-0002 | WhatsApp reminders arrive too late for shift swaps | +60123456789 (phone-guard case) | `Z3O55b9GMERT8WV5pWJxlCp4cz-iEL_l` |
| IDEA-0003 | No dark mode option anywhere in the app (only the required Problem statement filled) | Demo User | `l13MU-_D-TGYWA3ilYfqh8x4LaCTluLs` |

**DB-assisted steps, and why:**

- `submitter_name` on IDEA-0001 ("Aisha Rahman") and IDEA-0002
  ("+60123456789") was set directly in the DB. The "Capture idea" dialog
  (operator-authored path, `IdeaActionService.create_operator`) has no
  submitter field - it always stamps `submitter_name` from the logged-in
  actor ("Demo User"). To exercise the real-name path and the phone-guard
  path from the public page's `_first_name()` logic
  (`services/public_status.py` AC-90-105/106), a submitter name had to be
  set directly.
- `idea_number` / `status_token` were minted by calling the real
  `modules.ideation.services.numbering.mint_idea_identity(db, idea)`
  function from a one-off Python shell against the lane DB (not raw SQL) -
  see **Defect candidate #1** below for why this was necessary.
- 4 extra `idea_votes` rows (+1 real UI upvote click = 5 total) were
  inserted directly for IDEA-0001, to show "a few upvotes" on the public
  page; the UI only allows one vote per logged-in user, so a second voter
  cannot be produced by clicking as the same admin.
- `is_test=true` was set directly on IDEA-0003 for the W3 test-BR flow.
  **The brief's "chatbot console" is not available in this local lane** (no
  such UI/dev endpoint exists in this codebase - only the real WhatsApp
  conversational intake mints test ideas via `--say`, which needs a live
  WABA sandbox). DB `is_test` flip was used instead, as the brief allowed.
- The BR template's `active_version_id` was nulled then restored directly
  in `app_ideation.ideation_artifact_templates` for the W2 inactive-state
  screenshot, per the brief's explicit instruction.

IDEA-0001 was then moved **New -> Triaged -> Linked to BR** on the Triage
board via real dnd-kit drag-and-drop (`agent-browser` pointer-down /
pointer-move sequence, not the single-shot `drag` command, which dnd-kit's
collision detector needs to register).

## Response headers (curl, both origins)

Backend `GET /public/ideas/<token>` (`:8015`):
```
cache-control: no-store
content-type: application/json
```

Frontend `GET /public/ideas/<token>` (`:3015`):
```
Cache-Control: private, no-cache, no-store, max-age=0, must-revalidate
```
Page `<head>`:
```html
<meta name="referrer" content="no-referrer"/>
<meta name="robots" content="noindex, nofollow"/>
```
All four confirm the public page is never cached and never indexed, and
never leaks a referrer to the linked-out `Foundryx` mark's own site (none
present) or any outbound link.

## Screenshots

| File | Proves | AC-90 id(s) |
|---|---|---|
| `ev-01-public-page-current-status-375.png` | IDEA-0001 public page at 375px: branded header (product name), idea number + title, status pill "New", timeline with "New" highlighted, problem/solution/impact/department sections, "Submitted by Aisha - date - 5 votes", "what happens next" line, Foundryx footer mark | AC-90-102/103/104/105/108 |
| `ev-02-public-page-current-status-1280.png` | Same, 1280px (two-column layout) | AC-90-102/103/104/105/108 |
| `ev-03-public-page-later-status-375.png` | Same idea after being dragged New -> Triaged -> Linked to BR on the Triage board: timeline shows New/Triaged done (checkmarks), Linked to BR current, Building/Delivered upcoming; pill + next-step line updated | AC-90-102/103/108 |
| `ev-04-public-page-later-status-1280.png` | Same, 1280px | AC-90-102/103/108 |
| `ev-05-public-page-phone-guard-375.png` | IDEA-0002 (`submitter_name = "+60123456789"`): the "Submitted by ..." line is suppressed entirely - proves `_first_name()`'s phone-shape guard never publishes a phone number | AC-90-105/106 |
| `ev-06-public-page-phone-guard-1280.png` | Same, 1280px | AC-90-105/106 |
| `ev-07-public-page-empty-fields-375.png` | IDEA-0003 (only Problem statement set): Proposed solution / Impact / Department each render "Not provided" | AC-90-104 |
| `ev-08-public-page-empty-fields-1280.png` | Same, 1280px | AC-90-104 |
| `ev-09-public-page-unknown-token-375.png` | A syntactically-valid but non-existent token: uniform "This link isn't available." state, no enumeration hint | AC-90-107/109 |
| `ev-10-public-page-unknown-token-1280.png` | Same, 1280px | AC-90-107/109 |
| `ev-11-br-dialog-template-active.png` | Business requirements > "New requirement" dialog with the platform BR template active (normal): no Alert, Product + Title fields, "Create draft" enabled | AC-90-210 |
| `ev-12-br-dialog-template-inactive.png` | Same dialog after `active_version_id` was nulled: warning Alert "No active requirement template" / "Ask an administrator to restore the Business Requirement template.", "Create draft" disabled (see Defect candidate #2) | AC-90-210/211 |
| `ev-13-ideas-list-test-badge.png` | Ideas list with "Show test ideas" toggled on: IDEA-0003 shows a TEST badge; toggled off by default it is excluded (checked before this shot) | AC-90-310/311 |
| `ev-14-br-page-test-label.png` | IDEA-0003 promoted to a BR via Actions > "Promote to BR" (not refused, per the owner's 26 Sep ~12:50Z ruling): the BR detail page shows a TEST badge next to "Draft" | AC-90-311/313 |
| `ev-15-br-list-show-test.png` | Business requirements list with "Show test requirements" on: the promoted BR shows its TEST badge; off by default it was excluded (checked before this shot) | AC-90-310 |

## Defect candidates found during this run

1. **Operator-authored ideas never get a public track link.**
   `IdeaActionService.create_operator` (`services/actions.py`) sets
   `submitter_name` from the actor but never calls
   `numbering.mint_idea_identity`, which is the ONLY thing that mints
   `idea_number` / `status_token` outside of the one-time migration 0010
   backfill and the WhatsApp conversational intake sink
   (`services/sinks.py: ideation_on_complete_sink`). Every idea created
   through the app's own "Capture idea" dialog therefore has
   `idea_number = NULL` and `status_token = NULL` forever - it can never
   be shared via `/public/ideas/<token>` because no token is ever minted.
   For this evidence run the real `mint_idea_identity` function was
   invoked directly against the lane DB to produce tokens (see Data setup
   above) - this is NOT something achievable by an operator through the
   UI today. Confirmed by reading `services/actions.py` lines 89-111 and
   `services/sinks.py`; `IdeaOut` deliberately never surfaces
   `statusToken` to an authenticated read (by design, security-motivated),
   so there is also no in-app way to discover a link even if one existed.
   Whether this is intentional (only WhatsApp submitters are meant to get
   a trackable link) or a gap worth closing (an operator typing up a
   phone-in idea for a customer would want to hand them a track link too)
   is a product call - flagging for the coder/owner rather than assuming.

2. **The "No active requirement template" Alert has no link to the
   template admin page**, despite the brief's W2 wording ("the dialog must
   say what to do ... link to the template admin page"). The actual copy
   (`br-create-dialog.tsx` / `br-template-error.ts`,
   `NO_TEMPLATE_MESSAGE`) is plain text: "Ask an administrator to restore
   the Business Requirement template." - no `<a>`/link anywhere in the
   dialog (confirmed via `document.querySelectorAll('a')` in the live
   DOM). The logged-in user in this test (Demo User) IS the tenant Admin,
   so "ask an administrator" is not actionable guidance for the very role
   that could fix it from `/settings/templates`. See
   `ev-12-br-dialog-template-inactive.png`.

Both are reported as findings, not fixed - per the tester role, no
application code was changed.
