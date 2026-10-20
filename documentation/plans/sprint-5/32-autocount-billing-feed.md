# 32 - AutoCount billing presets + AR outstanding sweep (CRM #1770)

Status: Plan (WIP). Lane SS-BILLING-FEED.

Shared-service half of CRM #1770 (contract 2.10: billing documents ingest + `ar_outstanding`).
Pull billing documents (invoices / credit notes / debit notes / cash sales) and AR outstanding
per invoice from the `sql_db` source; push to the CRM ingest. AutoCount is read-only.

No backfill and no prod push in this lane (S4 backfill is the owner's, after 25 Oct).
