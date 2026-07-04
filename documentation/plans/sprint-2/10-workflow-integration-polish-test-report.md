# Test Execution Report — Sprint 2 · Plan 10 (Workflow Engine integration & polish)

**Branch:** `sprint-2/10-workflow-integration-polish`
**Stack:** frontend `:3001` + backend `:8001` (dev, Celery eager), one Postgres.
**Automated suites:** backend **416 passed** (`python -m pytest -q`), frontend
**406 passed** (`npx vitest run`) + **1 E2E passed** (`npx playwright test`).
Typecheck (`tsc --noEmit`) clean; ESLint clean (1 pre-existing unrelated warning).

---

## Coverage by decision

| Decision | What | Verification |
|---|---|---|
| D2 / BL-081 | Notification-spec template picker | Backend `test_context_filter_narrows_the_picker` (`?context=` filter + empty-context safety); frontend `status-engine.test.tsx` (drawer renders + validates); render-through-engine path already covered by plan-07 `test_template_engine.py` (notification template path). |
| D3 / BL-064 | Undo/redo + previewable Tidy, both canvases | `use-history.test.ts` (4 cases — set/undo/redo, redo-clear, external-reset, reset); **E2E `workflow-polish.spec.ts`** (real-click round-trip below); status-canvas drawer/flags still green in `status-engine.test.tsx`. |
| D4 | Run retention prune | `test_prune_runs_drops_old_runs_and_cascades_nodes` (age-based prune + child `workflow_run_nodes` cascade). |
| D5 | Audit-log seam | `test_emit_seam_notifies_registered_subscriber` (subscriber receives the documented event shape after commit). |
| D6 | Debug staleness through IF branches | `test_debug_staleness_propagates_through_taken_if_branch` (edit upstream → re-run upstream + active downstream; IF reused; untaken branch never touched; a stale id on the untaken branch ignored). |

---

## E2E — User Story / Scenario (real clicks, live stack)

**User Story:** As a workflow author, I can experiment with my graph layout —
auto-arrange (Tidy), move nodes, add/remove — and freely undo/redo, with Tidy
never silently destroying my work.

| Field | Detail |
|---|---|
| **Scenario** | Undo/redo + non-destructive Tidy round-trip on the workflow canvas (BL-064). |
| **Precondition** | Dedicated tenant `e2e-wf10-<stamp>` provisioned via operator API; admin logged in via real sign-in clicks. |
| **Steps** | 1. New workflow → canvas visible; Undo disabled (empty timeline). 2. Add Manual trigger (palette search → click). 3. Add Send-email action → 2 nodes. 4. Drag-connect trigger→action → 1 edge; Undo now enabled. 5. Click **Tidy**. 6. Undo (Tidy). 7. Undo (connect), Undo (add-email). 8. Redo, Redo. |
| **Expected** | After Tidy: still 2 nodes + 1 edge (non-destructive). After Undo×1: structure intact (layout only reverted). After Undo×2: edge gone. After Undo×3: 1 node. After Redo×2: 2 nodes + 1 edge restored. |
| **Actual** | All assertions passed — node/edge counts tracked the history exactly; Tidy preserved structure and was itself undoable. |
| **Result** | ✅ PASS (`e2e/workflow-polish.spec.ts`, 6.5s, chromium). |
| **Remarks** | Exercises the shared `useHistory` hook end-to-end. The status-engine canvas consumes the SAME hook (positions-as-draft + Save layout); its drawer + flag behavior stay green in vitest. |

### Status-canvas BL-064 — live manual verification (clean rebuild)

After the code-review fixes (dirty derived from a server baseline), the status
canvas was verified manually against a freshly-rebuilt frontend (`rm -rf .next
&& npm run build && npm start` — the served build had been stale, the documented
wrong-build gotcha). Operator → Status Engine ▸ Tenant ▸ Edit:

| Step | Expected | Actual |
|---|---|---|
| Enter Edit | Toolbar shows Undo/Redo/Tidy/Save-layout, all disabled (clean) | ✅ all disabled |
| Click Tidy | Preview only (no persist); Undo enabled; **"Save layout (1)"** (derived dirty count) | ✅ "Save layout (1)", Undo enabled |
| Click Undo | Layout reverts; **Save layout disabled** (dirty self-corrects to 0); Redo enabled | ✅ Save cleared + disabled, Redo enabled |

Confirms the review fix: dirty is no longer monotonic (undo clears it), Tidy is a
non-destructive preview. Save was intentionally NOT clicked — no shared-tenant
position was persisted.

---

## Journeys covered by integration/unit instead of full UI E2E (rationale)

- **BL-081 — transition notification sent via a selected template (mailbox).**
  The picker UI is unit-tested and the render-through-engine + outbox path is
  backend-integration-tested. A full UI-fire-to-mailbox E2E would require editing
  the **shared platform-tenant** status graph (the only real status entity is
  operator-owned `tenant`), which mutates state every concurrent spec depends on
  (isolation rule) — deliberately not automated here.
- **Debug edit-upstream → execute-downstream across an IF branch.** The branch-
  aware active-set walk + staleness propagation is fully covered by
  `test_debug_staleness_propagates_through_taken_if_branch`; the debug-mode UI
  (node Execute / output inspection) is high-flake to drive and adds no coverage
  the integration test lacks.

---

## Follow-up fixes (user feedback, verified live)

- **BL-081 picker was empty** — no template existed for the `status.notification`
  context, so the picker stayed hidden. Seeded a platform-tier starter "Status
  change notification" template. Verified live: the TransitionDrawer notification
  now shows the "Email template" picker listing *Inline content* + *Status change
  notification*.
- **BL-064 status-canvas Save/Cancel** — the layout draft now rides the
  ResourceForm's global Save/Cancel (like the workflow editor): Tidy/drag dirties
  the form; Cancel raises the "Discard changes?" dialog and reverts the
  arrangement; Save persists. The standalone "Save layout" button was removed.
  Verified live: Tidy → Cancel → Discard reverts the layout and exits edit mode
  (nothing persisted).

## Follow-up fixes round 2 (user feedback, verified live)

- **Template = "load as starting point" (copy).** Picking a template now copies
  its subject + flattened body into the editable inline fields on BOTH the status
  notification drawer and the workflow `email.send` custom mode (a "Load from
  template" picker; `lib/template-to-text` flattens the block doc to plain text +
  merge tokens, dropping rich/brand blocks). No live link. Verified live:
  selecting "Status change notification" filled Subject `{{recordLabel}} moved to
  {{toStatus}}` and a flattened Body, both editable.
- **Run retention = per-tenant setting** (was a global env default). New
  `workflow_settings` table (+ migration `1c2d3e4f5a6b`), `GET/PUT
  /workflows/settings` (gated `workflows.manage`), `prune_runs` prunes PER TENANT
  (override else global default), and a `/settings/workflows` page + sidebar
  entry. Verified live: page loaded the persisted value, Save PUT 200, value
  persisted (30→45→60); platform operator (no `workflows.manage`) correctly hits
  the no-access page.

## Follow-up fixes round 3 (user feedback, verified live)

- **Roomy "Expand" email editor + live preview.** Both email surfaces gained an
  Expand button opening a wide dialog (editor left, preview right). Verified live
  on the status notification: typing `{{recordLabel}} moved to {{toStatus}}`
  rendered "Sample Tenant moved to Active" in the preview. Workflow email.send
  custom mode gets the same dialog (subject + tall body + read-only preview).

## Follow-up fixes round 4 (user feedback, verified live)

- **Linked & branded template emails.** The "copy plain text" model dropped the
  brand header/footer/buttons. Switched to LINKED templates rendered through the
  engine. Notification "Email content" picker = Custom email | templates; a
  selected template sends the full branded template and a "Preview email" button
  shows the real branded render. Workflow email.send Template mode gains the same
  preview; the plain copy picker was removed. Verified live: notification preview
  rendered the engine HTML with the brand header ("Acme Events") + subject from
  sample values.

## Follow-up fixes round 5 (user feedback, verified live)

- **Per-use editable template copy (content-only WYSIWYG).** Selecting a template
  now COPIES its block doc; the operator edits the WORDING in a branded editor
  (header/footer/blocks render exactly like the email) while structure is locked
  (add/reorder/delete stays in Templates). Reuses `EmailEditor` via a new
  `structureLocked` mode (no new editor built). Backend `render_email_doc`
  renders the copied doc branded; `notification_specs.doc_json` (+ migration) and
  the workflow `email.send` action both store + render the doc. Verified live:
  notification content editor shows the branded canvas (brand header + heading/
  text), Design/Preview toggle, ZERO add-section controls (structure locked);
  workflow email.send doc render produced a branded email in the log (run
  success, htmlBody has the compiled brand table). Tests: `render_email_doc`
  branded render; frontend 408 + email-editor green.

## Residue / housekeeping

- E2E provisions an `e2e-wf10-<stamp>` tenant (timestamped; never a fixed literal).
  Purge `e2e-%` tenants from the local DB when the tenants list crowds (BL-035/069).
- No shared-tenant mutation in the automated E2E (dedicated tenant only).
