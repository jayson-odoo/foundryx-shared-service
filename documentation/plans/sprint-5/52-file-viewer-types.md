# Plan 52: file previews use a fixed set of display types

UAC: `52-file-viewer-types-acceptance-criteria.md`. Size S. Branch `crew/ss-blob-viewer-types`. Reuse the allow-list helper from the form file viewer (merged in PR 153); the type is the control (AC-52-02).

Files: `service_frontend/services/document-service.real.ts` (about :204, :341), `service_frontend/services/public-share-service.ts` (about :58), the idea attachment preview dialog (about :58). Tests: vitest beside each, red first. No new screens.
