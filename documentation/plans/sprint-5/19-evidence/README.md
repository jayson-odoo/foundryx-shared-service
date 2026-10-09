# Plan 19 evidence: idea comments, upvote-only voting, next-state primary (AC-19-27)

Run log, 2 Oct 2026, lane IDEATION-COMMENTS, branch `crew/ideation-comments` @ 420f7177.

## Rig

- Backend uvicorn :8017 from the worktree; DB `foundryx_service_ideacomments` built by
  `scripts.bootstrap_db` (core + module migrations incl. 0015 applied; `app_ideation.idea_comments` present).
- Frontend: fresh `rm -rf .next && npm run build` with the :8017 env baked in, `npx next start -p 3017`.
- Tenant `default`, login demo@example.com. The ideation module was installed via the App Store API
  (the fresh DB had it uninstalled); product "Sorento CRM"; 3 ideas created via `POST /ideation/ideas`:
  "I want a mobile app so field staff can log deliveries offline" (submitter WAWA),
  "Let CS bulk-export orders to Excel with column presets", and
  "Public status check: dealer wants WhatsApp reminder for quotation follow-up" (submitter WAWA,
  status_token + IDEA-0003 set directly in the dev DB; the token page is the one URL typed).
- Driver: `agent-browser --session ic-verify`, headless, real clicks from the sidebar. Viewports 1280x900 and 375x800.
- Console after every surface: no page errors. Only Radix warnings
  (`Missing Description or aria-describedby for AlertDialogContent`, from the delete confirm dialog).
- No horizontal page scroll at 375 on the idea page, public page and board (`scrollWidth <= innerWidth` true).

## Run log (1280)

1. 01 list: Votes column renders the box; 02 click vote on the mobile-app idea: box turns orange, count 1, row sorts first (votes desc).
2. 03 idea page: vote box in the avatar slot left of the title, `Edit` outline button left of `Move to Triaged`, no `Votes` row in Details.
3. 04 gear menu: Promote to BR, Archive, Delete only. 05 header unvote (box neutral, 0) then vote again (orange, 1).
4. 06/07 empty state `No comments.`, composer with `Visible to submitter` badge, Comment disabled until text.
5. 08 comment posted; reply posted; reply-to-reply posted: 09 shows it indented under the top-level (DB: both replies have the top-level `parent_id`).
6. 10/11 edit own reply: button reads `Save comment`, `edited` marker appears. 12 delete confirm; Cancel keeps it.
7. 13 delete the top-level that has replies: `Comment deleted` placeholder with replies still shown; deleting a leaf removes it from the list.
8. 14/15 `Move to Triaged` advances; label becomes `Move to Linked to BR`, toast `Moved to Linked to BR.`, then `Move to Building`.
9. Public page `/public/ideas/<token>`: 16 empty thread; 17 post (author WAWA with `Submitter` badge); 18 reply under it.
10. 19 operator page shows both public comments with `Submitter` badge and Reply/Delete only (no Edit); a staff comment is added.
    20 operator deletes the public reply (DB `deleted_at` set). 21 public page shows the staff comment under its real name (`Demo User`), no badge. 22 bad token: `This link isn't available.`
11. 48/49 triage board cards use the small vote box; clicking toggles it orange.

## Run log (375)

30-46: list, idea page header vote (33), gear menu (34), primary advance (35), composer (36),
reply composer (37), edit with `Save comment` (38/39), delete confirm (40), placeholder (41),
public post + reply (43/44), operator view of public comments (45) and delete (46), board (47).

## Findings

- F1 (375, list): the Votes column cannot be reached. The sticky Idea column is as wide as the table
  viewport (341px), so every other column scrolls underneath it; Idea cannot be hidden from the Columns menu
  (42). The vote box was therefore verified at 375 on the idea page header (33) and the board, not in the list (30, 31).
  Idea column width is unchanged by this lane (`use-ideas-list-config.tsx` diff touches only the Votes column), so this is a pre-existing DataGrid limitation.
- F2 (1280, list): the Votes column is clipped at the right edge of the table card (01/02); the box is fully visible only after a horizontal scroll.
- F3 (375, idea page): `Edit` and the primary button wrap onto two rows (35 and 33): Edit stays left of the primary in DOM/tab order but is not on the same line.
- F4: the public status page footer reads `Foundryx` (21), a tenant-facing surface (pre-existing, not part of this lane).
- Automation notes: off-viewport buttons and the first click on a freshly opened delete dialog needed `scrollintoview` / a repeat click; not reproduced as a product defect.
