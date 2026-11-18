# Feedback board - attach images (lane FEEDBACK-ATTACH-IMAGE) - investigation

Status: investigation done, behaviour card filed as a crew-ask on the PR. No code yet.

## What the owner hit

On the public feedback board (personal link `/public/feedback/board/<token>/<item>`), a
person reporting a problem for someone else cannot attach a screenshot, so they paste
chat text instead.

## Root cause: the board has NO attachment support at all

It is not a broken picker - the board never had one.

| Surface | Today | Where |
|---|---|---|
| Board "Submit feedback" form | Text fields + product only. No file input, no paste, no drop. | `service_frontend/components/platform/idea-portal/submit-idea-form.tsx:25-97` |
| Board comment box (+ reply) | `Composer` = one `Textarea` + button. No file input, no paste, no drop. | `service_frontend/components/platform/idea-portal/idea-page.tsx:51-96` |
| Board item page | Does not show attachments either (none on the wire). | `PortalIdeaOut` `service_backend/modules/ideation/schemas.py:927`; `types/idea-portal.ts` has no `attachments` |
| Board API | Create idea + comments only; no upload / serve route. | `service_backend/modules/ideation/routers/portal.py:228,318` |
| Comments table | Text `body` only; no link to attachments. | `service_backend/modules/ideation/models.py:327-346` |

What already exists and will be reused:

| Piece | Where |
|---|---|
| Upload service (magic-byte sniff, tenant storage, 20 per item cap) | `service_backend/modules/ideation/services/attachments.py:38-118` |
| Sniffer (images incl. HEIC/AVIF, PDF, audio, video; rejects markup) | `service_backend/app/uploads.py:121-157` |
| Staff upload + serve routes (25 MB cap) | `service_backend/modules/ideation/routers/ideas.py:61,239-273` |
| Embed upload + serve routes | `service_backend/modules/ideation/routers/embed.py:451-490` |
| Attachment rows (`idea_attachments`, storage_key/mime/size) | `models.py:189`, migration `0013_ideation_attachment_upload.py` |
| Drop area + file list (drag-drop, picker, remove) | `service_frontend/app/(protected)/feedback/components/attachment-drop.tsx` over `hooks/use-file-upload` |
| Preview dialog (image/video/audio/PDF, blob fetch) | `service_frontend/app/(protected)/feedback/components/idea-attachment-preview-dialog.tsx` |

Nothing in the repo handles clipboard paste (`onPaste`) today.

## Overlap

SS #253 (FEEDBACK-SUBSCRIBE) is open on the same module. This lane will touch
`idea-page.tsx`, `submit-idea-form.tsx`, `services/portal.py`, `routers/portal.py`,
`schemas.py`, `types/idea-portal.ts`, `services/idea-portal-service.ts`. A crew-note goes
to #253 before editing any file it also changes; rebase after it merges.
