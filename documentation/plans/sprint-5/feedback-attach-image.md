# Feedback attachments on board reports + comments - plan (lane FEEDBACK-ATTACH-IMAGE)

Fulfils `feedback-attach-image-acceptance-criteria.md`. Investigation: `feedback-attach-image-investigation.md`.

## Backend (`service_backend/modules/ideation/`)

1. `models.py IdeaAttachment.comment_id` - `Column(String, ForeignKey("idea_comments.id"), nullable=True, index=True)`
   (same FK style as `IdeaComment.parent_id`). Migration `alembic/versions/0025_ideation_comment_attachments.py`
   (`ADD COLUMN IF NOT EXISTS comment_id VARCHAR NULL` + `CREATE INDEX IF NOT EXISTS`), Postgres-only like 0013.
   down_revision = current head on main (re-pointed after #253's 0024 merges).
2. `services/attachments.py`
   - `MAX_ATTACHMENTS_PER_IDEA = 50`, new `MAX_ATTACHMENTS_PER_COMMENT = 10`.
   - `upload(..., comment_id=None)`: when set, the comment must be in the tenant + idea and not deleted (404
     otherwise); per-comment cap 422. Item cap counts every row of the idea.
   - new `by_comment(tenant_id, comment_ids) -> {comment_id: [IdeaAttachmentOut]}` and
     `report_level(tenant_id, idea_id)`; content route resolver `content(...)` unchanged, plus a
     `comment_id_of(...)` helper so the board route can refuse a deleted comment's / withheld report file.
   - `contentPath` prefix argument already exists - board uses `/ideation/portal`.
3. `services/ideas.py _attachments_by_idea` filters `comment_id IS NULL` (report-level only).
4. `schemas.py`: `IdeaCommentOut.attachments: List[IdeaAttachmentOut] = []`; `PortalIdeaOut.attachments`;
   comment create bodies gain `hasAttachments: bool = False` (empty body allowed only with it).
5. `services/comments.py`: `create(..., allow_empty=False)`; `list`/`_out` fill `attachments` in one batched query.
6. `services/portal.py`:
   - `detail()` adds `attachments` (report-level), added to `WITHHELD_DETAIL_KEYS`.
   - `upload_attachment(idea_id, filename, content, comment_id)`: `_resolve(follow_merge=False)`; report-level
     needs `_is_owned` or `can_manage`; comment-level needs the comment's author == `p.viewer` (reuse
     `IdeaCommentService._is_mine`); throttle `enforce_idea_portal_upload`; then `IdeaAttachmentService.upload`.
   - `attachment_content(idea_id, att_id)`: resolve (follow_merge=True), refuse withheld report files and
     deleted-comment files.
7. `routers/portal.py`: `POST /{idea_id}/attachments` (multipart `file`, optional form `commentId`, 25 MB capped
   read like `routers/ideas.py:251`), `GET /{idea_id}/attachments/{att}/content` (serve via the shared
   `_serve_blob` used by `routers/ideas.py`).
8. `routers/ideas.py` + `routers/embed.py` upload routes: optional form `commentId` (staff/embed author check).
9. `app/services/throttle.py`: `idea_portal_upload` scope (config `throttle_idea_portal_upload_max = 100` / 60 min).

## Frontend (`service_frontend/`)

1. `lib/shrink-image.ts` - canvas re-encode, JPEG/PNG/WebP > 2 MB -> max 2000 px long side (same mime; PNG -> PNG).
2. `components/platform/attachment-picker/` - `AttachmentPicker` (paperclip + hidden input + thumbnail strip)
   and `useAttachmentDraft()` (pending list, add/remove, limits, paste/drop handlers to spread on a wrapper).
   Built on `hooks/use-file-upload` (already used by `feedback/components/attachment-drop.tsx`).
3. `components/platform/attachment-preview/` - move `idea-attachment-preview-dialog.tsx` here (staff import
   updated) + `AttachmentThumbs` (thumbnail grid that fetches uploaded images as blobs through a passed
   `fetchContent`, opens the dialog).
4. `services/idea-portal-service.ts` - `uploadAttachment(id, file, commentId?)`, `attachmentContent(path)`;
   `types/idea-portal.ts` - `attachments` on `PortalIdea` / `PortalComment`.
5. `hooks/use-idea-portal.ts` - submit + addComment take files, upload sequentially after create, return the
   names that failed.
6. `submit-idea-form.tsx`, `idea-page.tsx` (`Composer` + `CommentItem` + fields block) wire it in.
7. `feedback/components/idea-comments.tsx` (+ its hook/service) - same picker + thumbnails.
