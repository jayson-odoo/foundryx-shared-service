# Plan 52: file previews use a fixed set of display types

UAC: `52-file-viewer-types-acceptance-criteria.md`. Size S. Branch `crew/ss-blob-viewer-types`. Reuse the allow-list helper from the form file viewer (merged in PR 153); the type is the control (AC-52-02).

Files: `service_frontend/lib/file-display-type.ts` (the one list and helper, moved out of `components/platform/form-renderer/field-read.tsx`), `service_frontend/services/document-service.real.ts` (about :204, :341), `service_frontend/services/public-share-service.ts` (about :58), the idea attachment preview dialog (about :58), `service_frontend/hooks/use-media-blob.ts` (conversation media). Tests: vitest beside each, red first. No new screens.

Round 2 (review at a7811c2e): one list for every viewer instead of a second media list, so an idea video or audio upload and a Messenger gif or webm keep their type (AC-52-05); a control per listed type so dropping an entry fails a test.
