# Sprint 2 · Plan 07 - Template Engine · Test Execution Report

**Feature:** Template engine (email surface) + email outbox UI
**Plan:** [07-template-engine.md](./07-template-engine.md)
**Date:** 2026-06-08
**Build under test:** `sprint-2/07-template-engine` (rebased onto main post-storage-merge)

## Suites

| Layer | Tool | Result |
|---|---|---|
| Backend | pytest (`tests/test_template_engine.py` + regression) | **381 passed** |
| Frontend unit | Vitest + RTL (46 files) | **372 passed** |
| E2E | Playwright (`e2e/templates.spec.ts`, real clicks) | **3 passed** |

Backend `test_template_engine.py` (40 cases) covers: merge security (substitution-only, HTML-escape, URL-scheme validation, no expression evaluation), compiler golden output per block type + text sibling + brand-primary inheritance, conditional pruning (fail-closed), `validate_doc` 422 matrix (unknown type, missing required fact, required-fact-in-subject, custom/text HTML sanitization, bad conditions, layout/column mismatch), two-tier fork/reset + platform-tier in-place edit, system delete-block + duplicate, preview with sample facts, engine-rendered system mails (forgot-password outbox row is mrml HTML), test-send to caller, notification `template_id` dispatch, email-log retry/cancel semantics + retention + permission gates.

---

## E2E Test Execution Report (orchestration guide §6)

Rig: backend :8001 (migrated + seeded), frontend :3001 (built), maildir smtpd
(`aiosmtpd … Mailbox /tmp/foundryx-e2e-mailbox`). Dedicated tenant provisioned via
the operator API per run (isolation §7); timestamped names.

### Scenario 1 - Create, design, preview, test-send

- **User Story:** US-15 - as an admin I design email templates with dynamic variables.
- **Precondition:** Admin signed in on a fresh tenant; SMTP connection → debug maildir.
- **Steps:** Templates list → New template → Settings tab: set name + pick context ("Template · Test send") → Design tab (blank doc = brand header/body/footer) → Save → Preview → Actions → Send test email.
- **Expected:** Create replaces `/new` with the new template id; preview iframe renders; test mail lands in the maildir as mrml table HTML.
- **Actual:** As expected - URL navigated to `/settings/templates/<id>`; preview frame visible; `[Test] …` mail delivered containing `<table`.
- **Remarks:** Pass. (Palette drag-drop is covered by the editor Vitest suite - Playwright's mouse-event `dragTo` does not drive dnd-kit's pointer sensors.)

### Scenario 2 - Fork a system template; forked mail; reset

- **User Story:** BL-038/BL-066 - tenant customizes (and brands) a system email.
- **Precondition:** Seeded platform-tier `auth.password_reset` at the Default tier.
- **Steps:** Open Password reset → Edit → Settings tab → change subject (unique marker) → Save → return to list (row now Customized) → trigger real forgot-password → read mail → reset to default.
- **Expected:** First edit FORKS a tenant copy (list shows Customized); the forgot-password mail renders the forked subject marker + a `change-password?token=` link; Reset drops the fork (row back to Default).
- **Actual:** As expected - list row Customized; mail contained the marker + reset link; after Reset the row showed Default.
- **Remarks:** Pass. Proves system mail renders through the engine and respects the tenant fork end-to-end.

### Scenario 3 - Email log: list, body, segments

- **User Story:** D14 - the outbox is surfaced; bodies inspectable.
- **Precondition:** Scenarios 1-2 left sent mail in the tenant's outbox.
- **Steps:** Email log → open a `[Test]` row → Body tab → Raw HTML view.
- **Expected:** Row opens to the read-only detail; sandboxed body iframe renders; Raw HTML shows the mrml `<table` output.
- **Actual:** As expected.
- **Remarks:** Pass. Retry/cancel state transitions are exercised in the backend suite (atomic cancel → 409 on race; retry preserves attempts).

---

## Known limitations (documented, not regressions)

- **Logo image unreachable in real mail clients during local dev:** `public_base_url` defaults to `http://localhost:8001`, so the brand-header logo URL can't be fetched by an external mail client's image proxy (e.g. Gmail). Works in production with a real public base URL; for local real-delivery testing, point `public_base_url` at a tunnel.
- **dnd-kit drag-drop not E2E-driven:** asserted via Vitest (`email-editor.test.tsx`) instead.
- **Rich-text formatting** is on Text blocks (panel WYSIWYG toolbar); headings remain plain inline text.

## Follow-ups logged

- BL-024 / BL-038 / BL-066 - closed by this plan (email surface).
- New backlog: notification-spec template-picker UI; badge/ticket canvas (BL-071); repeater block (BL-072); template versioning (BL-073); unsubscribe machinery (BL-074); saved-blocks (BL-075); website builder (BL-076).
