# F2 Slice 2 - Fixed-Canvas Badge Designer · Test Execution Report

**Plan:** `documentation/plans/sprint-3/03-multi-format-render.md` (§2, D12-D19)
**Branch:** `sprint-3/03b-canvas-designer`
**Date:** 2026-06-12
**Stack:** backend :8001 (sprint-3/03b, Postgres, seeded) · frontend prod build :3001 (clean `.next` rebuild)

---

## Summary

| Layer | Suite | Result |
|-------|-------|--------|
| Backend | `tests/test_template_canvas.py` (22) | ✅ pass |
| Backend | `tests/test_template_parity.py` (5, extended) | ✅ pass |
| Backend | full suite (`pytest -q`) | ✅ 685 passed (incl. the 3 workflow tests fixed by the email-picker type filter) |
| Frontend | `lib/canvas-doc.test.ts` (16) | ✅ pass |
| Frontend | `components/platform/canvas-editor/canvas-editor.test.tsx` (5) | ✅ pass |
| Frontend | full vitest (`vitest run`) | ✅ 543 passed |
| Frontend | `npm run lint` / `tsc --noEmit` | ✅ clean (1 pre-existing warning, not in this change) |
| E2E | `e2e/badge-canvas.spec.ts` (5) | ✅ 5 passed (live stack) |

---

## E2E journeys (Playwright, real clicks, live stack)

All five drive the seeded platform **"Attendee badge"** (`badge.attendee`, type `badge`,
context `badge.preview`) via real navigation (header Settings mega-menu → Templates →
row click). No shared state mutated (draft preview only) → parallel-safe.

### Journey 1 - Open badge → Konva editor mounts
- **Steps:** login → Templates → open "Attendee badge" → Design tab.
- **Expected:** the CanvasEditor mounts; palette (4 element types) + the Konva canvas stage visible.
- **Actual:** `canvas-editor`, `canvas-palette`, `canvas-stage` all visible. ✅

### Journey 2 - Edit → palette click-to-add opens the inspector
- **Steps:** open badge → Edit toggle → palette "Text".
- **Expected:** the new text element auto-selects; the inspector opens with the content field.
- **Actual:** `canvas-inspector` + "Text content" field visible. ✅

### Journey 3 - Preview renders the server canvas sheet
- **Steps:** open badge → Preview toggle.
- **Expected:** the in-app sheet (sandboxed iframe, `srcDoc`) shows the **server-rendered**
  canvas - the QR is a real server-generated inline `<svg>`; the `{{attendeeName}}` sample
  resolves to "Alex Tan"; a `.badge-side` page sheet is visible inside the frame.
- **Actual:** `srcdoc` contains `<svg>` and "Alex Tan"; `.badge-side` visible in-frame. ✅

### Journey 4 - Download PDF
- **Steps:** open badge → Preview → "Download PDF".
- **Expected:** a `.pdf` download starts (WeasyPrint bytes).
- **Actual:** download `suggestedFilename()` matches `*.pdf`. ✅

### Journey 5 - Responsive (375px AND 1280px)
- **Steps:** for each viewport: open badge (Design) → assert no horizontal overflow →
  Preview → assert no horizontal overflow.
- **Expected:** canvas stage + preview pane render with `scrollWidth − clientWidth ≤ 1` at
  both widths (CLAUDE.md both-sizes mandate; palette·canvas·inspector stacks on mobile).
- **Actual:** no overflow at mobile or desktop. ✅

---

## Notes / decisions surfaced during the build

- **`contextKey` stays on the Template row** (not in the canvas doc, deviating from the D14
  sketch) - keeps the doc shape consistent with email/document docs and the validate
  signature uniform (context passed in).
- **Rotation pivot = top-left** on both the Konva editor (default node pivot at x,y) and the
  HTML render (`transform-origin: left top`) - editor↔render parity without centre-offset math.
- **Konva never renders the artifact**: in-editor QR + storage-backed images show placeholders;
  the Preview/Download PDF is the authoritative server render (segno QR + WeasyPrint).
- **Real bug caught:** the workflow email-template picker (`template_options`) listed every
  template type; a badge/document **canvas/PDF doc must never render as mail** → now filtered
  to `type='email'`. This restored 3 workflow tests that broke once the badge starter seeded.
- **react-konva `data-testid` quirk:** the Stage container div does not receive forwarded
  `data-testid`; it lives on the DOM wrapper instead.

## Deferrals (unchanged, per plan §4)
- Per-element rule conditions already shipped (RuleBuilder in the inspector); per-row
  repeater conditions remain a slice-1 deferral.
- `render_canvas_batch` is the Celery batch **seam** (tested with synthetic facts); the real
  "print all badges for Event X" trigger lands with Cluster H (no attendee entity yet).
- Cert starter seed on the canvas surface - post-slice-2 (badge starter only).
