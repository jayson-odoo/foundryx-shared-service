# ITEM-TYPE-SS scout (2026-10-03)

Question: how does the shared-service AutoCount feed read items and push
ItemBrand / ItemCategory to the CRM (Sorento), and is ItemType read but dropped?

## Finding: shared-service has no item feed

- Synced entities are GRN, supplier, customer only:
  `service_backend/modules/autocount/services/company_service.py:100`
  (`SEEDED_ENTITIES`). The comment at `:82-97` records that the item routes
  (`Stock`, `StockItem`, `Item`, `StockGroup`, `StockCategory`, ...) were probed
  live on 2026-07-21, returned HTTP 500, and are deliberately left out. The
  standing guard: an entity is added only after its real payload has been captured.
- Canonical models exist only for suppliers/customers
  (`canonical/masters.py`) and GRN (`canonical/grn.py`). GRN lines carry
  `item_code` only (`canonical/grn.py:36`, `mapping.py:1046`), with no brand,
  category or type.
- The Sorento sink's ingest paths are `suppliers` and `customers` only
  (`sinks_sorento.py:62-64`). GRN has no ingest path, and there is no item path.
- Nothing under `service_backend/` or `service_frontend/` references
  `ItemBrand`, `ItemCategory` or `ItemType`. They appear only in the vendor
  Postman collection (`documentation/api/autocount/SL AutoCount API.postman_collection.json`,
  `POST /api/V2/Item/GetItem` filters).

So ItemBrand / ItemCategory do not reach the CRM through this service. Whatever
moves them today lives outside this repo, probably in Sorento's own AutoCount
pull or an n8n flow.

## Consequence for the lane

Shared-service has nothing to make "additive". Building an item entity here means
a new master end to end: vendor route capture, canonical model, mapping, a
Sorento `items` ingest path, and a Sorento canonical schema. Sorento's canonical
models set `extra="forbid"` (`canonical/masters.py:4`), so any new field must
land on the CRM side first or be rejected per record.
