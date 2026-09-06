# AutoCount direct-DB SQL pack - SO / PO (+ masters) → Sorento

Companion to `22-autocount-db-etl.md`. These are the first real AutoCount
(SQL Server) queries for the `sql_db` source. Written against the customer's
schema dump (`AED_SORENTO.dbo.*`, AutoCount 2.x). Replace `AED_SORENTO` with
the company database name configured on the AutoCount company row - the
`source_ref` qualifier (`{DatabaseName}:{key}`) is taken from THAT config, not
from the SQL.

## 0. Contract recap (what the ETL runtime does to these statements)

| Rule | Consequence for the SQL below |
|---|---|
| Header query is wrapped: `SELECT * FROM (<query>) AS t WHERE t.<watermark> > :mark AND t.<docDate> >= :from_date ORDER BY t.<watermark>` | Every column must be named (MSSQL 8155), no duplicate names across joins, no top-level `ORDER BY` + `OFFSET/FETCH`. |
| Guard: single `SELECT`/`WITH`; banned tokens incl. `USE`, `INTO`, `DECLARE`, `EXEC` | Fully qualify `AED_SORENTO.dbo.X`; no temp tables, no variables. |
| Document task: exactly ONE `keyColumns`, `watermarkColumn` required, `docDateColumn` + `fromDate` required | `DocKey` / `LastModified` / `DocDate`. |
| `lineQuery` must bind `:doc_key`; runs once per changed header | `WHERE d.DocKey = :doc_key`. `ORDER BY` allowed here (not wrapped). |
| Line mapping is FIXED: result column name == canonical field | Alias `Qty AS qty_ordered`, `UnitPrice AS unit_price`, … exactly. A misnamed column is silently dropped. |
| `lineKeyColumn` / `lineProductColumn` / `lineWarehouseColumn` are picked in the UI | Keep those as native-named columns. |
| `customer_ref` / `supplier_ref` mint `{DatabaseName}:{value}` via `ref_customer` / `ref_supplier` | `value` MUST equal the master task's key. Customers/suppliers already in Sorento are keyed on **`AutoKey`** (API-path convention), so the header JOINs Debtor/Creditor and exposes `AutoKey`. |
| `product_ref` / `warehouse_ref` mint `{DatabaseName}:{lineProductColumn}` / `{…:lineWarehouseColumn}` | Must equal the product / warehouse master task's `keyColumns`. This pack keys BOTH on `AutoKey` (one rule; `ItemCode`/`Location` can be renamed in AutoCount - FKs are `ON UPDATE CASCADE`). |
| `sales_agent_ref` mints `agent:{CODE}` (upper, unqualified) | Pass `SalesAgent` code raw. |
| `status` vocabulary: `open · partial · fulfilled · closed · cancelled` | Derived in SQL from `Cancelled` (`'T'/'F'`), header `Transferable`, and line `TransferedQty` vs `Qty`; mapped with plain `string`. |
| `d_Boolean` = `'T'`/`'F'` strings | Compare as strings; masters' `is_active` uses transform `t_f_bool`. |
| `internal_note` is NOT on the PO wire | Do not map it for PO (Sorento `extra="forbid"`). |
| Row hash = all result columns minus key (unless `comparedColumns` set) | Keep column types stable across runs; avoid `varchar` renderings of numbers. |
| Caps: 5000 lines/header, 200k rows/page; a page is `AUTOCOUNT_PAGE_SIZE` headers (default 2000) | Paged extraction (plan sprint-5/03) - no more fixed 2000-headers-per-run cap. |
| **Line fingerprint** (plan sprint-5/03, AC-03-20) - `LineCount`/`QtySum`/`TransferedSum`/`SubTotalSum`/`MaxDtlKey` in the header's own `OUTER APPLY`, filtered `d.ItemCode IS NOT NULL` | Live 2026-09-05: header `LastModified` moved for only **19%** of fulfilled June-2026 SOs - fulfilment (`TransferedQty` rising) is a LINE fact. These columns are ordinary result columns (no engine knowledge of them); a line-only edit changes the header's row hash and so is picked up WITHOUT re-reading every header's lines on every pass. |
| **Pseudo-line exclusion** - `d.Qty IS NOT NULL` alongside `d.ItemCode IS NOT NULL`, in BOTH the line fingerprint `OUTER APPLY` and the `lineQuery` itself (SO §2, PO §4) | AutoCount lets a header carry a marker/bundle line - e.g. `ItemCode 'PP'` labelled `"PROMOTION PACKAGE"` - whose `ItemCode` IS present (the existing cut alone does not drop it) but whose `Qty` is NULL and price is zero: a grouping row, never a real quantity to deliver/receive. Left uncut, `LineCount` disagrees with what `lineQuery` actually fetches once ITS OWN cut drops the same row, tripping the LineCount-mismatch guard (S2, review round 4) on a perfectly normal document. 570 real SOs (18.6k marker lines) hit exactly this before both queries carried the SAME predicate. |

---

## 1. Sales Order - header query

Task: entity `sales_order`, `source_impl = sql_db`.

```sql
SELECT
    h.DocKey                                   AS DocKey,
    h.DocNo                                    AS DocNo,
    h.DocDate                                  AS DocDate,
    h.LastModified                             AS LastModified,
    h.DebtorCode                               AS DebtorCode,
    c.AutoKey                                  AS DebtorAutoKey,
    h.DebtorName                               AS DebtorName,
    h.SalesAgent                               AS SalesAgent,
    h.CurrencyCode                             AS CurrencyCode,
    h.YourPONo                                 AS CustomerPONo,
    CAST(COALESCE(h.UDF_DelDate, l.FirstDeliveryDate) AS date)
                                               AS RequestedDeliveryDate,
    h.Note                                     AS Note,
    h.Cancelled                                AS Cancelled,
    h.Transferable                             AS Transferable,
    h.DocStatus                                AS DocStatus,
    h.NetTotal                                 AS NetTotal,
    h.FinalTotal                               AS FinalTotal,
    CASE
        WHEN h.Cancelled = 'T'                              THEN 'cancelled'
        WHEN l.LineCount IS NULL OR l.LineCount = 0         THEN 'open'
        WHEN l.DoneCount = l.LineCount                      THEN 'fulfilled'
        WHEN h.Transferable = 'F'                           THEN 'closed'
        WHEN l.StartedCount > 0                             THEN 'partial'
        ELSE                                                     'open'
    END                                        AS status
FROM AED_SORENTO.dbo.SO AS h
LEFT JOIN AED_SORENTO.dbo.Debtor AS c
       ON c.AccNo = h.DebtorCode
OUTER APPLY (
    SELECT
        COUNT(*)                                                   AS LineCount,
        SUM(CASE WHEN d.TransferedQty >= d.Qty THEN 1 ELSE 0 END)  AS DoneCount,
        SUM(CASE WHEN d.TransferedQty > 0      THEN 1 ELSE 0 END)  AS StartedCount,
        MIN(d.DeliveryDate)                                        AS FirstDeliveryDate,
        -- line fingerprint (plan sprint-5/03, AC-03-20) - see §0's note.
        SUM(d.Qty)                                                 AS QtySum,
        SUM(d.TransferedQty)                                       AS TransferedSum,
        SUM(d.SubTotal)                                            AS SubTotalSum,
        MAX(d.DtlKey)                                               AS MaxDtlKey
    FROM AED_SORENTO.dbo.SODTL AS d
    WHERE d.DocKey = h.DocKey
      AND d.ItemCode IS NOT NULL
      AND d.Qty IS NOT NULL
) AS l
```

`source_config`

```json
{
  "query": "<above>",
  "lineQuery": "<§2>",
  "keyColumns": ["DocKey"],
  "watermarkColumn": "LastModified",
  "docDateColumn": "DocDate",
  "fromDate": "2026-08-01",
  "comparedColumns": [],
  "lineKeyColumn": "DtlKey",
  "lineProductColumn": "ItemAutoKey",
  "lineWarehouseColumn": "LocationAutoKey",
  "incrementalMinutes": 15,
  "reconcileMode": "dailyAt",
  "reconcileAt": "02:00"
}
```

Header mapping rows (operator-authored on the Mapping tab)

| Source column | Canonical | Transform |
|---|---|---|
| `DocNo` | `so_number` (required) | `string` |
| `DebtorAutoKey` | `customer_ref` | `ref_customer` (locked pair) |
| `SalesAgent` | `sales_agent_ref` | `ref_sales_agent` (locked pair) |
| `DocDate` | `doc_date` | `date` |
| `RequestedDeliveryDate` | `requested_delivery_date` | `date` |
| `status` | `status` (required) | `string` |
| `Note` | `internal_note` | `string` |

## 2. Sales Order - line query

```sql
SELECT
    d.DtlKey                    AS DtlKey,
    d.Seq                       AS Seq,
    d.ItemCode                  AS ItemCode,
    i.AutoKey                   AS ItemAutoKey,
    d.Location                  AS Location,
    w.AutoKey                   AS LocationAutoKey,
    d.Description               AS Description,
    d.Qty                       AS qty_ordered,
    d.TransferedQty             AS qty_delivered,
    d.UnitPrice                 AS unit_price,
    d.DiscountAmt               AS discount,
    d.SubTotal                  AS line_total,
    d.UOM                       AS uom,
    CAST(d.DeliveryDate AS date) AS required_date
FROM AED_SORENTO.dbo.SODTL AS d
LEFT JOIN AED_SORENTO.dbo.Item     AS i ON i.ItemCode  = d.ItemCode
LEFT JOIN AED_SORENTO.dbo.Location AS w ON w.Location  = d.Location
WHERE d.DocKey = :doc_key
  AND d.ItemCode IS NOT NULL
  AND d.Qty IS NOT NULL
ORDER BY d.Seq
```

Notes
- `ItemCode IS NOT NULL` drops AutoCount's description-only / sub-total /
  package-header rows. Verify on real data that no stock line has a NULL
  `ItemCode` (check `DtlType` distribution too).
- `Qty IS NOT NULL` drops AutoCount's pseudo-lines (`ItemCode` present,
  `Qty` NULL, price zero) - a marker/bundle item like `"PROMOTION PACKAGE"`
  that groups the real lines underneath it, never a real quantity. See §0's
  note - the SAME cut must also sit in the header's own `LineCount`
  `OUTER APPLY`, or the two disagree.
- `discount` uses `DiscountAmt` (money). The `Discount` column is text
  (`"10%"`, `"5+2"`) and would fail the `decimal` transform.
- `qty_ordered` is `Qty` in the line's `UOM`. `SmallestQty` is base-UOM; swap
  if Sorento products are keyed on base UOM only.
- Line `source_ref` becomes `{DatabaseName}:{DocKey}:{DtlKey}` automatically.

---

## 3. Purchase Order - header query

Task: entity `purchase_order`, `source_impl = sql_db`.

```sql
SELECT
    h.DocKey                                   AS DocKey,
    h.DocNo                                    AS DocNo,
    h.DocDate                                  AS DocDate,
    h.LastModified                             AS LastModified,
    h.CreditorCode                             AS CreditorCode,
    s.AutoKey                                  AS CreditorAutoKey,
    h.CreditorName                             AS CreditorName,
    h.PurchaseAgent                            AS PurchaseAgent,
    h.CurrencyCode                             AS CurrencyCode,
    CAST(l.FirstDeliveryDate AS date)          AS ExpectedDate,
    h.Cancelled                                AS Cancelled,
    h.Transferable                             AS Transferable,
    h.DocStatus                                AS DocStatus,
    h.NetTotal                                 AS NetTotal,
    h.FinalTotal                               AS FinalTotal,
    CASE
        WHEN h.Cancelled = 'T'                              THEN 'cancelled'
        WHEN l.LineCount IS NULL OR l.LineCount = 0         THEN 'open'
        WHEN l.DoneCount = l.LineCount                      THEN 'fulfilled'
        WHEN h.Transferable = 'F'                           THEN 'closed'
        WHEN l.StartedCount > 0                             THEN 'partial'
        ELSE                                                     'open'
    END                                        AS status
FROM AED_SORENTO.dbo.PO AS h
LEFT JOIN AED_SORENTO.dbo.Creditor AS s
       ON s.AccNo = h.CreditorCode
OUTER APPLY (
    SELECT
        COUNT(*)                                                   AS LineCount,
        SUM(CASE WHEN d.TransferedQty >= d.Qty THEN 1 ELSE 0 END)  AS DoneCount,
        SUM(CASE WHEN d.TransferedQty > 0      THEN 1 ELSE 0 END)  AS StartedCount,
        MIN(d.DeliveryDate)                                        AS FirstDeliveryDate,
        -- line fingerprint (plan sprint-5/03, AC-03-20) - see §0's note.
        SUM(d.Qty)                                                 AS QtySum,
        SUM(d.TransferedQty)                                       AS TransferedSum,
        SUM(d.SubTotal)                                            AS SubTotalSum,
        MAX(d.DtlKey)                                               AS MaxDtlKey
    FROM AED_SORENTO.dbo.PODTL AS d
    WHERE d.DocKey = h.DocKey
      AND d.ItemCode IS NOT NULL
      AND d.Qty IS NOT NULL
) AS l
```

`source_config` - identical to §1 except `query`/`lineQuery`.

Header mapping rows

| Source column | Canonical | Transform |
|---|---|---|
| `DocNo` | `po_number` (required) | `string` |
| `CreditorAutoKey` | `supplier_ref` | `ref_supplier` (locked pair) |
| `DocDate` | `issue_date` | `date` |
| `ExpectedDate` | `expected_date` | `date` |
| `CurrencyCode` | `currency` | `string` |
| `status` | `status` (required) | `string` |

Do **not** map `internal_note` on PO.

## 4. Purchase Order - line query

```sql
SELECT
    d.DtlKey                    AS DtlKey,
    d.Seq                       AS Seq,
    d.ItemCode                  AS ItemCode,
    i.AutoKey                   AS ItemAutoKey,
    d.Location                  AS Location,
    w.AutoKey                   AS LocationAutoKey,
    d.Description               AS Description,
    d.Qty                       AS qty_ordered,
    d.TransferedQty             AS qty_received,
    d.UnitPrice                 AS unit_cost,
    d.DiscountAmt               AS discount,
    d.SubTotal                  AS line_total,
    d.UOM                       AS uom,
    COALESCE(d.UDF_Currency, h.CurrencyCode) AS currency,
    CAST(d.DeliveryDate AS date) AS expected_date
FROM AED_SORENTO.dbo.PODTL AS d
JOIN      AED_SORENTO.dbo.PO       AS h ON h.DocKey    = d.DocKey
LEFT JOIN AED_SORENTO.dbo.Item     AS i ON i.ItemCode  = d.ItemCode
LEFT JOIN AED_SORENTO.dbo.Location AS w ON w.Location  = d.Location
WHERE d.DocKey = :doc_key
  AND d.ItemCode IS NOT NULL
  AND d.Qty IS NOT NULL
ORDER BY d.Seq
```

---

## 5. Masters the documents depend on

Documents are `_DEPENDENT_ENTITIES`: an unresolved `*_ref` is a `retryable`
verdict and the document stays staged until the master lands. Sync order:
customers / suppliers / products / warehouses / sales agents → SO → PO.

All keyed on `AutoKey` so refs line up with §1 - §4.

### 5.1 Customer (`customer`) - replaces the API-path task if switching to DB

```sql
SELECT
    c.AutoKey        AS AutoKey,
    c.AccNo          AS AccNo,
    c.CompanyName    AS CompanyName,
    c.Desc2          AS Desc2,
    c.RegisterNo     AS RegisterNo,
    c.Address1       AS Address1,
    c.Address2       AS Address2,
    c.Address3       AS Address3,
    c.Address4       AS Address4,
    c.PostCode       AS PostCode,
    c.Attention      AS Attention,
    c.Phone1         AS Phone1,
    c.Phone2         AS Phone2,
    c.Mobile         AS Mobile,
    c.Fax1           AS Fax1,
    c.EmailAddress   AS EmailAddress,
    c.WebURL         AS WebURL,
    c.SalesAgent     AS SalesAgent,
    c.DebtorType     AS DebtorType,
    c.AreaCode       AS AreaCode,
    c.CurrencyCode   AS CurrencyCode,
    c.DisplayTerm    AS DisplayTerm,
    c.CreditLimit    AS CreditLimit,
    c.TaxCode        AS TaxCode,
    c.IsActive       AS IsActive,
    c.LastModified   AS LastModified
FROM AED_SORENTO.dbo.Debtor AS c
```
`keyColumns: ["AutoKey"]`, `watermarkColumn: "LastModified"`. `is_active` ← `IsActive` via `t_f_bool`.
Same `source_ref` as the API path (`{DatabaseName}:{AutoKey}`), so no duplicate wave in Sorento.

### 5.2 Supplier (`supplier`)

Same as 5.1 over `AED_SORENTO.dbo.Creditor` (`PurchaseAgent` instead of `SalesAgent`, `CreditorType` instead of `DebtorType`).

### 5.3 Product (`product`)

```sql
SELECT
    i.AutoKey            AS AutoKey,
    i.ItemCode           AS ItemCode,
    i.Description        AS Description,
    i.Desc2              AS Desc2,
    i.ItemGroup          AS ItemGroup,
    i.ItemType           AS ItemType,
    i.ItemBrand          AS ItemBrand,
    i.ItemClass          AS ItemClass,
    i.ItemCategory       AS ItemCategory,
    i.BaseUOM            AS BaseUOM,
    i.SalesUOM           AS SalesUOM,
    i.PurchaseUOM        AS PurchaseUOM,
    i.StockControl       AS StockControl,
    i.HasSerialNo        AS HasSerialNo,
    i.HasBatchNo         AS HasBatchNo,
    i.TaxCode            AS TaxCode,
    i.PurchaseTaxCode    AS PurchaseTaxCode,
    i.TariffCode         AS TariffCode,
    i.MainSupplier       AS MainSupplier,
    i.IsActive           AS IsActive,
    i.Discontinued       AS Discontinued,
    i.LastModified       AS LastModified
FROM AED_SORENTO.dbo.Item AS i
```
`keyColumns: ["AutoKey"]`, `watermarkColumn: "LastModified"`. Omit `[Image]` (varbinary MAX - hashing cost, no consumer field).

### 5.4 Warehouse (`warehouse`)

```sql
SELECT
    w.AutoKey       AS AutoKey,
    w.Location      AS Location,
    w.Description   AS Description,
    w.Address1      AS Address1,
    w.Address2      AS Address2,
    w.Address3      AS Address3,
    w.Address4      AS Address4,
    w.PostCode      AS PostCode,
    w.Phone1        AS Phone1,
    w.Contact       AS Contact,
    w.IsActive      AS IsActive
FROM AED_SORENTO.dbo.Location AS w
```
`keyColumns: ["AutoKey"]`, no watermark (no `LastModified`; tiny table, full snapshot each run - `incrementalMinutes` floor is 15 without a watermark).

### 5.5 Product category (`product_category`)

```sql
SELECT
    g.ItemGroup     AS ItemGroup,
    g.Description   AS Description,
    g.Desc2         AS Desc2
FROM AED_SORENTO.dbo.ItemGroup AS g
```
`keyColumns: ["ItemGroup"]` (this table has no `AutoKey`). No watermark.

### 5.6 Sales agent (`sales_agent`)

Not in the schema dump. AutoCount stores agents in `dbo.Agent`
(`Agent`, `Description`, `IsActive`). Task query
`SELECT a.Agent AS Agent, a.Description AS Description, a.IsActive AS IsActive FROM AED_SORENTO.dbo.Agent AS a`,
`keyColumns: ["Agent"]` - ref is `agent:{AGENT}` (upper-cased, unqualified),
which is exactly what `SO.SalesAgent` feeds into `sales_agent_ref`.

---

## 6. Things to verify on the customer's DB before activation

1. **`SO.LastModified` moves on a line-only edit.** The whole incremental
   design trusts it (BL-SS-036). Edit one `SODTL` row in AutoCount, re-read
   `SO.LastModified`. If it does NOT move, fall back to reconcile-only or add
   `SODTL` change detection (code change).
2. **`DocStatus` semantics.** `char(1)` + `ExpiryTimeStamp` index suggests
   draft/expired documents. `SELECT DocStatus, COUNT(*) FROM SO GROUP BY DocStatus`.
   If drafts exist (e.g. `'D'`), add `AND h.DocStatus = 'A'` - but note the
   header wrap ANDs its own predicates, so filter inside the query body.
3. **Non-stock lines.** `SELECT DtlType, COUNT(*) FROM SODTL WHERE ItemCode IS NULL GROUP BY DtlType` - confirm `ItemCode IS NOT NULL` is the right cut.
4. **Read-only login.** `pymssql` only, SQL auth; grant `db_datareader` on the
   company DB and nothing else (no session read-only on MSSQL - the guard +
   login ARE the boundary).
5. **Preview each query in the task editor first** - key/watermark/docDate
   pickers only populate from a fresh preview, and the save-time wrap run
   surfaces MSSQL 8155/duplicate-name errors as a 422 instead of at run time.
6. **`fromDate` sizing.** 2000 headers/run cap. Count
   `SELECT COUNT(*) FROM SO WHERE DocDate >= '2026-08-01'` and pick a window
   under the cap for the first load, then widen.
7. **Sorento must be on the G3 contract** (`feat/autocount-cross-repo-contract`:
   `POST /api/v1/external/ingest/sales_orders|purchase_orders`, `companyCode`
   anchor, ref-keyed masters, per-line `source_ref`). Sorento `main` has masters
   only → `404 UNKNOWN_ENTITY`; the older `fix/ingest-status-codes-and-dry-run`
   branch uses `/external/sales-orders/ingest` + code-keyed lines → also 404.
   The local `sorento-crm` clone is stale (tip 2026-08-14) - fetch before
   testing hop 2.
