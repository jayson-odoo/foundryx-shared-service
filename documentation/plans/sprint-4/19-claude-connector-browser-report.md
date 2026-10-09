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
