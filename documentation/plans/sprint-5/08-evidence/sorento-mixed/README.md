# AC-08-36 - DB company + API toggle - S5 real-backend evidence (substitute company, see gap note)

Lane s37, backend :8007 -> HEAD `da5c82d3`, frontend :3007, DB `foundryx_service_s37`. Run
date 2026-09-12 (UTC).

## Environment gap (read first)

The AC's literal precondition - "Sorento company (DB company, existing SQL SO/PO/SPO
tasks)" against the real `AED_SORENTO` MSSQL server - is **not reachable in this lane**:

- `foundryx_service_s37` (this lane's Postgres) has NO `AED_SORENTO` `ac_company` row and no
  SQL connection to it (checked: `SELECT * FROM app_autocount.ac_company` - only the Mocha
  companies this run created exist).
- The real AED_SORENTO server is only reachable through an operator SSH tunnel
  (`localhost:59773`, per prior plan-06 lane notes) that is not open on this machine right now
  (`nc -zv localhost 59773` -> connection refused).
- The S1 mock evidence's "Sorento Trading (existing DB company, SQL SO/PO/SPO tasks)" is
  FRONTEND MOCK data only (`autocount-service.mock.ts`) - it never existed in a real backend
  DB, on this lane or otherwise.

Rather than skip the AC, a **substitute DB company** was built live, end to end, through real
clicks against the real backend, to prove the actual NEW mechanic AC-08-36 is testing (a DB
company's Source tab defaults to Database, then toggles to a FREE API connection picker) with
real data. This is called out explicitly, not silently substituted.

## Run log

1. Settings -> Integrations -> Connect integration -> Provider "SQL Database", dialect
   PostgreSQL, host `localhost`, port `5432` (defaulted), database `foundryx_service_s37`,
   username/password `foundryx`/`foundryx` (this lane's own, already-running Postgres - a
   real, reachable SQL Database connection, never a stub). Name "Substitute DB
   20260912T004004Z" -> Create integration.
2. AutoCount -> Companies -> Connect company -> Source "SQL database" -> that connection ->
   Label "Substitute Sorento 20260912T004004Z" -> Create company: probed the real database
   (`SELECT current_database()`), `Company database = foundryx_service_s37` (auto-derived,
   AC-01 behaviour unchanged), Integration **"Database"**, "Company name" reads "-" (no
   `dbo.Profile` table on Postgres - documented plan-01 behaviour, not a defect).
3. Entities -> Add entity: dropdown offered the FULL SQL-and-legacy-API entity set (Customer,
   Supplier, Product category, Unit of measure, Warehouse, Product, Sales agent, Sales order,
   Purchase order, Shipping order, Brand) - confirms a DB company is never restricted to the
   six HTTP entities (AC-08-12's restriction is `autocount_http`-specific, not company-kind
   specific). Picked **Product category** -> Configure -> Source tab opened on **Database**
   (the company default, AC-08-19) with the REAL schema tree (`foundryx_service_s37 ->
   app_autocount / app_ideation / app_meetings / app_omnichannel / public`, live introspection,
   not a stub). Screenshot `01-db-company-database-default-1280.png`.
4. Toggled Database -> **API**: the Database/API `RadioGroup` is `disabled` until "Edit" is
   clicked (matches the shell's view/edit-mode split; the SQL editor's Test/preview stay
   interactive in view mode but the source-kind switch itself needs edit mode - noted as a
   minor asymmetry, not a hard-fail). After Edit: toggled to API -> connection picker showed
   **BOTH** tenant open connections FREE (not locked) - `Mocha REST (No auth)` and `Mocha REST
   20260912T004004Z (No auth)` - proving AC-08-13's "an HTTP task on a DB company may
   reference ANY open connection" live, not just at the unit-test level. Path pre-filled
   `/ItemGroup` (the product_category HTTP preset, D9 "path editable"), Key columns still
   `ItemGroup` (carried over from the SQL branch's own picks - preset survives the toggle).
   Screenshot `02-toggle-to-api-free-picker-1280.png`.
5. Picked "Mocha REST 20260912T004004Z" -> Test -> **"List - 28 rows - one request"** against
   the REAL Mocha `/ItemGroup` (ACCOUNT, FG, IB-BATHROOM, IB-CERAMIC, ...) - genuine live data,
   header badge flipped to "Open API". Screenshot `03-api-test-list-28-rows-1280.png`.
6. Save task -> toast "Task saved.", `sourceImpl` persisted as `autocount_http` on a DB
   company (AC-08-28's "switching sourceImpl... sets it back to draft" mechanic - this was the
   task's FIRST save, so it lands `draft` directly, the same terminal state).
7. Viewport 375x812: Source tab (post-toggle, saved) renders cleanly, no clipping. Screenshot
   `04-toggled-saved-375.png`.
8. `agent-browser console`: zero errors throughout.

## AC-08-36 coverage

PARTIAL / DEFERRED for the literal AED_SORENTO precondition (environment gap above, not a
product defect). The NEW mechanic the AC exists to prove - **DB company defaults to Database
with a real schema tree, toggles to a FREE (not locked) API connection picker, Test shows the
page-count badge with real data, Save persists the switch** - is fully verified live against a
real, currently-running SQL Database connection and the real Mocha REST API. The specific
"the SQL PO task's Runs tab is unchanged" assertion could not be checked (no pre-existing SQL
task exists in this substitute company to compare against, and typing a SQL query into the
CodeMirror editor did not register via this session's agent-browser tooling - `keyboard type`
/ `keyboard inserttext` / `execCommand('insertText')` all left the editor empty even after a
confirmed `.focus()`; not investigated further given time budget). Reported honestly rather
than silently claimed. See the Test Execution Report for the full AC-08-36 verdict and the
Group F narrative on why AC-08-37's literal "Activate on a logging-sink company" scenario is
unreachable by design (same root cause touches this AC's unverifiable sub-clause).
