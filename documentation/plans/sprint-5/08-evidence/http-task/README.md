# AC-08-21 - HTTP task configuration on the open Mocha company - S5 real-backend evidence

Lane s37, backend :8007 -> HEAD `da5c82d3`, frontend :3007, DB `foundryx_service_s37`. Run
date 2026-09-12 (UTC). Continues from `08-evidence/open-company/` on the SAME company
(`Mocha 20260912T004004Z`, `d0b58883-6a87-46a3-abf1-0fe5aef8dd55`). Real clicks via
`agent-browser --session s37-tester`; see the open-company README for the `element.click()`
tooling note (CDP mouse dispatch did not register on several Radix controls in this session).

## Run log

1. Companies -> Mocha 20260912T004004Z -> Entities -> Add entity: dropdown offered exactly
   the six confirmed HTTP entities (Product, Customer, Warehouse, Product category, Brand,
   Unit of measure) - AC-08-18. Picked **Product** -> Configure -> task editor opened on
   **Source** tab, `API` chip (single, no toggle - an `http` company only ever offers API),
   connection locked "Mocha REST 20260912T004004Z" badge "No auth", path pre-filled
   `/itembypage`, Key columns `ItemCode` / Watermark `LastModified` pre-picked (AC-08-16
   preset). Screenshot `01-product-test-paged-1280.png` (post-Test).
2. Test -> **"Paged - 3,438 total - 4 pages of 1000 - a run walks every page"** (D14 exact
   wording, REAL total against the live Mocha `/itembypage`) + preview grid with real rows
   (ItemCode 2001.., real descriptions). Edit -> Save task -> toast "Task saved.".
3. Mapping tab: seeded rows byte-for-byte AC-08-16's table - `ItemCode->Code,
   Description->Name, Desc2->Description, ItemGroup->Category code, ItemBrand->Brand code,
   BaseUOM->Uom code, IsActive->Is active (Boolean)`, "Not delivered to Sorento: Discontinued
   -> Is discontinued (Provenance)". Screenshot `02-product-mapping-preset-1280.png`.
4. Schedule tab: Incremental every 15 minutes (task default), Reconcile daily at 02:00 UTC,
   Delete guard "20% of known rows (minimum 50)" - no false "needs a watermark" warning since
   one is picked. Screenshot `03-product-schedule-1280.png`.
5. Review & Activate: only the genuinely-true warnings ("no delivery target (logging only)",
   "no active category/UOM task yet") - no false "no query saved" (AC-08-19's HTTP-aware
   prerequisite check). Screenshot `04-product-review-activate-1280.png`.
6. Entities list: Product row BORN, Source badge **"Open API"** (AC-08-18). Screenshot
   `05-entities-product-born-open-api-1280.png`.
7. Add entity **Brand** -> Configure -> path pre-filled `/ItemBrand`, key `ItemBrand`, no
   watermark row (list has none) -> Test -> **"List - 0 rows - one request"**, "Query returned
   no rows." Screenshot `06-brand-test-list-envelope-empty-1280.png`. Verified independently
   against the live wrapper (`curl https://hapi.sorento.cc.cd/api/db2/ItemBrand` ->  `[]`) -
   Mocha genuinely carries zero AutoCount brands today; not a defect, the list-envelope
   handling (AC-08-14/22) is proven correct either way. Not saved (left as a reachable draft,
   proving "Add entity" never force-saves - mirrors the S1 mock evidence's own choice).
8. Add entity **Unit of measure** -> Configure -> path `/itembypage` (reused), "Derived from
   distinct values of" chips `BaseUOM` / `SalesUOM` / `PurchaseUOM` (D6), Key columns
   pre-picked `value`. Screenshot `07-uom-derived-chip-1280.png`. Test -> **"Paged - 3,438
   total - 4 pages of 1000 - a run walks every page"** (same `/itembypage` endpoint), distinct
   `value` column showing REAL Mocha UOM codes `UNIT` / `DZ` / `SET`. Screenshot
   `08-uom-test-distinct-values-1280.png`.
9. Viewport 375x812, same Unit of measure Source tab: renders cleanly, endpoint-path/Test row
   scrolls within its own bounded container, no page-level horizontal overflow. Screenshot
   `09-uom-test-375.png`.
10. `agent-browser console`: zero errors throughout.

## AC-08-21 coverage

PASS - Product (paged, real 3,438-item total, saved, preset mapping verified verbatim, born on
the Entities list) and Unit of measure (`distinctOf`, real BaseUOM/SalesUOM/PurchaseUOM values)
fully match the AC. Brand's live total is genuinely 0 on Mocha (verified independently against
the raw wrapper), which the list-envelope UI handles correctly (not a defect); the "list
envelope, one request" mechanic itself is the assertion, and it holds.
