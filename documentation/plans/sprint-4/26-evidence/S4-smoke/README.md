# Plan 26 S4 smoke - Contacts module wired to the real backend

Date: 2026-09-06. Backend :8005 (`foundryx_service_s26`), frontend :3004 (prod build), `agent-browser --session s26`. Login `demo@example.com` / `demo1234`.

## Run log (real clicks from `/`, sidebar Omnichannel > Contacts)

1. **01-contacts-list-1280.png** - `/omnichannel/contacts` list loads 9 real rows from `GET /omnichannel/workspaces/{id}/contacts` - the 5 anchor demo contacts (Sarah Chen, Marcus Wong, Priya Raj, Daniel Lee, Aisha Abdullah) plus residue rows from earlier S1-S3 backend testing on this same DB (CleanProbe, Probe…, Live1, Live3). No console errors.
2. Search "Sarah" -> server-filtered to 1 row (real `search` param). Cleared via a full reload (see harness gotcha below).
3. **02-filter-applied-1280.png** - Filters popover: Name contains "Wong" -> 1 row (Marcus Wong), filter badge "1", "Save as segment" button appears.
4. Saved the filter as a real segment ("S4 Smoke Wong <ts>") via `POST /contact-segments` -> "Segment saved." toast; segment appears in the picker alongside a pre-existing "VIP Gold" segment (residue). Switched to it -> same filtered result from the real segment id; switched back to "All contacts" (the `'all'` sentinel correctly omits `?segment=` on the wire - see reconciliation below).
5. **03-columns-toggled-1280.png** - Columns menu: unchecked Email -> Assignee column shows real values ("Demo User" for 2 rows, "Unassigned" for the rest) - confirms per-view column prefs persist through the real `view_key` endpoint (unchanged A1 machinery). Re-checked Email to restore.
6. Selected 3 rows (checkboxes) -> bulk toolbar "3 selected / Actions / Export / Clear".
7. **04-bulk-assigned-1280.png** - Actions > Assign -> real member picker (Admin User/Demo User/Event Manager/Event Staff/KT Demo from the workspace) -> picked "Demo User" -> "3 contacts assigned." (`POST bulk/assign`), Assignee column updates live.
8. **05-bulk-tags-1280.png** - Actions > Add tags -> real tag picker (CleanProbeTag/Follow up/LiveProbeTag/ProbeTag/VIP) -> picked "⭐ VIP" -> "3 contacts tagged." (`POST bulk/tags`), VIP chip appears on all 3 rows.
9. **06-bulk-lifecycle-1280.png** - Actions > Move lifecycle -> real stage picker (New Lead/Hot Lead/Payment/Customer/Cold Lead) -> picked "💵 Payment" -> "3 contacts moved." (`POST bulk/lifecycle`), all 3 succeeded (this demo graph allows New Lead -> Payment directly, so no partial failure was produced by this particular data - the per-record failure path (`BulkResult.failed`) is exercised by `hooks/use-contact-bulk.test.ts`'s `reportBulkResult` tests instead).
10. **07-contact-created-1280.png** - "Add contact" -> filled First/Last name, phone `+60191788646656` (timestamped), email, left Lifecycle at the workspace's initial stage -> "Create contact" -> `POST /contacts` 201, "Contact created." toast, redirected to the real detail page (`/omnichannel/contacts/7ce5321a-...`) showing Details + Conversation tabs.
11. **08-duplicate-phone-422-1280.png** - New contact with Marcus Wong's exact phone (`+60 16-888 2211`) -> real 422 `{fieldErrors:{phone}}` mapped inline: "A contact with this phone number already exists."
12. **09-export-download-1280.png** - Export dialog (10 columns, all checked) -> Export -> network log confirms `POST .../contacts/export` 201 `{jobId}` immediately followed by `GET .../contacts/export/{jobId}/file` 200 (eager Celery locally finishes the job before the first poll) - the CSV downloaded via the browser's normal download flow, no errors.
13. **10-import-test-errors-1280.png** - Import wizard: uploaded a 3-row CSV (firstName,lastName,phone,email) with row 3's phone blank -> auto-mapped columns -> Test -> "2 valid / 1 invalid / 3 total", row 3 column `phone` "required".
14. Cancelled (redirected back to `?from=/omnichannel/contacts` per the shared import-engine convention), re-uploaded a corrected 3-row CSV as a fresh job -> Test -> "3 valid / 0 invalid" -> **11-import-committed-1280.png** - Import -> redirected to the list -> all 3 new contacts visible ("ImportGood One…", "ImportFixed Two…", "ImportGood Three…").
15. **12/13/14-*-375.png** - same list / create-form / detail page at a 375px viewport: toolbar wraps, table scrolls horizontally, form fields stack cleanly, Details/Conversation tabs sit side-by-side with no overlap or clipping. No console errors at any step.

## Mock-vs-backend differences reconciled (S4 coder)

1. **The shell's segment `SearchSelect` always carries a value** (`ALL_CONTACTS_SEGMENT_ID = 'all'`, `segment-picker.ts`), but the backend's `if segment_id:` check in `ContactListService._build_query` treats ANY truthy string as a real segment id and 404s `SegmentNotFound` for `'all'`. `contact-service.real.ts` drops the sentinel to `undefined` before it reaches the wire (list AND export) - covered by `services/contact-service.real.test.ts` ("drops the all contacts segment sentinel").
2. **No dedicated `/contacts/at` endpoint** (unlike `/roles/at`) - `getAt` re-issues `list()` computing the page that contains the requested index (`page = floor(index / pageSize)`), capped at the backend's `pageSize<=200`. Verified in the same test file.
3. **Export is a `background_jobs` job, not a synchronous response** - `exportContacts` posts, then polls `GET /jobs/{id}` (400ms x 5 attempts, ~2s window) before downloading; throws the shared `ExportPendingError` if the window elapses (never a silent failure - the UI's existing `exportPendingToast()` points the user at Jobs) and surfaces the job's own `error` as an `ApiError` on a failed job. Locally `CELERY_TASK_ALWAYS_EAGER=true` finishes the job before the POST even returns, so the pending-fallback path is exercised only in the vitest suite (`services/contact-service.real.test.ts`), not in the live smoke.
4. **The single-contact `GET`** rides the existing A1 `/omnichannel/contacts/{id}` route (`ThreadItem`, no `channels[]` - that field is a list/export-only decoration per D-A2-11) - `contact-service.real.ts get()` fills `channels: []` (an honest empty default, never fabricated) since the detail page never reads `.channels` off the single-record fetch.
5. **CSV tag/channel joins** - checked the live backend code (`contact_export_service.py _column_value`): both use `"; ".join(...)`, matching the S0 mock's assumption exactly - no reconciliation needed there (the brief's note about a comma-vs-semicolon mismatch did not reproduce on this branch's code).

## AC-CTM-45 check (backend wire diff since the last merged plan)

```
git diff d302ea7..HEAD -- service_backend/modules/omnichannel/routers/api_v1.py service_backend/modules/omnichannel/schemas.py
```

- `routers/api_v1.py`: **zero diff**.
- `schemas.py`: **112 insertions, 1 deletion** (the 1 deletion is an import-line reorder) - every addition is a NEW plan-26 class (`ContactChannelRef`, `ContactListItem`, `ContactListResponse`, `ContactCreate`, `BulkFailure`, `BulkResult`, `BulkAssignRequest`, `BulkTagsRequest`, `BulkLifecycleRequest`, `ContactExportRequest`, `ContactSegmentItem`, `ContactSegmentCreate`, `ContactSegmentUpdate`). No `Rio*` class touched.
- **Result: PASS** - no gateway/consumer-guide diff needed.

## Console errors

None observed across the full run (login, list, filters, segments, columns, bulk x3, create, duplicate-422, export, import x2, 375px pass). Only pre-existing shell-wide warnings logged (`Missing Description for {DialogContent}` on every `AlertDialog`/`Dialog` mount - not introduced by this slice).

## Harness gotchas (agent-browser session, not product bugs)

- **`click @ref` / CSS-selector `click` silently no-op'd on several buttons this session** (Filters, Clear-search, Columns, Actions, dialog Assign/Add/Move buttons, and - as a control test on the completely unrelated, already-shipped `/user-management/users` detail page - the Radix `Tabs` triggers). The workaround throughout was `agent-browser eval` calling `element.click()` directly on the matched DOM node, which fired reliably every time. `fill`/`upload`/keyboard-`press Escape` all worked normally via the plain CLI commands.
- **Radix `Tabs` (Details/Conversation) would not switch via ANY click method in this session** - ref-click, CSS-selector click, eval `.click()`, eval `.focus()` + `ArrowRight`, and a real mouse `move/down/up` sequence at the exact bounding-rect coordinates were all tried. A control test switching the **Security** tab on the unrelated, unmodified `/user-management/users/{id}` detail page reproduced the identical non-switching behavior, proving this is a session-wide CDP/harness quirk (not a regression from this slice - the Conversation tab's wiring itself was verified by source review: `contact-form-view`/`ContactDetailsTab` reuses the already-real A1 `ContactPanel`/`use-messages` hook unchanged since plan 25).
- **Row selection clears on segment/view switch** (by design, per the Resource-shell convention) - after switching the segment picker my earlier 3-row bulk selection was gone; re-selected before the next bulk action.
