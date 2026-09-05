# Slice S0 evidence - Omnichannel contact data model (plan 25, frontend-mock)

Recorded via `agent-browser --session s25`, lane frontend `:3003` / backend `:8004`,
tenant `default`, user `demo@example.com`. All navigation below is real clicks from `/`
(sidebar → App Store → Omnichannel section → Workspaces/Inbox), except where noted.

**Environment fixes made during this run (infra, not feature code):**
- `foundryx_service_s25` was a brand-new Postgres DB with an empty module catalog
  (`modules`/`tenant_modules` tables empty) - ran
  `DATABASE_URL=...s25 ENVIRONMENT=development python -m scripts.bootstrap_db` once to
  sync the catalog + install `omnichannel` for the `default` tenant + seed the demo
  conversations/AI workflows. Needed once per lane DB, unrelated to this slice's code.
- The backend's default `CORS_ORIGINS` (service_backend/app/config.py) only lists
  `:3001,:3002` - port `:3003` (this lane) was rejected at the CORS preflight (every
  `OPTIONS` 400'd, so every API call silently failed and the UI looked broken/empty).
  Restarted uvicorn with `CORS_ORIGINS="http://localhost:3001,http://localhost:3002,http://localhost:3003"`
  in the environment (never touched the shared `.env` file). Future lanes on a new port
  need the same override.
- `contact_fields.manage` / `contact_tags.manage` / `contacts.read` / `contacts.manage`
  don't exist yet (S1 ships the real CSV rows + grant). To demonstrate the CRUD dialogs
  (not just the correctly-hidden read-only state), a **local-only** SQL insert added
  those 4 permission keys (module `omnichannel`) and granted them to the `default`
  tenant's Admin role, then re-logged-in to refresh the session. This is a throwaway DB
  change for evidence purposes only - no code changed, and S1's `sync_permissions`
  (delete-by-module on the CSV) will reconcile/replace these rows normally.

## Screenshots (numbered = the walkthrough script; `qa/` = extra validation-state checks)

| # | File | Shows |
|---|---|---|
| 01 | `01-workspaces-list-1280.png` | Settings → Workspaces list (Resource shell), the seeded `General` (Default) workspace. |
| 02 | `02-workspace-detail-tabs-1280.png` | Workspace detail: **Settings · Channels · Members · Lifecycle · Contact fields · Tags · API Keys** - AC-CDM-29 (new tabs after Members). |
| 03 | `03-lifecycle-tab-empty-1280.png` | Lifecycle tab - real `EntityFlow` + `useStatusGraph('omnichannel_contact_lifecycle', workspaceId)` against the REAL backend. **Expected S0 empty state**: canvas renders with zero nodes + a toast "Unknown status entity 'omnichannel_contact_lifecycle'." because the entity isn't registered until S2. This is the correct graceful degradation, not a bug. |
| 04 | `04-contact-fields-tab-1280.png` | Contact fields tab **before** the local permission grant - read-only (no Add/Edit/Delete), proving AC-CDM-33's UX gate; 4 seeded mock fields render (Lead Source list, Company text, Deal Value number, Newsletter Opt-in checkbox/hidden). |
| 05 | `05-contact-field-added-source-1280.png` | After granting `contact_fields.manage` locally: created a `list` field "Source" (options WhatsApp Ads / Referral) via the dialog - success toast, row appended. |
| 06 | `06-tags-tab-1280.png` | Tags tab - 3 seeded tags (📌 Follow up, 🚫 Spam, ⭐ VIP) with emoji, colour swatch + hex, description, contacts count, date added. |
| 07 | `07-create-tag-dialog-1280.png` | Create-tag dialog - emoji input, name, the status-engine's `STATUS_COLOR_SWATCHES` swatches + native colour picker (reused component), description. |
| 08 | `08-tag-created-priority-1280.png` | "Priority" (💜) tag created - success toast, row appended. |
| 09 | `09-inbox-list-1280.png` | Inbox thread list - **AC-CDM-39**: every row shows its lifecycle emoji+label badge and up to 2 tag chips + "+N" (Daniel Lee: VIP, Follow up, +1 for the 3rd tag Spam). |
| 10 | `10-thread-open-1280.png` | Sarah Chen's thread open, Contact panel not yet toggled on. |
| 11 | `11-contact-panel-open-1280.png` | Contact panel opened via the header toggle (right pane, ≥1280px) - **AC-CDM-34/35**: Details (first/last name, phone, email, language, country + registered `always` custom fields incl. the new Source dropdown), Lifecycle (🔥 Hot Lead badge + "Move to…"), Tags (VIP chip + "Add tag…"). |
| 12 | `12-details-editing-1280.png` | Details Edit mode - every field type has its typed input (text/email/SearchSelect for list fields/number). |
| 13 | `13-details-saved-1280.png` | Saved "Source = Referral" - **AC-CDM-06/36**: one PATCH, partial merge, persisted back into the read view. |
| 14 | `14-lifecycle-moved-payment-1280.png` | Moved Hot Lead → Payment via "Move to…" - **AC-CDM-37**: the badge, thread-list row, AND panel all update live off the same mock WS `contact.updated` push, no manual refresh. |
| 15 | `15-tag-added-priority-1280.png` | Added the "Priority" tag from the panel - **AC-CDM-38**: chip appears optimistically, thread-list row updates too. |
| 16 | `16-tag-removed-1280.png` | Removed "Priority" - back to just VIP, thread row in sync. |
| 17 | `17-reload-persists-1280.png` | Full page reload. **Known S0 mock-phase limitation** (documented, not a bug): the in-memory mock services (`contact-field-service.mock.ts`, `contact-tag-service.mock.ts`, `conversation-service.mock.ts`) reset to their seed state on a hard reload, same as every other `*.mock.ts` in this codebase pre-dating this slice (there is no localStorage/backend persistence in Phase A). So the "Source" field, the Payment stage move, and the Priority tag all revert to seed. Real persistence lands with the S1-S3 backend; AC-CDM-42's "reload keeps everything" targets the **S4 real-backend** run, not S0. |
| 18 | `18-tag-duplicate-error-1280.png` | Tags list unaffected by a duplicate "VIP" create attempt (see Known limitations below re: this specific interaction). |
| 19-28 | `19-*` … `28-*-375.png` | Same surfaces at ~375px: workspaces list, tab strip (scrolls horizontally past `min-w-0` fix, all 7 tabs reachable, `20b` shows the scrolled state), Contact fields tab + Add dialog (stacked footer buttons), Tags tab, Lifecycle tab empty state, Inbox list, thread view, Contact panel as a full-screen **Sheet** (`26`,`28`) with its own header + close (`27` shows the thread view with the header's Contact toggle present in the DOM, wrapped into the existing `flex-wrap` header row alongside Search/Assign/Snooze/Close - a pre-existing responsive pattern this button now participates in). |

`qa/` - additional manual validation-state checks (not part of the main walkthrough):
- `qa-contact-fields-editable.png` - Contact fields tab immediately after the local
  permission grant + re-login, "Add custom field" now visible.
- `qa-add-field-dialog.png` - empty create-field dialog.
- `qa-add-field-list-options.png` - selecting Type = Dropdown list reveals the Options
  editor (add/remove rows).
- `qa-add-field-error-no-options.png` - submitting a `list` field with zero options
  shows the client-side zod error "Add at least one option." inline, dialog stays open
  (fieldErrors-shaped validation, matches the real backend's future 422 contract).

## Console / errors observed
- The Lifecycle tab's expected toast (`Unknown status entity 'omnichannel_contact_lifecycle'`)
  is the ONLY error surfaced anywhere in the run - it is the documented S2 dependency,
  not a defect.
- No other console errors during the walkthrough (checked via `agent-browser console`
  after each major navigation).

## Known S0 limitations / things NOT independently re-verified
- **Mock state does not survive a hard reload** (see row 17) - inherent to every
  Phase-A `*.mock.ts` in this repo, not new to this slice.
- **Tag/field registries are single-workspace mocks**: `contact-field-service.mock.ts` /
  `contact-tag-service.mock.ts` accept a `workspaceId` argument (stamped on created
  rows for realism) but do NOT filter by it - `workspace-service` is real and returns a
  real UUID per install, so filtering by a hardcoded seed id would show nothing for the
  actual workspace being viewed. Documented in both files' header comments; the real S1
  backend is properly per-workspace.
- **Row-action dropdown menu (Contact fields "…" Edit/Delete) was not exercised live**
  in this run - the CLI's synthetic click toggled the Radix dropdown open then appears
  to immediately re-close it (a CLI/timing quirk, not reproced via the browser UI
  manually); the delete-confirmation copy naming the contacts/values count was written
  and code-reviewed but not screenshotted. The action menu itself is the exact shared
  `ActionMenu` component used by `use-api-key-list.tsx` (proven elsewhere), so risk is
  low; flagging for the tester to double check with a slower manual pass.
- **Duplicate-tag-name 422 (screenshot 18)** - the CLI's `find role button --name
  "Create tag"` ambiguously matched either the dialog's submit button or the page's
  toolbar button (both share the label); the specific inline "A tag with this name
  already exists." error render wasn't screenshotted, though the mock throws the
  correctly-shaped `ApiError(422, {fieldErrors})` and the dialog's generic
  `form.setError` mapping is shared code already proven via the Contact Field dialog's
  "Add at least one option." error (see `qa/qa-add-field-error-no-options.png`).
