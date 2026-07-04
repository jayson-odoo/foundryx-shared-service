# Sprint 3 · Plan 04 — Resource & Document Management (the Drive) — User Acceptance Criteria

**Scope:** slice 1 (the Drive). Companion to `04-document-mgmt-drive.md`. Sharing (links, tiers, public route) is slice 05 (`05-document-mgmt-sharing.md`) and is **out of scope** here except where the slice-1 UI must *not* yet expose it.

**How to read:** each criterion is **Given / When / Then**, grouped by feature. Every group lists its **edge cases** as their own pass/fail criteria. The **Traceability** table at the end maps each acceptance group back to the plan's locked decisions (D1–D15) so functionality tallies with the design. A feature is "accepted" only when every criterion in its group passes at **both** a desktop (~1280px) and a mobile (~375px) viewport (house responsive mandate).

**Personas**
- **Member** — holds `documents.read` only. Browses, previews, downloads.
- **Manager** — holds `documents.read` + `documents.manage`. Adds/edits/moves/deletes files & folders.
- **Admin** — also holds `documents.configure`. Manages types + settings.
- **No-access** — holds none of `documents.*`.

**Global preconditions**
- The tenant Drive is seeded/empty as stated per scenario; the user is authenticated to a single tenant; all data is tenant-scoped (a user never sees another tenant's folders/files — verified in Phase B backend tests, asserted at UI by absence).

---

## 1. Navigation & the Drive tree (use case: "find my files like Google Drive")

**AC-NAV-01 — Land on the Drive root**
- Given a Member opens **Documents** from the sidebar,
- When the page loads,
- Then the left **tree** shows a **Drive** root plus top-level folders, the main panel shows the root's folders + files, and the breadcrumb reads **Drive** only.

**AC-NAV-02 — Open a folder (three ways, one result)**
- Given a folder is visible,
- When the user (a) double-clicks the folder card, **or** (b) clicks its name in the tree, **or** (c) chooses **Open** from its right-click menu,
- Then the main panel shows that folder's contents and the breadcrumb appends the folder name.

**AC-NAV-03 — Breadcrumb + tree navigate up**
- Given the user is 3 levels deep,
- When they click any ancestor crumb or any tree node,
- Then the Drive navigates to that level and the breadcrumb/tree highlight update to match.

**AC-NAV-04 — Tree lazy-expands**
- Given a folder has sub-folders,
- When the user clicks its expand chevron,
- Then its children load and render indented; a folder with no sub-folders shows **no** chevron (no dead control).

**Edge cases**
- **NAV-E1 Empty folder:** an empty folder shows a centered empty state ("This folder is empty."), never a blank panel.
- **NAV-E2 Deep path overflow:** a long breadcrumb scrolls horizontally within its bar — it never pushes the toolbar buttons off-screen or wraps into the grid.
- **NAV-E3 Load failure:** if a folder fails to load, the panel shows a friendly error ("Could not load this folder."), not a stack trace or a spinner stuck forever.
- **NAV-E4 Selection clears on navigate:** opening any folder clears the current multi-selection (selection belongs to the view it was made in).

---

## 2. Folder operations (use case: organise documents)

**AC-FOLDER-01 — Create a folder**
- Given a Manager is inside any folder (or root),
- When they click **New folder**, type a name, and confirm,
- Then a new folder appears in the current location and the tree refreshes to include it.

**AC-FOLDER-02 — Rename a folder**
- Given a Manager right-clicks a folder → **Rename**,
- When they change the name and save,
- Then the folder's display name updates everywhere (grid, tree, breadcrumb if open) and its identity/contents are unchanged.

**AC-FOLDER-03 — Move a folder by drag**
- Given a Manager drags a folder card onto another folder (card or tree node),
- When they drop,
- Then the folder relocates under the target and both source and tree refresh.

**AC-FOLDER-04 — Move a folder by dialog**
- Given a Manager chooses **Move to…**,
- When they descend the destination picker and click **Move here**,
- Then the folder relocates; **Move here** is disabled when the chosen destination equals the current location (no-op).

**Edge cases**
- **FOLDER-E1 Cycle guard (drag):** dragging a folder onto itself or any of its own descendants performs **no move** — the item stays put, no error toast spam, no corrupted tree.
- **FOLDER-E2 Cycle guard (dialog):** the destination picker disables the folders being moved as drop targets; attempting a descendant move is refused by the backend (422) and the UI keeps the item in place.
- **FOLDER-E3 Blank name:** an empty/whitespace name cannot be submitted (the confirm button is disabled); never creates an "Untitled"-less blank.
- **FOLDER-E4 Permission:** a Member sees **no** New folder / Rename / Move / Delete affordances; backend rejects if attempted directly (403).

---

## 3. File operations (use case: tidy individual files)

**AC-FILE-01 — Rename a file (refs stable)**
- Given a Manager renames a file,
- When they save,
- Then the name updates but the file id, version history and any links are unaffected.

**AC-FILE-02 — Move files (single + multi)**
- Given a Manager selects one or many files,
- When they drag the selection onto a folder **or** use **Move**,
- Then every selected file relocates and selection clears.

**Edge cases**
- **FILE-E1 Mixed selection move:** a selection containing both folders and files moves all of them together to the target.
- **FILE-E2 Drag a non-selected item:** dragging an item that is **not** part of the current selection moves only that item (the selection is untouched).

---

## 4. Upload (use case: bulk + à-la-carte import, like Drive)

**AC-UPLOAD-01 — À-la-carte upload**
- Given a Manager clicks **Upload** and picks one file,
- Then the file lands in the current folder, the **Uploads** drawer opens showing per-file progress, and the item ends as **done** with a success indicator.

**AC-UPLOAD-02 — Bulk upload**
- Given a Manager selects/drag-drops 20 files at once,
- Then all 20 queue in the drawer with independent progress bars and complete without blocking navigation (the user can browse other folders while uploads run).

**AC-UPLOAD-03 — OS drag-drop onto the Drive**
- Given a Manager drags files from their desktop onto the Drive panel,
- When they drop,
- Then those files enqueue to the current folder exactly as the Upload button would.

**AC-UPLOAD-04 — Non-blocking + decoupled drawer**
- Given uploads are in flight,
- When the user navigates between folders / Types / Settings within Documents,
- Then the Uploads drawer and its progress persist (decoupled from the page); the toolbar **Uploads** badge shows the in-flight count and reopens the drawer.

**AC-UPLOAD-05 — Retry a failed upload**
- Given an upload failed (e.g. transient error),
- When the user clicks **Retry** on that row,
- Then the upload restarts from queued; **Clear finished** removes done/failed rows without touching in-flight ones.

**Collision (D5) — the headline UX**

**AC-UPLOAD-06 — Same-name warning**
- Given a file with the same name already exists in the destination,
- When the upload reaches the server,
- Then that drawer row enters a **conflict** state offering **Replace** and **Keep both** — nothing is silently overwritten or duplicated.

**AC-UPLOAD-07 — Replace → new version**
- Given a conflict, when the user chooses **Replace**,
- Then the existing file gains a **new version** (its bytes are not destroyed) and the version count increments.

**AC-UPLOAD-08 — Keep both → auto-rename**
- Given a conflict, when the user chooses **Keep both**,
- Then a new file is created named `name (1)` (next free index), leaving the original intact.

**Policy + safety floors (D7, D12)**

**AC-UPLOAD-09 — Sniff hard-floor**
- Given a Manager uploads an executable/HTML/SVG (e.g. `.exe`),
- Then the upload is **rejected** with a clear reason ("… aren't allowed for security reasons") regardless of any type configuration — a tenant cannot configure this open.

**AC-UPLOAD-10 — Type/size policy**
- Given a file exceeds the per-type cap (when a type is chosen) or the tenant default cap (untyped),
- Then the upload is rejected with the limit named; given a type with an allowed-extension list, a disallowed extension is rejected naming the type.

**AC-UPLOAD-11 — Quota (D12)**
- Given the upload would push storage past the tenant quota,
- Then it is rejected with a quota message (HTTP 413), and the usage bar reflects unchanged usage.

**Edge cases**
- **UPLOAD-E1 Zero-byte / empty filename:** handled gracefully (rejected or accepted per policy) — never crashes the drawer.
- **UPLOAD-E2 Many conflicts in one batch:** each conflicting row resolves independently; resolving one does not auto-apply to the others.
- **UPLOAD-E3 Navigate away mid-upload:** within Documents the upload continues; leaving Documents entirely is acceptable to drop in-session progress (slice-1 scope) — no orphaned partial file is shown in the tree.
- **UPLOAD-E4 Drive refresh on completion:** when an upload completes, the current folder's grid and the tree refresh automatically so the new file appears without a manual reload.
- **UPLOAD-E5 Replace keeps quota honest:** Replace retains old versions, so usage increases by the new version's size (not a net-zero swap) — consistent with version history.

---

## 5. Version history (D5)

**AC-VERSION-01 — Append, never overwrite**
- Given a file is replaced or re-uploaded,
- Then a new version is appended, `currentVersion` advances, and the prior bytes are retained (restore-previous UI is a later backlog item, BL-097, but the data must be kept now).

**AC-VERSION-02 — Version indicator**
- Given a file has >1 version,
- Then the file card shows a version marker (e.g. `v2`).

**Edge case**
- **VERSION-E1:** a single-version file shows no version marker (no noise).

---

## 6. Download (use case: preview + download; bulk export)

**AC-DOWNLOAD-01 — Single file = direct**
- Given a Member chooses **Download** on one file (menu or non-previewable double-click),
- Then the file downloads directly (stream/presigned), with **no** job queued.

**AC-DOWNLOAD-02 — Bulk / folder = async ZIP**
- Given a user multi-selects files (or picks **Download ZIP** on a folder),
- Then a ZIP job is created, the **My Downloads** drawer opens showing **Preparing…**, and on completion the row offers **Download**.

**AC-DOWNLOAD-03 — Fresh URL on click**
- Given a ZIP job is **ready**,
- When the user clicks **Download**,
- Then a freshly-signed URL is fetched and the browser downloads the ZIP (presigned URLs are never cached/immutable).

**AC-DOWNLOAD-04 — Decoupled poll**
- Given a job is pending/processing,
- Then the drawer polls and updates status to ready without a page reload, and stops polling once all jobs are settled.

**Edge cases**
- **DOWNLOAD-E1 Single folder selected:** a selection of exactly one folder + no files zips that folder's subtree.
- **DOWNLOAD-E2 Job failure:** a failed ZIP shows a clear failed state (no enabled Download button).
- **DOWNLOAD-E3 Badge:** the toolbar **Downloads** badge shows in-flight job count and reopens the drawer.

---

## 7. Inline preview (D10)

**AC-PREVIEW-01 — Image preview**
- Given a Member double-clicks (or chooses **Preview** on) an image,
- Then a dialog renders the image inline with a **Download** affordance.

**AC-PREVIEW-02 — PDF preview**
- Given a PDF,
- Then it renders inline in a **sandboxed** iframe (no script execution), with Download available.

**AC-PREVIEW-03 — Non-previewable types**
- Given a `.docx`/`.xlsx`/`.zip`,
- Then there is **no** Preview action; the card double-click downloads instead, and the card shows a type-appropriate icon.

**Edge cases**
- **PREVIEW-E1 Preview unavailable:** if the preview source can't load, the dialog shows "Preview unavailable." plus Download — never a broken image frame with no recourse.
- **PREVIEW-E2 Cleanup:** closing the preview releases any created object URL (no leak).

---

## 8. Trash — soft-delete, restore, purge (D9)

**AC-TRASH-01 — Soft-delete to Trash**
- Given a Manager deletes a file or folder,
- Then it disappears from the Drive and appears under **Trash**; deleting a folder cascades its entire subtree into Trash.

**AC-TRASH-02 — Restore**
- Given items in Trash,
- When the user selects and **Restore**,
- Then they return to their original location; restoring a folder restores its whole subtree (folders + files).

**AC-TRASH-03 — Purge (typed-confirm)**
- Given items in Trash,
- When the user chooses **Delete forever**,
- Then a dialog requires typing **DELETE** to enable the destructive button; on confirm, the rows + all their stored versions are permanently removed.

**Edge cases**
- **TRASH-E1 Empty Trash:** shows an empty state, not a blank panel.
- **TRASH-E2 Typed-confirm guard:** the **Delete forever** button stays disabled until the exact word `DELETE` is typed (case-sensitive); cancelling discards the typed value.
- **TRASH-E3 Selection isolation:** Trash selection is independent of the Drive selection; switching between Drive and Trash clears selection.
- **TRASH-E4 Restore name re-check:** restoring into a location that now has a same-name item is handled (backend re-collision-checks) — no silent duplicate-key failure.

---

## 9. Attachment types (D7) — Resource shell

**AC-TYPE-01 — List**
- Given an Admin opens **Documents → Document types**,
- Then a Resource list shows each type with name/description, allowed extensions (as pills), max size, and file count.

**AC-TYPE-02 — Create / edit**
- Given an Admin clicks **New type** (or edits a row),
- When they set name, optional description, comma-separated extensions, and an optional max-MB, and save,
- Then the type is created/updated and the list refreshes.

**AC-TYPE-03 — Delete**
- Given an Admin deletes a type (with confirm),
- Then the type is removed; existing files keep their bytes and merely lose that category (description states this).

**Edge cases**
- **TYPE-E1 Optional everywhere:** a type with no extensions = "Any" (within the system floor); no max-MB = "Tenant default" — both render explicitly, never blank.
- **TYPE-E2 Extension normalisation:** inputs like `.PDF`, ` pdf `, `docx` normalise to `pdf`, `docx` (dot-less, lowercase, trimmed).
- **TYPE-E3 Permission:** the Types page is gated `documents.configure`; a Manager (manage but not configure) gets the friendly NoPermission page, not a 403.

---

## 10. Settings (D12) — quota, default cap, sharing ceiling

**AC-SETTINGS-01 — Storage quota**
- Given an Admin opens **Documents → Settings**,
- When they set a storage quota (MB, blank = unlimited) and save,
- Then the value persists and the usage bar (here and in the Drive) reflects the quota.

**AC-SETTINGS-02 — Default upload cap**
- Given an Admin sets the default max file size (MB),
- Then untyped uploads are bounded by it (verified in §4).

**AC-SETTINGS-03 — Sharing ceiling present, inert in slice 1**
- Given the **Public link sharing** policy control (Off / View / Edit),
- Then it saves a value, with copy clarifying internal/user links are always available and this caps public links — **but no share UI exists yet** (enforcement is slice 05). The control must not imply sharing already works.

**Edge cases**
- **SETTINGS-E1 Unlimited:** blank quota = unlimited; the usage bar then shows used bytes without a progress meter.
- **SETTINGS-E2 Save feedback:** a successful save shows confirmation (toast); a failed save does not silently appear to succeed.

---

## 11. Storage usage bar (D12)

**AC-USAGE-01 — Live usage**
- Given a quota is set,
- Then the Drive sidebar shows `used / quota` with a progress bar; usage updates after uploads, deletes (note: soft-deleted items still count until purged), and purges.

**Edge case**
- **USAGE-E1 Over-quota visual:** as usage approaches/exceeds the quota the bar caps at 100% and the next upload is blocked per AC-UPLOAD-11 (no negative/overflow rendering).

---

## 12. Workflow events (D13) — backend, Phase B

**AC-EVENT-01 — File is triggerable**
- Given a workflow with an `entity.created` trigger on `file`,
- When a file is uploaded,
- Then the workflow fires (after-commit), and **failure of that workflow never 500s or blocks the upload** (failure-isolated).

**AC-EVENT-02 — Move/rename/delete emit**
- Given workflows on `entity.updated` / `entity.deleted` for `file`,
- Then move/rename emit updated and delete emits deleted, each isolated.

*(These are validated by backend tests in Phase B; the UI need only ensure uploads/edits complete normally whether or not a workflow is wired.)*

---

## 13. Permissions & gating (D15)

**AC-PERM-01 — Read gate**
- A No-access user opening `/documents` sees the friendly **NoPermission** page (never a raw 403).

**AC-PERM-02 — Manage gate**
- A Member sees no create/upload/rename/move/delete controls; the Drive is read-only for them.

**AC-PERM-03 — Configure gate**
- Types + Settings pages require `documents.configure`; absent it, the user is bounced to NoPermission. The **Documents** menu prunes child entries the user can't access (a user with only `documents.read` sees only "All documents").

**AC-PERM-04 — Backend is the boundary**
- Any UI gate bypass (direct API call) is still rejected server-side with the correct status (Phase B).

---

## 14. Responsive (house mandate)

**AC-RESP-01 — Desktop (~1280px):** tree sidebar + grid sit side-by-side; toolbar, breadcrumb, bulk bar, drawers and dialogs all fit without horizontal scroll.

**AC-RESP-02 — Mobile (~375px):** the sidebar stacks above the grid; the grid reflows to 2 columns; the breadcrumb scrolls horizontally; drawers/dialogs are full-width and usable; no clipped or overlapping controls.

**Edge case**
- **RESP-E1:** the 5-control toolbar (New folder, Upload, Uploads, Downloads, Trash) wraps gracefully on narrow widths rather than overflowing.

---

## 15. Guided process & foolproof-UI (user mandate)

**AC-UX-01 — Self-evident, no how-to copy**
- The Drive teaches nothing procedurally: controls are labelled (New folder, Upload, Download, Restore, Delete forever), empty states state status ("This folder is empty.", "Trash is empty.", "No uploads yet."), and there is **no** instructional/hint copy ("drag a file here to…", etc.).

**AC-UX-02 — Destructive actions guarded**
- Soft-delete is reversible (Trash); permanent purge requires typed **DELETE**; same-name uploads always ask before replacing. No destructive action is one irreversible click.

**AC-UX-03 — Only valid options offered**
- Move dialog disables no-op/illegal destinations (current location, the folders being moved); Preview appears only for previewable types; Replace/Keep-both appear only on an actual conflict; sharing controls don't pretend to share in slice 1.

**AC-UX-04 — Feedback at every step**
- Every async action shows progress or result: uploads show per-file progress + final state, ZIP shows preparing→ready, saves toast, failures show an actionable message with retry where applicable.

**AC-UX-05 — Selection model is predictable**
- Single click selects one; ⌘/Ctrl-click (or the card checkbox) toggles multi-select; clicking empty background clears selection; the bulk bar appears only when ≥1 item is selected and offers Download ZIP / Move / Delete; selection clears on folder navigation and on Drive↔Trash switch.

---

## 16. Cross-cutting edge cases (regression guards)

- **X-E1 Concurrent mutation:** two quick actions (e.g. delete then navigate) don't leave a stale grid; the tree and grid reconcile to the server state.
- **X-E2 Long names:** very long file/folder names truncate with the full name available (title/tooltip), never breaking the card layout.
- **X-E3 Special characters / unicode** in names render and round-trip correctly through create/rename/breadcrumb.
- **X-E4 Tenant isolation:** no folder, file, type, setting, or download job from another tenant is ever visible (Phase B backend test; UI shows only own-tenant data).
- **X-E5 Empty Drive:** a brand-new tenant with no folders/files shows a clean empty root + working Upload/New-folder, not an error.
- **X-E6 No "Dreamz"/no provider leakage:** tenant-facing copy stays neutral/white-label (no product-name strings on the Drive surface).

---

## Traceability — acceptance group → plan decision

| Acceptance group | Plan decision(s) |
|---|---|
| §1 Navigation / tree | D2 (shared tenant Drive), D14 (custom Drive surface) |
| §2 Folder ops + cycle guard | D4 (folders, cycle-guard), D14 |
| §3 File ops | D4 (files stable by id), D11 (key-by-id so move/rename never touch blobs) |
| §4 Upload + collision + floors + quota | D5 (collision→version), D6 (client drawer), D7 (type optional + sniff floor), D11 (quarantine), D12 (quota) |
| §5 Versioning | D5 (append, never overwrite) |
| §6 Download | D8 (direct single + async ZIP), D11 (presigned never cached) |
| §7 Preview | D10 (image+PDF inline, CSP-sandbox) |
| §8 Trash | D9 (soft-delete + cascade + restore subtree + typed-confirm purge) |
| §9 Attachment types | D7 (optional types), D14 (Resource shell) |
| §10 Settings | D12 (quota, default cap, sharing ceiling — enforced slice 05) |
| §11 Usage bar | D12 |
| §12 Workflow events | D13 (`file` triggerable, failure-isolated) |
| §13 Permissions | D15 (`documents.read/manage/configure`) |
| §14 Responsive | House responsive mandate |
| §15 Guided/foolproof UX | Foolproof-UI + no-inline-instructions mandates |
| §16 Cross-cutting | Tenant-scoping invariant, ClampedText, white-label |

---

## Explicitly OUT of scope (slice 05 — must NOT appear/work yet)

- Generating a share link (file or folder); the three tiers (internal/user/public); view/edit capability; expiry/password; the public pre-auth route; live-follow folder shares.
- The `documents.share` permission's effects; the `/documents/shares` oversight list.
- The `publicSharing` policy is **savable** in Settings but has **no functional effect** in slice 1 (it arms the slice-05 ceiling). Acceptance: the control exists, saves, and is honestly labelled — it does **not** claim sharing is available.

## Deferred to backlog (not acceptance failures in slice 1)

Per-folder restricted ACL (BL-094), ZIP-expand import (BL-095), office-doc preview (BL-096), restore-previous-version UI (BL-097), blob-prune/auto-purge (BL-098), AV scan (BL-099), wider sniff list (BL-100), entity-link wiring (BL-101).
