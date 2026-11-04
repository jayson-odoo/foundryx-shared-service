# AutoCount write API on db3: Quotation and Sales Order probes (4 Nov 2026)

From Foundryx, lane AC-WRITE-QTSO (plan 57). Companion to `test-report-2026-11-04.md` (PO links).
All calls went to the `db3` test book through our write client, on documents we created (DocNo prefix
`FXT-1104q-`), except the two numbering probes noted below. Nothing was deleted. Every request,
response and before / after read was recorded exactly (15 writes, every one recorded); this report
shows the sanitised summary. Times are UTC (add 8 h for Malaysia time). Rows read as
`DtlKey item qty location unit price`.

| Probe | Time | Call | Status | Answer text | Rows read back after the call | Observed |
|---|---|---|---|---|---|---|
| P-QT1 | 09:39:47 | POST /NewQuotation FXT-1104q-QT1 | 200 | `DocNo=FXT-1104q-QT1 ,DocKey=12060 ... Created Successful.` | 12061 SRTUB6213-BI 1 HQ 900; 12062 SRTKT38SS 5 BRW-AM 126 | created as sent; header `Cancelled F`, `DocStatus A`, `ToDocType ""` |
| P-QT2 | 09:40:00 | PUT /EditQuotationbydockey 12060 | 200 | `... Done Edit.` | 12061 SRTUB6213-BI 2 HQ 850 (Discount "5%"); 12062 SRTKT38SS 5 HQ 126; 12063 SRTKT38SS 3 HQ 126 | every change applied: Ref, Description, Remark1, qty, unit price, discount, location, new row |
| P-QT3 setup | 09:40:13 | POST /NewQuotation FXT-1104q-QT4 | 200 | `DocNo=FXT-1104q-QT4 ,DocKey=12064 ...` | 12065 SRTUB6213-BI 1 HQ 900; 12066 SRTKT38SS 5 HQ 126 | created |
| P-QT3 | 09:40:14 | PUT /EditQuotationbydockey 12064, only row 12066 with Qty 0 | 200 | `... Done Edit.` | 12065 unchanged; 12066 SRTKT38SS 0 HQ 126 | Qty 0 accepted; the omitted row kept |
| P-DOC1 | 09:40:23 | POST /NewQuotation (our script error: DocNo `SO390188`) | 200 | `DocNo=SO390188 ,DocKey=12067 ...` | 12068 SRTUB6213-BI 1 HQ 900 | a quotation numbered SO390188 was created by mistake (Ref `P-DOC1-FXT1104q`); your sales order SO390188 untouched; clean-up asked in AQ34 |
| P-DOC2 | 09:40:24 | POST /NewQuotation DocNo `"<<New>>"` | 200 | `DocNo=QT-000001 ,DocKey=12069 ...` | 12070 SRTUB6213-BI 1 HQ 900 | AutoCount assigns the next number |
| P-DOC1b | 09:40:38 | POST /NewQuotation without DocNo | 500 | `Column 'DocNo' does not allow nulls` | none | DocNo is required |
| P-SO0 | 09:40:49 | POST /NewSalesOrder FXT-1104q-SO1, row from quotation row 12061 (FromDocType QT, FromDocNo FXT-1104q-QT1, FromDocDtlKey 12061, FullTransferOption " ") | 200 | `DocNo=FXT-1104q-SO1 ,DocKey=12072 ...` | 12073 SRTUB6213-BI 1 HQ 850 (FromDocType QT, FromDocNo FXT-1104q-QT1, FromDocDtlKey 0) | created; `FromDocDtlKey` reads 0 and the quotation shows no `ToDocType` / `ToDocKey` (AQ31) |
| P-SO1 | 09:41:01 | PUT /EditSalesOrderbydockey 12072 | 200 | `... Done Edit.` | 12073 SRTUB6213-BI 2 HQ 800 (Discount ""); 12075 SRTKT38SS 1 HQ 126 | the SO edit door exists; qty, price, discount and the new row applied (AQ33) |
| P-CX1 setup | 09:41:12 | POST /NewQuotation FXT-1104q-QT3 | 200 | `DocNo=FXT-1104q-QT3 ,DocKey=12076 ...` | 12077 SRTUB6213-BI 1 HQ 900 | created |
| P-CX1 | 09:41:13 | PUT /EditQuotationbydockey 12076, header `Cancelled "T"` | 200 | `... Done Edit.` | 12077 unchanged | NOT cancelled: `Cancelled` reads "F" (AQ32) |
| P-CX2 | 09:41:14 | same with `Cancelled "F"` | 200 | `... Done Edit.` | 12077 unchanged | no change |
| P-CX3 setup | 09:41:14 | POST /NewSalesOrder FXT-1104q-SO2 | 200 | `DocNo=FXT-1104q-SO2 ,DocKey=12078 ...` | 12079 SRTUB6213-BI 1 HQ 900 | created |
| P-CX3 | 09:41:15 | PUT /EditSalesOrderbydockey 12078, header `Cancelled "T"` | 200 | `... Done Edit.` | 12079 unchanged | NOT cancelled: `Cancelled` reads "F" (AQ32) |

## What this means for us

- Quotation create and edit, and Sales Order create and edit, work as documented (plus the SO edit door).
- Create answers carry the new DocNo and DocKey; we read the document back by that DocKey.
- Cancel is not possible through the API today; our cancel stays switched off until you add a door (AQ2).
- A Sales Order row taken from a quotation row keeps `FromDocType` / `FromDocNo` but not the row key, and
  the quotation shows no transfer (AQ31); we report that as a warning, never as a failure.
