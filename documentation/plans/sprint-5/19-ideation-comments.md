# 19 - Idea comments, upvote-only voting, next-state primary action - plan

UAC: `19-ideation-comments-acceptance-criteria.md`. Mock (approved v2): `documentation/mockups/IDEATION-COMMENTS/index.html`. Lane IDEATION-COMMENTS, branch `crew/ideation-comments`, size M.

Rulings (owner card, 2 Oct, all recommendation (a)): Q1 oldest-first, one reply level; Q2 new `ideation.ideas.comment` swept to `ideation.ideas.upvote` holders; Q3 author edits/deletes own, `ideation.triage.manage` deletes any; Q4 keep `down` rows, ignore in tallies; Q5 no comments on the public status page. Embed/iframe polish belongs to lane IDEATION-IN-CRM; this lane keeps the components embeddable (runtime paths + service only).

## 1. Backend (`service_backend/modules/ideation/`)

1. `models.py`: `IdeaComment` (table `idea_comments`, columns per AC-19-01). `parent_id` self-FK nullable.
2. `alembic/versions/0015_ideation_idea_comments.py` (revision id `0015_ideation_idea_comments`, down `0014_ideation_br_build`): `CREATE TABLE IF NOT EXISTS` + indexes, Postgres-only, idempotent. Crew dev-DB SQL mirrored at `crew/state/migrations/IDEATION-COMMENTS.sql`.
3. `permissions/permissions.csv`: row `ideation.ideas,Ideas,comment,Comment,Comment on ideas (Submitter)`. `bootstrap.py`: generalise the one-shot sweep (`sweep_send_to_build_grants` pattern) into a helper `_sweep_grant(db, holder_key, new_key)`; call it for `upvote -> comment` when the sync created `ideation.ideas.comment`.
4. `services/comments.py` (`IdeaCommentService`, Repository-style queries inside the service as the module already does): `list(tenant_id, idea_id, viewer)`, `create(...)`, `edit(...)`, `delete(...)`; `viewer` = `(author_kind, author_id, can_moderate)`. Parent normalisation (AC-19-04), soft delete + omission rule (AC-19-06), merged-child refusal reusing `_refuse_if_merged_child` (AC-19-08). Idea delete path (`actions.py` delete / deferred `ideation_ideas.delete` handler) removes the idea's comments first (AC-19-09).
5. `schemas.py`: `IdeaCommentOut(ApiModel)`, `IdeaCommentCreate {body, parentId?}`, `IdeaCommentEdit {body}`; body validation strip + 1..5000.
6. `routers/ideas.py`: 4 operator routes (AC-19-02..06). `can_moderate` = `ideation.triage.manage` in the caller's effective permission keys.
7. `routers/embed.py`: 4 embed routes (AC-19-10), author id = `_embed_voter_id(principal)`, name = `principal.email or "Portal user"`, `can_moderate=False`.
8. Upvote only: `VoteBody.dir` accepts only `up` (422 on `down`) for operator + embed (AC-19-12); `actions._recount` counts `up` only and sets `downvotes = 0`; `ideas._serialize` returns `downvotes=0`, `myVote` `up|None` (AC-19-13); `build_handoff.py` / `issue_body.py` upvotes only (AC-19-14).

## 2. Frontend (`service_frontend/`)

1. `types/ideation.ts`: `IdeaComment`; `myVote: 'up' | null`; `downvotes` kept on the type (always 0) for wire compatibility.
2. `services/ideation-service.ts`: optional `listComments/addComment/editComment/deleteComment`; `vote(id)` keeps the `dir` param typed `'up'`. Implement in `.real.ts`, `ideation-embed-service.ts`, `.mock.ts`.
3. `hooks/use-idea-comments.ts`: load + mutations via `useIdeationRuntime().service`; groups flat list into threads.
4. `app/(protected)/ideation/ideas/components/idea-comments.tsx`: section per AC-19-21..24 (`UserAvatar`, `Textarea`, `Button`, `AlertDialog`, `useDatetime`). Mounted at the bottom of `DetailsTab` view mode for an existing idea.
5. `vote-cell.tsx`: drop down button; add `variant: 'pill' | 'box'` and `size: 'sm' | 'md'` (AC-19-15). Used by `use-idea-form.tsx` (avatar slot), `use-ideas-list-config.tsx` (Votes column + CSV + sort), `select-idea-rows.ts` (upvotes sort), `board/triage-board.tsx`.
6. `components/platform/resource-form/{types.ts,resource-form.tsx}`: `editPlacement` (AC-19-18).
7. `use-idea-form.tsx`: `primaryAction` per AC-19-19, the chosen move removed from `actions`, `editPlacement: 'beside-primary'`, avatar = vote box, `Votes` row removed from `idea-form-fields.tsx`.

## 3. Test list (tester writes these RED before the coder)

Backend `service_backend/tests/test_ideation_comments.py`: AC-19-02 list order + shape; 03 create + 422 empty/5001; 04 reply-to-reply normalised + cross-idea parent 404; 05 edit own ok, other 403, edited_at set; 06 delete own, triage deletes other's, plain user 403, deleted-with-replies placeholder, deleted-without-replies omitted; 07 flags per caller; 08 merged child 409; 09 idea delete removes comments; 10 embed CRUD + author name from email + cross-scope 404 + operator/embed token cross 401; 11 sweep grants comment to upvote holders, idempotent; cross-tenant 404 on GET. `test_ideation_votes_upvote_only.py`: 12 down 422 (operator + embed), down row switched by upvote; 13 tallies ignore down, myVote null for down voter; 14 issue body no `/ -`.

Frontend (vitest): `vote-cell.test.tsx` (no down button, box variant pressed/disabled); `resource-form.edit-placement.test.tsx` (beside-primary order + not in menu; default unchanged); `use-idea-form.test.tsx` (primary per state: draft/new/relabelled/closed/archived/merged; move not duplicated in menu; click calls setStatus); `idea-comments.test.tsx` (render order, reply indent, reply-to-reply posts parent, edit/delete visibility, delete confirm, deleted placeholder, composer hidden without perm / merged, plain text not HTML); `use-ideas-list-config.test.tsx` + `select-idea-rows.test.ts` (upvotes sort, CSV Votes column); `ideation-service.real.test.ts` (comment endpoints + paths).

## 4. Deferred

None planned. Comment notifications (email/WhatsApp to submitter) are out of scope; raise with the owner if wanted.
