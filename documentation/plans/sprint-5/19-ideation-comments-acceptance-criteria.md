# 19 - Idea comments, upvote-only voting, next-state primary action - acceptance criteria

Owner request 2 Oct 2026 (crew lane IDEATION-COMMENTS, branch `crew/ideation-comments`). Behaviour card answered with the recommendations (Q1-Q5 all option a); mock v2 approved ("ok good"): `documentation/mockups/IDEATION-COMMENTS/index.html`. Plan: `19-ideation-comments.md`.

Surfaces: the OPERATOR idea page `app/(protected)/ideation/ideas/[id]` and the EMBED idea page `app/embed/ideas/[id]` render the SAME `IdeaFormView` / `useIdeaForm` (runtime mode `operator` | `embed`); every FE AC applies to both unless it names one mode. Components stay embeddable: every link and API call goes through `useIdeationRuntime()` (paths + service), never a hard-coded host.

## A. Comments - backend

- **AC-19-01** [BE] A new module table `app_ideation.idea_comments` (`id`, `tenant_id`, `idea_id` FK ideas, `parent_id` nullable self-FK, `author_kind` `user|embed`, `author_id`, `author_name`, `body` TEXT, `created_at`, `edited_at` nullable, `deleted_at` nullable; indexes on `tenant_id`, `idea_id`) lands via module Alembic `0015_ideation_idea_comments` (idempotent `CREATE TABLE IF NOT EXISTS`, Postgres-only) and `IdeationBase` metadata (suite). No backfill: a new table, no existing rows.
- **AC-19-02** [BE] `GET /ideation/ideas/{id}/comments` (perm `ideation.ideas.view`) returns the idea's comments as a flat list ordered `created_at` ASC (oldest first), each `{id, ideaId, parentId, authorName, authorKind, body, isDeleted, isMine, canEdit, canDelete, createdAt, editedAt}`. Tenant-scoped: an idea id from another tenant 404s.
- **AC-19-03** [BE] `POST /ideation/ideas/{id}/comments` `{body, parentId?}` (perm `ideation.ideas.comment`) creates a comment authored by the current user (`author_kind=user`, `author_id=user.id`, `author_name` = user name, falling back to email) and returns 201 with the comment. `body` is stripped; empty or over 5000 chars = 422.
- **AC-19-04** [BE] One reply level: a `parentId` that is itself a reply is normalised to that reply's top-level parent. A `parentId` from another idea (or tenant) = 404 (never attached across ideas).
- **AC-19-05** [BE] `PATCH /ideation/ideas/{id}/comments/{commentId}` `{body}` (perm `ideation.ideas.comment`): only the author may edit (else 403); sets `edited_at`; same body validation as create; editing a deleted comment = 404.
- **AC-19-06** [BE] `DELETE /ideation/ideas/{id}/comments/{commentId}` (204): allowed for the author (perm `ideation.ideas.comment`) or any holder of `ideation.triage.manage`; anyone else = 403. Soft delete (`deleted_at`). A deleted comment WITH live replies is returned with `isDeleted: true`, `body: null`, `authorName: null`; a deleted comment with no live replies is omitted from the list.
- **AC-19-07** [BE] `canEdit` = author and not deleted; `canDelete` = (author or triage.manage) and not deleted; `isMine` = author. Computed per caller.
- **AC-19-08** [BE] A merged child (`merged_into_id` set) refuses comment create/edit (409, same refusal as voting on a merged child); reading still works.
- **AC-19-09** [BE] Deleting an idea removes its comments (no orphan rows; no FK error).
- **AC-19-10** [BE] Embed: `GET|POST /embed/ideas/{id}/comments` and `PATCH|DELETE /embed/ideas/{id}/comments/{commentId}` with `require_embed_principal` + `_assert_in_scope` (tenant + product). Embed author = `author_kind=embed`, `author_id` = the embed voter id (`embed-user:<sub>`), `author_name` = the token's `email` claim, else `Portal user`. Embed users edit/delete only their own comments (no triage override on the embed). An operator JWT on the embed route and an embed token on the operator route both 401.
- **AC-19-11** [BE] New permission `ideation.ideas.comment` (row in `modules/ideation/permissions/permissions.csv`). Grant sweep: when the sync creates the permission row, every role (every tenant) holding `ideation.ideas.upvote` gets `ideation.ideas.comment` (one-shot, same pattern as `sweep_send_to_build_grants`); idempotent on re-run.

## B. Upvote only

- **AC-19-12** [BE] `POST /ideation/ideas/{id}/vote` and `POST /embed/ideas/{id}/vote` with `dir: "down"` = 422. `dir: "up"` toggles as today; an existing `down` row for that voter is switched to `up` by an upvote.
- **AC-19-13** [BE] Existing `down` rows are kept but ignored: `downvotes` on the wire is always 0, `upvotes` counts only `up` rows, `myVote` is `"up"` or `null` (a caller whose row is `down` reads `null`). The `ideas.downvotes` column is recomputed to 0 by `_recount` (no destructive SQL).
- **AC-19-14** [BE] The BR build-handoff issue body lists idea votes as upvotes only (no `/ -N`).
- **AC-19-15** [FE] `VoteCell` renders only an upvote control (no down button anywhere). New `variant="box"` (bordered box, chevron above the count, `size` `md` on the idea page, `sm` in list/board) with orange (primary token) pressed state when `myVote === 'up'`; disabled on a merged child.
- **AC-19-16** [FE] Idea page header: the vote box sits in the record card's avatar slot left of the title (replaces the lightbulb avatar); the Details tab no longer has a `Votes` row.
- **AC-19-17** [FE] Ideas list: the Votes column renders the `sm` vote box; default sort and the Votes column sort by `upvotes` desc (ties `createdAt` desc); CSV has one `Votes` column (upvotes), no `Up`/`Down`. Triage board card uses the same `sm` box and its score is `upvotes`.

## C. Idea page actions

- **AC-19-18** [FE] `ResourceForm` gains opt-in `editPlacement?: 'menu' | 'beside-primary'` (default `'menu'` = today's behaviour, BR page unchanged). With `'beside-primary'` and a `primaryAction`, Edit renders as an outline button immediately LEFT of the primary button and is NOT in the "..." menu.
- **AC-19-19** [FE] Idea page primary action (not editing): merged child -> `Unmerge`; archived idea with a restore transition -> `Restore`; otherwise when `advanceTransitionId` is set -> `Move to <target status label>` (tenant label, e.g. `Move to New` from Draft, `Move to Triaged` from New, `Move to Discussed` where a tenant relabelled Triaged); otherwise no primary action and Edit is the primary as today. The chosen move is removed from the "..." menu (no duplicate); Promote to BR, Archive, Delete stay in the menu.
- **AC-19-20** [FE] Clicking the primary move fires the same status call as before (`setStatus(id, toStatusId)`), refreshes the idea and toasts `Moved to <label>.`; the next primary updates to the following status.

## D. Comments - frontend

- **AC-19-21** [FE] Under the Details tab content (view mode, existing idea only; not on create) a `Comments <n>` section shows a composer (Textarea + `Comment` button disabled while empty/whitespace) above the comment list, oldest first; each comment = `UserAvatar` initials + author name + `formatDateTime(createdAt)` (via `useDatetime`) + `edited` marker when `editedAt` + body (plain text, whitespace preserved; never HTML-rendered).
- **AC-19-22** [FE] Replies render indented under their top-level comment. `Reply` opens an inline composer under that thread (Cancel / Reply); posting a reply to a reply posts to the top-level parent.
- **AC-19-23** [FE] `Edit` / `Delete` links show only when `canEdit` / `canDelete`. Edit swaps the body for a Textarea (Cancel / Save). Delete asks for confirmation (`AlertDialog`) then deletes. A deleted comment with replies shows `Comment deleted`.
- **AC-19-24** [FE] The composer is hidden when the user cannot comment (operator without `ideation.ideas.comment`; any merged child). Empty list = `No comments.`.
- **AC-19-25** [FE] Data flows component -> `hooks/use-idea-comments.ts` -> `IdeaService` (`listComments`, `addComment`, `editComment`, `deleteComment`, optional on the interface) in `ideation-service.real.ts`, `ideation-embed-service.ts` and `ideation-service.mock.ts`; the component never fetches.

## E. Gates

- **AC-19-26** [T] Red-first: tests committed alone (`test(red):`) before any implementation; kill test after green.
- **AC-19-27** [E2E] agent-browser run at 1280px and 375px on a fresh build: vote box toggles on idea page and list, primary `Move to ...` advances, Edit beside it, add/reply/edit/delete a comment.
