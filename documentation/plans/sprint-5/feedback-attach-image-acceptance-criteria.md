# Feedback attachments on board reports + comments - acceptance criteria (lane FEEDBACK-ATTACH-IMAGE)

Owner answers (17 Nov): all types the staff side accepts (image, PDF, video, audio, other sniffable files);
image-only comment allowed; 10 files per report/comment, 25 MB each, 50 per item in total; phone photos
over 2 MB shrunk to 2000 px long side in the browser; same attach on the CRM staff comment box.

Tags: [BE] backend, [FE] frontend unit, [E2E] browser pass, [T] test-only.

## Slice 1 - backend

- **AC-A-01 [BE]** Given a board session that can see an item, When it POSTs a file to
  `/ideation/portal/{id}/attachments` (multipart `file`), Then 201 with `{id, kind, name, sizeBytes, contentPath}`
  and the bytes are in tenant storage. Uses the SAME `IdeaAttachmentService.upload` as staff + embed.
- **AC-A-02 [BE]** Report-level upload (no `commentId`) is allowed only for the item's own submitter
  (`isMine`) or a board manager; anyone else gets 403.
- **AC-A-03 [BE]** With form field `commentId`, the file attaches to that comment; allowed only for the
  comment's author (same viewer identity as delete); a comment of another item / tenant = 404; a deleted
  comment = 404.
- **AC-A-04 [BE]** Limits: file > 25 MB = 413; unverifiable / markup / executable = 415; an 11th file on one
  comment = 422 "This comment has reached its attachment limit."; the 51st file on one item (report +
  comments together) = 422 "This feedback has reached its attachment limit."
- **AC-A-05 [BE]** `GET /ideation/portal/{id}` returns `attachments[]` (report-level only, never comment
  files) - omitted with the other withheld keys when the text is withheld from this viewer.
- **AC-A-06 [BE]** `GET /ideation/portal/{id}/comments` (and the activity feed's embedded comments) return each
  comment's own `attachments[]`; a deleted comment's placeholder returns `[]`.
- **AC-A-07 [BE]** `GET /ideation/portal/{id}/attachments/{attId}/content` serves the bytes with
  `Content-Security-Policy: sandbox`, `nosniff`, private cache; 404 for another tenant's / item's
  attachment, for a report attachment the viewer may not see (withheld), and for a deleted comment's file.
- **AC-A-08 [BE]** A comment body may be empty when the request says files follow:
  `POST .../comments {body: "", hasAttachments: true}` = 201; empty body without `hasAttachments` = 422 (as today).
  Same on the staff `POST /ideation/ideas/{id}/comments`.
- **AC-A-09 [BE]** Staff side: `POST /ideation/ideas/{id}/attachments` accepts optional `commentId` (staff
  comment author only); `GET /ideation/ideas/{id}/comments` carries `attachments[]` per comment;
  `IdeaOut.attachments` keeps report-level files only. Embed upload route accepts `commentId` the same way.
- **AC-A-10 [BE]** Migration `0025_ideation_comment_attachments`: nullable indexed `comment_id` on
  `idea_attachments` (`ADD COLUMN IF NOT EXISTS`); existing rows stay report-level (no backfill needed: NULL
  = report-level, which is what every existing row is).
- **AC-A-11 [BE]** Throttle: board uploads count against a per-principal bucket (reuse the board comment
  throttle family) so a link holder cannot flood storage.

## Slice 2 - frontend (one shared component)

- **AC-A-20 [FE]** Shared `components/platform/attachment-picker/attachment-picker.tsx`: paperclip button
  (file picker; `accept` covers image/video/audio/PDF/any, so a phone offers Gallery / Camera / Files),
  drag-drop onto the wrapped area, clipboard paste (files from `clipboardData`) anywhere inside the wrapped
  form. Pending files show as thumbnails (image object-URL; other kinds = icon + name) with a remove X.
- **AC-A-21 [FE]** Max 10 pending; 25 MB each; an over-limit file is refused at pick time with
  "<name> is too large (max 25 MB)" / "Up to 10 files"; nothing else is lost.
- **AC-A-22 [FE]** `lib/shrink-image.ts`: JPEG/PNG/WebP over 2 MB are re-encoded to at most 2000 px on the long
  side before upload; smaller images, HEIC, video, audio and PDF are sent unchanged.
- **AC-A-23 [FE]** Board Submit form: files upload after the item is created (one Submit click); the page
  then opens the item. If a file fails, the item still exists, the failed file is named with "Try again".
- **AC-A-24 [FE]** Board comment + reply box: Comment is enabled with text OR files; files upload after the
  comment is created; the comment shows its thumbnails.
- **AC-A-25 [FE]** Item page: report thumbnails under the fields; comment thumbnails under the comment text;
  clicking opens the shared preview popup (moved to `components/platform/attachment-preview/`) with Download.
- **AC-A-26 [FE]** CRM staff comment box (`feedback/components/idea-comments.tsx`) gets the same picker and
  shows comment thumbnails.

## Slice 3 - verification

- **AC-A-30 [E2E]** 1280 + 375: paste a screenshot into Submit, drag 3 files onto a comment, pick from the
  phone file input (image + video), image-only reply, remove before send, preview popup opens.
