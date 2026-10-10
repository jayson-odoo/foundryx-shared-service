# Plan 19 - Claude connector admin UI: browser pass (AC-19-60/61/62)

Lane SS-CONNECTOR-L, head 35b734ae. agent-browser session `ssconn`, backend :8031, frontend :3031 (fresh `rm -rf .next && npm run build`), DB `foundryx_service_ssconn`, demo admin of tenant `default` (Admin role already held connector.read/manage; no re-grant needed). Sorento deliberately DOWN (:8032). Evidence: `documentation/mockups/SS-CONNECTOR-L/evidence/`.

Setup note: the DB held 13 revoked grants and no active ones, so 3 throwaway active grants (`tst-active-1..3`, "Test User N") were inserted by SQL to exercise revoke; they were deleted at teardown. Revoked counts: 13 before, matches the UI (`1 - 13 of 13`). Screenshots of the grant Details tab (shows an email) were deleted, not saved. All saved screenshots show only "MCP User" / "Test User N".

## Results

| Step | Result | Evidence |
|---|---|---|
| 1 Sidebar Settings > Claude connector, Grants segments | PASS (counts 13 revoked / active / expired segment present; list matches DB) | 01-grants-active-1280, 01-grants-revoked-1280 |
| 2 Grant -> Details + Activity | PASS with defects D1, D2 (real call_log: 5 rows, tools, codes 200/403, chars, ms) | 02-activity-1280, 05-activity-375 |
| 3 Products: facts, secrets Set/Set, MCP URL copy, Refresh with sorento down | PASS: stale banner + error toast, never "Manifest refreshed". Defect D5 | 03-products-1280, 03-products-refresh-1280, 05-products-375 |
| 4 Revoke from row menu (plain confirm) | PASS: card "Actions > Revoke" -> "Revoke access?" confirm -> DB status revoked, reason admin; moves to Revoked. Defect D3 (list view has no row menu) | 04-row-menu, 04-revoke-confirm |
| 4b Bulk revoke typed REVOKE | PASS: 2 selected, Bulk actions > Revoke, button disabled until "REVOKE" typed exactly (disabled with "REV"), both revoked in DB | 04-bulk-select, 04-bulk-confirm |
| 5 375px: no horizontal scroll, cards, tabs | PASS: `documentElement.scrollWidth` = 375 on grants cards (active empty + revoked), detail, activity, products; tabs reachable | 05-* |
| 6 No instructional copy / "Foundryx" string / console errors | PASS: body text has 0 "Foundryx" (only the browser tab title reads "Foundryx", default tenant branding, not this surface); console empty after the full journey; no teaching copy seen |

AC mapping (by journey): AC-19-60 (grants list + revoke single/bulk) PASS; AC-19-61 (detail + activity) PASS-with-defects D1/D2; AC-19-62 (products + manifest refresh) PASS with D5.

## Defects (no product code edited)

- D1 (medium): Activity never shows the error code. `service_frontend/app/(protected)/settings/claude-connector/components/use-connector-activity-list-config.tsx:12-17` (Code column = HTTP status) and `:72-84` (Result column only renders "Truncated"); `service_frontend/types/connector.ts:20-29` `ConnectorCall` has no `errorCode`, though the backend sends it (`service_backend/modules/connector/schemas.py:44`). So `chat_history_not_permitted` / `reconsent_required` rows show only 403 and an empty Result. The task asked for chat_history_not_permitted to be visible: not met.
- D2 (low): Rows renders the literal text `null` when the row count is absent (same file, `:60-70`, `String(row.original[c.id])`). Show a dash.
- D3 (medium): Grants LIST view has no select column and no row "..." menu (table overflows to 1100px in a 950px container at 1280; no Actions column); revoke is only reachable from the CARD view and from the detail. Mock shows row checkboxes + "..." in the table.
- D4 (low): the red "ConnectError" toast from the manifest refresh never auto-dismissed; it stayed across tab switches and viewports until closed.
- D5 (low): stale banner and toast show the raw exception class `ConnectError` instead of a human message.
- D6 (cosmetic): at 375, one card click right after "Back" did not navigate (pathname unchanged); it worked after `scrollintoview`, so likely a harness/overlay artifact (toast overlapping), not confirmed as a product bug.

## Deviations from the approved mock (index.html)

- Toolbar has no Filters or Export buttons (only search, segment, view toggle, Columns); mock has both.
- Detail header lacks the record-nav (`< 2 / 3 >`) and the "..." Actions menu with Revoke; Activity tab is a separate Resource list with its own duplicated page title "Claude connector" + breadcrumb and an irrelevant Active/Trashed toggle, with lifecycle events as plain lines below instead of merged rows.
- Activity columns: Time/Tool/Code/Rows/Chars/ms/Result; mock has Event/Status(name)/Args and merged events.
- Breadcrumb on detail reads "... > Claude connector > Grant" (mock: the user's name).
- Revoke copy: "Revoke access? Claude loses access for this user immediately." (mock: "Revoke this grant? <user> loses Claude access to Sorento now ...").

## Teardown

Backend/frontend stopped (pids recorded, nothing left on :8031/:3031), `.env.local` restored from backup, test grants deleted, session `ssconn` closed. Nothing committed.

## Round 2

Head `1864555e` (round 2 = 664fb394 + 51464768, tunnel config af9f7458). agent-browser session `ssconn2`, backend :8031 (env on the command line, product Sorento at :8099 deliberately down), frontend :3031 fresh `rm -rf .next && npm run build`, DB `foundryx_service_ssconn` (10 real active grants "MCP User" with real call_log incl. error codes + 3 throwaway "Test User N" grants inserted by SQL, deleted at teardown). Real clicks from the sidebar (Settings > Claude connector), then row open, record-nav next, tabs. Evidence: `documentation/mockups/SS-CONNECTOR-L/evidence/round2/`. Screenshots showing the Details tab (carries an email) were deleted; none saved show a person name or email.

| Item | Result | Evidence |
|---|---|---|
| D1 Activity shows errorCode | PASS: `validation_error` in the Status column (call_log has error_code `validation_error`) | 08-activity-errors-1280 |
| D2 no literal "null" | PASS: Rows shows "-"; body text has no `null` | 07-activity-1280, 08 |
| D3 table view select + row "..." Revoke | PASS: select column + "..." per row -> Revoke; bulk "Actions" -> Revoke | 02-row-menu-1280, 04-bulk-select-1280 |
| D4 error toast auto-dismisses | PASS: toast visible at 2 s, gone at ~10 s (0 toasts) | 11, 12 |
| D5 stale banner sentence | PASS: "Sorento manifest is stale: last refresh failed (upstream_error). Serving the copy fetched ..." and toast "upstream_error", no "ConnectError" | 11-products-refresh-fail-1280, 20-products-375 |
| Dev: title + breadcrumb before tabs | PASS (Grants, Products, detail) | 01, 10 |
| Dev: Filters + Export | PASS (plus Columns) | 01-grants-1280 |
| Dev: detail record nav N/M + Actions menu | PASS: opened a row from the list (2 / 11), pressed next -> 3 / 11, "..." menu holds Revoke; breadcrumb ends with the grant name | 09-detail-actions-menu-1280, 23 |
| Dev: Activity one merged table, no page header, no Active/Trashed toggle | PASS: tool calls + "Consented" event in one table, search + Columns only | 07, 08 |
| Dev: revoke copy | PASS: single "Revoke this grant?" "Test User 3 loses Claude access to Sorento now. Connecting again asks them to sign in to Sorento." Bulk "Revoke 2 grants?" typed REVOKE, button disabled for "REV", enabled for "REVOKE"; DB confirms 2 revoked, reason admin | 03-revoke-single-1280, 05-bulk-confirm-1280 |
| Dev: product shows "Sorento" | PASS (list, cards, detail, Products) | 01, 22 |
| AC-19-60 grants list/segments/revoke/detail+Activity | PASS | above |
| AC-19-61 Products read-only, copy MCP URL, Refresh | PASS: facts, secrets Set/Set, copy button, refresh with Sorento down keeps last copy and shows stale banner | 10, 11 |
| AC-19-62 1280 + 375, no horizontal scroll, no instructional copy | PASS: `documentElement.scrollWidth` = viewport on products/grants list/grants cards/detail/activity at 375 and on all 1280 pages; console empty; 0 "Foundryx" in body text; no teaching copy | 20, 21, 22, 23 |

Remaining differences vs the mock (none in the checklist, all cosmetic): the Active|Revoked|Expired segments render as a dropdown, not a segmented control (shell N-way segment behavior); Activity "Status" is plain text, not a coloured badge; Activity at 375 is a horizontally scrolling table inside its card (mock shows cards); the Products tab has no tools table and no "Manifest stale" badge beside the title (the banner carries it); the grants table scrolls horizontally inside its own container at 1280 (page itself does not). D6 not reproduced.

Teardown: session `ssconn2` closed, backend/frontend pids stopped (:8031/:3031 free), `.env.local` restored, throwaway grants + events deleted, the failed manifest refresh left the Sorento manifest_cache flagged stale in `foundryx_service_ssconn` (harmless). Nothing committed.
