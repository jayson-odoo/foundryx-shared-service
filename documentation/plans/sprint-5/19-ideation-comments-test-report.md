# Test report: Idea comments, upvote-only voting, next-state primary (sprint-5/19)

UAC: `19-ideation-comments-acceptance-criteria.md`. Plan: `19-ideation-comments.md`. Mock: `documentation/mockups/IDEATION-COMMENTS/index.html`.
Evidence: `19-evidence/` (screenshots + `README.md` run log). Branch `crew/ideation-comments` @ 420f7177.

## Environment

- Backend uvicorn :8017, DB `foundryx_service_ideacomments` built by `scripts.bootstrap_db` (core + module migrations; 0015 applied, table `app_ideation.idea_comments` verified in psql). Frontend fresh build baked to :8017, `next start -p 3017`. Servers stopped afterwards (own PIDs only).
- Driven with `agent-browser --session ic-verify`, headless, real clicks from the sidebar, 1280px and 375px. The public token page URL was typed (it is a link users receive). Tenant `default`, Sorento CRM product, 3 seeded ideas (see README).
- Console: no page errors; only Radix `AlertDialogContent` missing-Description warnings.

## Automated suites (re-run at this HEAD for context)

| Suite | Result |
|---|---|
| `tests/test_ideation_comments.py` + `tests/test_ideation_public_comments.py` | 70 passed |
| `tests/test_ideation_votes_upvote_only.py` | 9 passed |
| vitest: idea-comments, vote-cell, idea-form-fields, use-idea-form and related (5 files) | 50 passed |

Full suites and the kill test belong to the coder/reviewer gates and were not re-run here.

## Results by AC

PASS = observed in the live run. COVERED = backend/unit AC proven by the suites above, plus any incidental live observation. DEFERRED = not exercised in the browser run.

| AC | Result | Evidence |
|---|---|---|
| 19-01 table + migration | PASS | bootstrap_db applied 0015 on live Postgres; `\d app_ideation.idea_comments` lists the columns |
| 19-02 list, oldest first | PASS | thread order in `09-thread-reply-to-reply-1280.png`, `19-operator-sees-public-1280.png`; suite `test_ideation_comments.py` |
| 19-03 create | PASS | `08-comment-added-1280.png`; DB row `author_kind=user`, `author_name=Demo User` |
| 19-04 one reply level | PASS | reply-to-reply stored with top-level `parent_id` (psql), shown in `09-thread-reply-to-reply-1280.png` |
| 19-05 edit own | PASS | `11-comment-edited-1280.png`, `39-comment-edited-375.png` (`edited` marker) |
| 19-06 delete + placeholder | PASS | `13-deleted-with-replies-placeholder-1280.png`, `41-placeholder-375.png`; leaf delete removed from list (psql `deleted_at`) |
| 19-07 canEdit / canDelete | PASS | own comments show Edit+Delete; public comments show Reply+Delete only (`19-operator-sees-public-1280.png`) |
| 19-08 merged child refuses | COVERED | suite only; no merged child in this run |
| 19-09 idea delete removes comments | COVERED | suite only |
| 19-10 embed routes | COVERED | suite only; embed mode not driven (no embed connection) |
| 19-11 permission + grant sweep | COVERED | suite only; demo Admin could comment in the live run |
| 19-12 down vote 422 | COVERED | suite `test_ideation_votes_upvote_only.py`; no down control anywhere in the UI (all vote screenshots) |
| 19-13 down rows ignored | COVERED | suite only |
| 19-14 handoff body upvotes only | COVERED | suite only |
| 19-15 VoteCell box variant | PASS | orange pressed, no down: `02-list-voted-1280.png`, `05-header-unvoted-1280.png`, `33-idea-header-voted-375.png`, `49-board-voted-1280.png` |
| 19-16 idea header box, no Votes row | PASS | `03-idea-page-1280.png`, `33-idea-header-voted-375.png` |
| 19-17 list/board box, sort by upvotes | PASS at 1280 / FAIL at 375 (list) | 1280: `01/02-list-*-1280.png` (voted idea sorts first), board `48/49`. 375: Votes column unreachable in the list, see Findings F1 (`31-list-vote-column-375.png`); board at 375 `47-board-375.png`. CSV column not exported in this run |
| 19-18 Edit beside primary | PASS | `03-idea-page-1280.png`; at 375 wraps to two rows (F3, `33-idea-header-voted-375.png`) |
| 19-19 next-state primary | PASS | `Move to Triaged` (03), then `Move to Linked to BR`, `Move to Building`; gear menu holds Promote/Archive/Delete only (`04-gear-menu-1280.png`, `34-gear-menu-375.png`). Restore/Unmerge variants DEFERRED (suite) |
| 19-20 primary advances + toast | PASS | `14-moved-triaged-1280.png`, `15-moved-toast-1280.png` (`Moved to Linked to BR.`), `35-moved-375.png` |
| 19-21 comments section + composer | PASS | `06-comments-empty-1280.png`, `07-composer-filled-1280.png`, `36-composer-375.png`; datetimes via useDatetime |
| 19-22 replies indented | PASS | `09-thread-reply-to-reply-1280.png`, `37-reply-composer-375.png`, `41-placeholder-375.png` |
| 19-23 edit / delete / Save comment / confirm | PASS | `10/11` (1280), `38/39/40` (375); Cancel on the confirm keeps the comment |
| 19-24 composer hidden without perm / merged; empty `No comments.` | PASS (empty) / DEFERRED (hidden) | empty text in `06-comments-empty-1280.png`; hidden states are suite-only |
| 19-25 layering | COVERED | vitest `idea-comments.test.tsx`; no component fetch |
| 19-26 red-first, kill test | COVERED | commit history (tester red tests); kill test belongs to the reviewer |
| 19-27 E2E at 1280 and 375 | PASS with findings | this report + `19-evidence/README.md`; exception: list vote at 375 (F1) |
| 19-28 public GET | PASS | `16-public-page-empty-1280.png`, `21-public-staff-comment-1280.png`; bad token renders `This link isn't available.` (`22-public-bad-token-1280.png`) |
| 19-29 public POST | PASS | `17-public-posted-1280.png` (author WAWA from submitter_name), `43/44` (375); DB `author_kind=public`, `author_id=public:<idea id>` |
| 19-30 throttle | DEFERRED | 429 toast not triggered; suite `test_ideation_public_comments.py` |
| 19-31 no public edit/delete; operator deletes | PASS | `20-operator-deleted-public-comment-1280.png`, `46-operator-deleted-public-375.png`; `deleted_at` set in psql |
| 19-32 staff name on public, no ids | PASS | `21-public-staff-comment-1280.png` shows `Demo User` with no badge |
| 19-33 public page UI | PASS (merged-child hide, 429 toast DEFERRED) | `17/18` (1280), `43/44` (375); `Comment deleted` placeholder seen on the public page at 375 (`44-public-reply-375.png`) |
| 19-34 badges | PASS | `Visible to submitter` in `07-composer-filled-1280.png`, `Submitter` in `19-operator-sees-public-1280.png`, `18-public-reply-1280.png` |
| 19-35 security review | DEFERRED | security-reviewer seat |

Counts: PASS 24, FAIL 0 outright (1 partial FAIL: 19-17 list vote at 375), COVERED by suites 10, DEFERRED 5.

## Findings

- F1 (partial FAIL, 19-17 / 19-27, 375px list): the Votes column is not reachable. The sticky Idea column is as wide as the table viewport (341px), so Votes scrolls underneath it, and Idea cannot be hidden in the Columns menu (`42-list-columns-menu-375.png`, `31-list-vote-column-375.png`). Pre-existing: the lane's diff to `use-ideas-list-config.tsx` only touches the Votes column. Fix options for the captain: narrower Idea column on mobile, or show the vote box inside the Idea cell below `md`.
- F2 (1280, list): the Votes column is clipped at the table card's right edge until the card is scrolled horizontally (`01-list-1280.png`).
- F3 (375, idea page): Edit and the primary button wrap to separate rows; Edit remains before the primary in order (`35-moved-375.png`).
- F4: the public status page footer reads `Foundryx` (tenant-facing branding rule), pre-existing.
- Console: Radix warning `Missing Description or aria-describedby for AlertDialogContent` on the comment delete confirm; add an `AlertDialogDescription` or `aria-describedby={undefined}`.

## Deferred / unblocks

- 19-30 429 toast and 19-33 merged-child hide: need 6 rapid posts / a merged child seeded; covered by suites.
- 19-24 composer hidden without permission, 19-08/09/10/11/12-14: suite-proven; a role without `ideation.ideas.comment` and an embed connection are needed for a browser run.
- 19-35 awaits security-reviewer.

## Round 2 (HEAD f8216a64, fresh build baked to :8017, evidence in `19-evidence/round2/`)

The frontend was built from a scratch copy of the worktree because another process (`next dev -p 3110`) shares this worktree's `.next`. Servers stopped, own session closed.

| AC | Result | Evidence |
|---|---|---|
| 19-43 Votes first column, visible without scroll, 1280px | PASS | `round2/01-list-1280.png`; vote click toggles without navigating (`02-list-unvote-1280.png`) |
| 19-43 same at 375px (closes F1/F2) | PASS | `round2/03-list-375.png`, `04-list-unvote-375.png`; no horizontal page scroll |
| 19-43 delete dialog description, no Radix warning | PASS | `round2/12-delete-dialog-description-1280.png` ("This comment will be removed."); console after opening the dialog: 0 description warnings |
| 19-40 reply under a deleted top comment, operator | PASS | `round2/05-deleted-root-reply-1280.png`; psql: new reply `parent_id` = the deleted top-level |
| 19-40 same, public page | PASS | `round2/06-public-deleted-root-reply-1280.png` |
| 19-29 public author is the submitter first name | PASS | submitter "Wawa Tan" posts as "Wawa" (`06`, DB `author_name=Wawa`) |
| 19-32 no email on the public page | PASS | nameless staff author (blank user name, stored as the email) shows "Team member"; embed author stored as an email shows "Portal user"; page text and `/comments` JSON contain no "@" (`round2/07-public-no-emails-1280.png`) |
| 19-41 failing Move shows an error toast | PASS | stale page after the status was changed via API: toast "No transition from 'Triaged' to 'Triaged'." (`round2/09-move-failure-toast-1280.png`, backend 409) |
| 19-19 Restore primary on an archived idea | PASS | `round2/10-archived-restore-primary-1280.png`, then click gives "Idea restored." and `Move to Triaged` returns (`11-restored-1280.png`) |
| 19-24 composer hidden without `ideation.ideas.comment` | PASS | user with view + upvote only: thread readable, no composer/Reply/Edit/Delete (`round2/13-no-comment-permission-1280.png`) |
| 19-30 / 19-33 429 toast after repeated public posts | PASS | toast "Too many comments. Try again later." on the 5th post (`round2/08-public-429-toast-1280.png`); backend log shows 429s |

Round 2 notes:
- The embed comment was inserted by SQL (no embed connection in the rig); the embed route itself stays suite-only.
- The view-only user needed `products.read` to open the Ideas list ("Missing permission: products.read"), and its row click did not navigate, so the idea page was opened by URL for that one check. Pre-existing gating, not this lane.
- Same user still sees Edit and `Move to ...` on the idea page; they were not exercised (no triage perm). Worth a look by the reviewer.
- F1 and F2 are closed; F3 (Edit/primary wrap at 375) and F4 (public footer reads "Foundryx") are unchanged.

Round 2 counts: PASS 11, FAIL 0. Still DEFERRED: merged-child hide, embed routes in the browser, AC-19-35 security review.

## Round 3 (HEAD 53c6a87f, frontend built from a refreshed scratch copy, evidence in `19-evidence/round3/`)

| Check | Result | Evidence |
|---|---|---|
| Viewer (view + upvote only): no Edit, no `Move to`/Restore primary, 1280px and 375px (AC-19-46/49) | PASS | `01-viewer-idea-1280.png`, `06-viewer-idea-375.png` |
| Viewer on an archived idea: no Edit, no Restore, no composer | PASS | `04-viewer-archived-1280.png`, `05-viewer-archived-375.png` |
| Viewer: no composer, Reply, Edit or Delete on a thread | PASS | `01`, `03-viewer-voted-1280.png` |
| Viewer: vote box still works | PASS | vote POST 200 at 1280 (`03`) and a toggle at 375 (`07-viewer-vote-375.png`); DB row confirmed |
| Viewer: "..." menu has no Archive/Restore | PASS, with a polish finding | the menu opens with zero items (`02-viewer-menu-1280.png`); see F5 |
| Demo (triage): Edit + `Move to` present; menu = Promote to BR, Archive, Delete | PASS | `08-demo-idea-1280.png`, `09-demo-menu-1280.png`; 375px `12-demo-idea-375.png`, `13-demo-menu-375.png` |
| Demo on an archived idea: Edit + Restore | PASS | `14-demo-archived-375.png` |
| Regression: comment + reply as demo, public page still loads the thread | PASS | `10-demo-comment-reply-1280.png` (reply has the top-level `parent_id` in psql), `11-public-thread-1280.png` (both new comments rendered, no errors) |
| No horizontal scroll at 375px | PASS | viewer idea, viewer archived, demo menu |

Round 3 counts: PASS 9, FAIL 0, one polish finding.

- F5: a user with no idea actions still gets the "..." gear button, which opens an empty menu (`02-viewer-menu-1280.png`). Suggest hiding the trigger when the menu has no items.
- Harness note: mid-run the daemon stopped delivering real mouse input (no pointer/click events reached the page, even after closing and reopening the session). For the remaining steps I fired the same DOM events from script (a click, or a pointerdown/up/click sequence for Radix triggers). Text entry used the normal fill. The vote, comment, reply and menu results above are real app behaviour (backend rows and POSTs confirmed), but the clicks were not physical mouse input.
