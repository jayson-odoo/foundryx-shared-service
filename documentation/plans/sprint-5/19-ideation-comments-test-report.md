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
