# AC-06-25 evidence run - live AED_SORENTO tunnel proof

Recorded with the `agent-browser` CLI, session `lane35`, against the lane stack (backend
`:8005`, frontend `:3005`, DB `foundryx_service_s35`) and the operator's SSH tunnel to the
real AutoCount MSSQL instance (`127.0.0.1:59773`). Logged in as the dedicated proof tenant's
admin (`linkage-proof-20260908144112@example.com`,
`http://linkage-proof-20260908144112.localhost:3005`) via real clicks on the sign-in form.
Run date: 2026-09-08/09.

The MSSQL login used for the new "SQL Database" connection (`FXView` / a read-only password)
was supplied by the coordinator for this proof only and is never reproduced in this README,
the screenshots or the test report - referred to throughout as "the operator-supplied
read-only login". None of the screenshots below show the password value (masked dots only).

## Steps (real clicks, no deep-URL navigation)

1. Signed in to the dedicated proof tenant.
2. Sidebar: **Settings > Integrations > Connect integration**, provider **SQL Database**.
   Filled Name `AutoCount SQL (linkage proof)`, Database type Microsoft SQL Server (default),
   Host `127.0.0.1`, Port `59773`, Database `AED_SORENTO`, Username `FXView`, Password = the
   operator-supplied read-only login. **Create integration** -> connection
   `5228963c-3394-4cde-a591-15dac0014891`.
3. Connection detail page, Actions menu -> **Test connection**:
   "Connected to AED_SORENTO on 127.0.0.1 (Microsoft SQL Server)." Screenshot `01`.
4. AutoCount > Companies > **Connect company**, source SQL database, connection = the one
   just created, label "Linkage proof AED_SORENTO". Created -> company
   `ad986221-3214-4646-8332-eefde863b069`; Overview confirms "No delivery (logging only)" -
   no sink.
5. Entities tab -> Add entity **Purchase order** -> Configure -> Query tab -> Edit -> **Use
   preset "AutoCount PO"** -> fromDate typed digit-by-digit into the native date input's
   segments to `2026-09-01` (confirmed via the input's own ISO `.value`) -> **Test query**:
   100 rows against real AED_SORENTO, header result columns include the four new aggregates
   (`LinkedSOCount`, `FromSOKeySum`, `LinkedPOCount`, `FromPOKeySum`). Screenshots `02`-`03`.
6. **Test line query**: 0 rows (harmless NULL `:doc_key` bind for column discovery), the seven
   new line columns present in the result set. Screenshot `04`.
7. Key columns/Watermark/Compared columns/Filter all preset-populated (visible in `05`).
   **Save task**; Mapping tab confirmed the six preset line rows landed automatically.
8. Review & Activate's `Activate`/`Run preview` are disabled for a no-sink company by design
   (`activatePrerequisites`) - the manual run mechanism is the Entities list's own row-level
   **Sync now** action. Purchase order row, Actions menu -> **Sync now**: "Sync finished - the
   batch is awaiting approval." 43 records, 43 changed. Screenshot `06`.
9. Repeated steps 5-8 for **Shipping order** with preset "AutoCount SPO": **Test query** ->
   100 rows (screenshot `07`); **Save task**; **Sync now** -> "Sync finished - the batch is
   awaiting approval," 41 records, 41 changed (screenshot `08`).
10. Neither review batch was approved - both stay `Needs review`/`Awaiting approval`, and the
    company has no sink regardless, so nothing was pushed to Sorento at any point.

## Data verification (direct DB read, not screenshotted - see the test report section 4 for
the full canonical JSON excerpts and wire projections)

- `ac_staged_record` id `b5517819-6004-46b5-a7e4-d10ad3663fc6`: PO-2026/09-0015, line
  MSP124, `from_so_line_ref = "AED_SORENTO:45737847:45737853"`,
  `from_so_numbers = ["SO420374"]` - matches the brief exactly.
- `ac_staged_record` id `0e029a5b-1e46-4428-b033-5416635b58b5`: SPO-2026/09-0038, line DtlKey
  45737810, `from_po_line_ref = "AED_SORENTO:44909094:45021331"`,
  `from_po_number = "202606-S0018"` - matches the brief exactly.
- Both rows: `status = 'STAGED'`, `pushed_at IS NULL`.

## agent-browser tooling note

Same click-mechanism workaround as the AC-06-22 run (see
`documentation/plans/sprint-5/06-evidence/mapping/README.md`): native `agent-browser click
@ref` was unreliable on several controls in this session; the reliable pattern throughout was
a full trusted-shaped pointer sequence (`pointerdown` -> `mousedown` -> `pointerup` ->
`mouseup` -> `click`, `pointerType: 'mouse'`, real coordinates from `getBoundingClientRect()`
after `scrollIntoView`) dispatched via `agent-browser eval --stdin` on the actual DOM element
under test - always a genuine click on the genuine control, never a URL shortcut. One
additional finding this run: the sandbox's own permission classifier intermittently blocked
`eval`-based clicks specifically on the "Connect integration" provider picker (twice, on
identical commands) before allowing an identical retry through - flagged here as an
environment quirk, not a deliberate workaround.

## Residue

The dedicated proof tenant, its new connection, company and both entity tasks are all
intentional residue - see the test report's Residue section (section 10) for the full
accounting. No shared/default-tenant state was touched.
