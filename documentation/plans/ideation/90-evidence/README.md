# Issue #90 browser evidence run log

**Re-run 2026-09-26 (this revision)** against branch head `b2989bd6`
(backend `fbb55009` review round 2 + frontend `b2989bd6` review round). The
first run (superseded) was captured at `65fbabe3`, BEFORE the review-round
fixes below existed - every shot in this revision replaces the stale one.

Worktree `foundryx-shared-service-ideapage`. Private lane: backend `:8015`
(venv from the main checkout, `service_backend/.env` is a lane COPY, not a
symlink), frontend `:3015` (`npx next start -p 3015` against `.next` built
fresh from this branch), Postgres DB `foundryx_service_ideapage`, Redis db
15. `agent-browser --session s52`, viewports 375x812 and 1280x900.

**Lane restart for this re-run:** confirmed pid ownership via `lsof -p <pid>
| grep cwd` (both pids' cwd resolved into this worktree) before killing;
`python -m scripts.bootstrap_db` afterwards showed no pending ideation
migration (`app_ideation.alembic_version_ideation` stayed at
`0011_ideation_br_is_test`, matching the coordinator's "0011 unchanged"
note); `rm -rf .next && npm run build` then `npx next start -p 3015` for the
frontend.

Logged in as `demo@example.com` / `demo1234` at `localhost:3015` (default
tenant, Admin) - the same agent-browser session/cookies survived the lane
restart, no re-login needed.

## What changed in the review-round fixes (why every shot needed a re-run)

- **`IdeaHero`** (`idea-hero.tsx`): a null `title` used to fall back to
  `Idea <number>`; review fix S5 changed the fallback to the `problem` text
  (truncated via `ClampedText`) - the number line above no longer repeats
  itself as the heading.
- **`PublicIdeaFooter`**: now renders the shared `BrandMark` component (the
  same one the header's branded shell uses) instead of whatever produced a
  broken image in the prior build.
- **`_first_name()` phone/email guard** (`public_status.py`, review round 2):
  NFKC-normalizes the WHOLE raw name first, checks the WHOLE string for
  5+ digits or `@` (not just the first whitespace token) - closes the
  fragment leak where a phone split across tokens by spaces/hyphens
  (`+60 12-345 6789`) left an individual token too short to trip a
  token-only digit count.
- **`GET /public/ideas/{token}`**: now also sets `X-Robots-Tag: noindex`
  and `Referrer-Policy: no-referrer` on the 200 (in addition to the
  pre-existing `Cache-Control: no-store`).
- **`seed_br_template`**: rewritten to a three-part idempotent repair (row
  exists -> version exists -> active pointer valid), each independently
  self-healing, run on every `bootstrap_db` - this is what the W2 recovery
  screenshots (`ev-15`/`ev-16`) exercise below.

## Data setup (what's real-click vs DB-assisted)

Same three ideas as the first run, now with title/submitter tweaks:

| Idea | Problem | Title | Submitter | Status |
|---|---|---|---|---|
| IDEA-0001 | Customers cannot filter reports by date range | **"Add date-range filters to the reports dashboard"** (titled) | Aisha Rahman | Linked to BR |
| IDEA-0002 | WhatsApp reminders arrive too late for shift swaps | *(null - fallback case)* | **"+60 12-345 6789"** (fragment-proof phone probe) | New |
| IDEA-0003 | No dark mode option anywhere in the app | *(null - fallback case)* | Demo User | New, `is_test=true` |

**DB-assisted steps this round, and why:**

- **Title on IDEA-0001** ("Add date-range filters to the reports
  dashboard") was set directly in the DB. Checked first: the idea edit
  form (`use-idea-form.tsx`'s `toFormValues`/`IdeaFormValues`) and the
  backend `IdeaUpdateIn` schema (`schemas.py`) both omit `title` entirely -
  there is no UI path to set it. Title is only ever populated by the real
  WhatsApp conversational intake (an LLM-derived headline), which this
  local lane has no live WABA sandbox to drive. DB write was the only
  option, as instructed.
- **IDEA-0001's status was DB-reset to `captured`** (back to "New") before
  re-driving it forward, because the status-engine's edge graph is
  forward-only (no `Linked to BR -> Triaged` edge) - the prior run had
  already advanced this idea, so reproducing the "early status" shot for
  THIS idea required a reset. The actual New -> Triaged -> Linked to BR
  transition shown in `ev-03`/`ev-04` was driven by real dnd-kit
  drag-and-drop on the Triage board (pointer-sequence, not the single-shot
  `drag` command).
- **IDEA-0002's `submitter_name`** was updated to the exact probe format
  the coordinator specified, `"+60 12-345 6789"` (previously
  `"+60123456789"`), to exercise the NEW fragment-proof guard specifically
  (a phone split across three whitespace tokens by spaces/hyphens - the
  first token alone, `"+60"`, has only 2 digits, under the old check's
  per-token threshold).
- The BR template's `active_version_id` was nulled directly in
  `app_ideation.ideation_artifact_templates` for the "inactive" dialog
  shots, per the brief. For the **recovery** shots
  (`ev-15`/`ev-16`), it was NOT manually restored - `python -m
  scripts.bootstrap_db` was run against the lane `.env`
  (`DATABASE_URL=.../foundryx_service_ideapage`) and its own idempotent
  `seed_br_template` repair reactivated the pointer (see the SQL log line
  below). This proves the actual W2 fix, not a manual DB patch.
- `is_test=true` on IDEA-0003 is unchanged from the first run (still no
  chatbot-console dev tool exists in this codebase - confirmed again this
  round).

## The W2 recovery, and the log line proving it

Sequence: (1) `New requirement` dialog confirmed normal with the template
active (`ev-11`/`ev-12`) -> (2) `active_version_id` nulled directly in the
DB -> (3) dialog reopened, confirmed the Alert + disabled Create
(`ev-13`/`ev-14`) -> (4) **`python -m scripts.bootstrap_db`** run against
the lane DB (no manual restore) -> (5) dialog reopened again: no Alert,
`Create draft` enabled (`ev-15`) -> (6) a title was typed and Create draft
clicked, producing a real "Draft requirement created." toast and a new BR
row `d4dc9ed2-42de-4149-8e64-22a89110b326` (`ev-16`).

The exact SQL line from the `bootstrap_db` run (SQLAlchemy echo) proving
`seed_br_template`'s repair fired:
```
UPDATE app_ideation.ideation_artifact_templates
SET active_version_id=%(active_version_id)s, updated_at=now()
WHERE app_ideation.ideation_artifact_templates.id = %(app_ideation_ideation_artifact_templates_id)s
-- params: {'active_version_id': 'ee3c954c-e599-48d9-9a53-de511c7ff4a0',
--          'app_ideation_ideation_artifact_templates_id': '24927667-ca29-4bbb-8c3b-89a0a840daa2'}
```
Confirmed via direct query immediately before/after: `active_version_id`
went `NULL` -> `ee3c954c-e599-48d9-9a53-de511c7ff4a0` (the template's own
v1 row) purely from running bootstrap - no manual UPDATE in between.

## Response headers (curl, both origins, re-verified this round)

Backend `GET /public/ideas/<token>` (`:8015`), on the 200:
```
cache-control: no-store
x-robots-tag: noindex
referrer-policy: no-referrer
```
(`x-robots-tag` and `referrer-policy` are new this round - confirmed
present, matching the router's two added `response.headers[...]` lines.)

Frontend `GET /public/ideas/<token>` (`:3015`):
```
Cache-Control: private, no-cache, no-store, max-age=0, must-revalidate
```
Page `<head>` (unchanged):
```html
<meta name="referrer" content="no-referrer"/>
<meta name="robots" content="noindex, nofollow"/>
```

## Screenshots

| File | Proves | AC-90 id(s) |
|---|---|---|
| `ev-01-public-page-current-status-375.png` | IDEA-0001 (titled) public page at 375px, status "New": branded header, idea number, the SET TITLE as heading (not the old `Idea IDEA-0001` fallback), status pill + timeline, problem/solution/impact/department, "Submitted by Aisha - date - 5 votes", next-step line, proper Foundryx wordmark footer (not broken) | AC-90-101/102/108/110/112 |
| `ev-02-public-page-current-status-1280.png` | Same, 1280px | AC-90-101/102/108/110/112 |
| `ev-03-public-page-later-status-375.png` | Same idea re-dragged New -> Triaged -> Linked to BR on the Triage board (real dnd-kit drag): timeline done/current/upcoming states, title still correct, footer wordmark correct | AC-90-102/103/110/111/112 |
| `ev-04-public-page-later-status-1280.png` | Same, 1280px | AC-90-102/103/110/111/112 |
| `ev-05-public-page-phone-guard-375.png` | IDEA-0002, `submitter_name = "+60 12-345 6789"` (fragment-proof probe): no "Submitted by" line at all; heading falls back to the problem text (null title case) | AC-90-105/106 |
| `ev-06-public-page-phone-guard-1280.png` | Same, 1280px | AC-90-105/106 |
| `ev-07-public-page-empty-fields-375.png` | IDEA-0003 (null title, only Problem set): heading = problem text (fallback confirmed post-fix), Proposed solution/Impact/Department = "Not provided" | AC-90-101/104/110 |
| `ev-08-public-page-empty-fields-1280.png` | Same, 1280px | AC-90-101/104/110 |
| `ev-09-public-page-unknown-token-375.png` | Syntactically-valid but non-existent token: uniform "This link isn't available." | AC-90-107/109 |
| `ev-10-public-page-unknown-token-1280.png` | Same, 1280px | AC-90-107/109 |
| `ev-11-br-dialog-template-active-375.png` | "New requirement" dialog, template active (normal), 375px: no Alert, Create draft enabled | AC-90-210 |
| `ev-12-br-dialog-template-active-1280.png` | Same, 1280px | AC-90-210 |
| `ev-13-br-dialog-template-inactive-375.png` | Same dialog after `active_version_id` nulled via DB, 375px: warning Alert "No active requirement template" / "Ask an administrator to restore the Business Requirement template.", Create draft disabled | AC-90-210/211 |
| `ev-14-br-dialog-template-inactive-1280.png` | Same, 1280px | AC-90-210/211 |
| `ev-15-br-dialog-recovered-after-bootstrap-1280.png` | Dialog reopened AFTER `python -m scripts.bootstrap_db` (no manual DB restore) - no Alert, title filled, Create draft enabled | AC-90-202/203 |
| `ev-16-br-created-after-recovery-1280.png` | "Draft requirement created." toast + the new BR's edit page, proving Create actually works post-repair | AC-90-202/203 |
| `ev-17-ideas-list-test-badge-375.png` | Ideas list, "Show test ideas" on (table scrolled right to bring the TEST column into view at this width - the resource-shell grid does not reflow narrower than its column set): IDEA-0003 shows a TEST badge | AC-90-310/311 |
| `ev-18-ideas-list-test-badge-1280.png` | Same, 1280px (no scroll needed) | AC-90-310/311 |
| `ev-19-br-detail-test-badge-375.png` | The promoted test BR's detail page: TEST badge next to "Draft" | AC-90-313 |
| `ev-20-br-detail-test-badge-1280.png` | Same, 1280px | AC-90-313 |
| `ev-21-br-list-show-test-375.png` | Business requirements list, "Show test requirements" on: TEST badge on the test BR row (also shows the real `d4dc9ed2` recovery-proof BR alongside it) | AC-90-310 |
| `ev-22-br-list-show-test-1280.png` | Same, 1280px | AC-90-310 |
| `ev-23-idea-brs-tab-test-badge-375.png` | **New this round**: the test idea's OWN "Business Requirements" tab (on the idea detail page, not the BR list) shows the TEST badge on its linked BR row | AC-90-313 |
| `ev-24-idea-brs-tab-test-badge-1280.png` | Same, 1280px | AC-90-313 |

## Defect / backlog status (re-checked, not re-filed)

Both findings from the first evidence run were already triaged by the
coordinator's backend round (confirmed in
`ideation-public-idea-page-br-template-test-report.md` §3):

1. **Operator-authored ideas never get a public track link**
   (`create_operator` never mints `idea_number`/`status_token`) - filed as
   **BL-SS-280**, deferred pending a product decision. Re-checked this
   round: still true (`IdeaUpdateIn`/`use-idea-form.tsx` still have no
   title field either, consistent with this being the WhatsApp-only path
   by design).
2. **The "No active requirement template" Alert has no link to a template
   admin page** - this is **not a defect**: no such admin page exists yet
   (Q1's ruling), and **BL-SS-278** tracks building it. The Alert's actual
   copy, "Ask an administrator to restore the Business Requirement
   template.", is the correct interim behaviour.

No new defects found this round - all review-round fixes (title fallback,
footer wordmark, fragment-proof phone guard, hardening headers, seed
recovery) verified working exactly as intended by direct browser
inspection.
