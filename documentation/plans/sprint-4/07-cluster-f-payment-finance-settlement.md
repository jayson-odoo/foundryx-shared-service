# Sprint 4 · Plan 07 - Cluster F: Payment · Finance · Sales Order · Settlement (finance + crm modules + core gateway adapters)

**Status:** RE-GRILLED ×2 (2026-06-23) - post-split reality + financial-standards hardening (FeedMe/Eventbrite-grade) locked, ready to slice + build.
**Acceptance criteria (the contract - fulfil these):** `07-cluster-f-payment-finance-settlement-acceptance-criteria.md` (AC-07-01..53).
**Branch (future):** `sprint-4/07-cluster-f`
**Depends on:** Cluster B/CRM split (`08` - client/quotation/product in `modules/crm`, catalog→core) · Cluster D (`05` - tickets/participants/capacity) · **`03` Derived Status** (BUILT + merged - heaviest consumer: invoice Paid/Partially/Overdue/Refunded, SO Fulfilled, participant Eligible) · F2 (PDF render + repeater block) · core integration framework (`app/integrations`, `connections`, Fernet) · omnichannel webhook pattern · workflow + scheduler · `modules/finance` (invoices+invoice_lines already born in D).

> **Module-location correction (supersedes the 2026-06-18 grill).** Two module splits landed AFTER the first grill:
> - **Finance is its own module** `modules/finance/` (`app_finance` schema) - invoices/invoice_lines already live there. **Payments, refunds, settlements live in finance, NOT `app_ems`.** (The earlier plan's "finance entities in app_ems" line is wrong.)
> - **CRM is its own module** `modules/crm/` (`app_crm`) - leads/clients/quotations/products. **Sales Order lives in CRM** (next to quotation), not app_ems.
> - Real `Invoice` columns: `bill_to_type/bill_to_id` (Client|Profile), `project_product_id` soft-ref - NOT `client_id`/`product_id`.

---

## Scope - close the money loop

D creates **Draft invoices**; F makes them payable: Quotation (CRM)→**Sales Order** (CRM)→Invoice (finance)→**Payment** (B2B) and registration Invoice→Payment (attendee), via real **gateway checkout + webhooks** (core), with **refunds**, **tax**, **invoice PDFs**, and **client settlement/give-back**. Heaviest consumer of the (now-merged) plan-03 derived status.

## Locked decisions (re-grill 2026-06-23)

1. **Gateway plumbing = CORE; business reaction = FINANCE module.** Core owns the `PaymentProvider` protocol, Stripe/Billplz adapters (`app/integrations/`), `integration_logs`, connection lifecycle (Fernet + Test), and the **webhook receiver route**. Finance consumes core (`create_checkout`/`refund`) + **subscribes** to the payment event → writes the finance `payment` row → derived invoice Paid.
2. **Gateways on the connections framework, one-per-type lifted for `type=payment`.** Multiple payment connections per tenant (provider-unique); **per-project** via `project.payment_connection_id` (+ tenant default via `resolve_for_type`).
3. **Stripe + Billplz (FPX); hosted-redirect.** Stripe (cards) + Billplz (FPX online-banking + cards, X-Signature HMAC webhook, clean sandbox). Server creates a gateway session → **redirect** → return URL + **webhook** confirm. More via the provider contract.
4. **Webhook route = CORE, `connection_id` in the path.** `/integrations/webhooks/{provider}/{connection_id}` - `connection_id` → tenant (like omnichannel's `channel_id`). Fast-ACK + signature-verify + Celery, mirrors omnichannel. Idempotency = `UNIQUE(tenant_id, provider, external_event_id)`.
5. **Payment-row lifecycle = Pending-at-checkout, webhook flips it.** Finance creates a **Pending** `payment` row at "Pay" (it knows `invoice_id`), passes its id as `external_ref` into core `create_checkout`. Webhook → core emits a payment event keyed by `external_ref` → finance finds its Pending row → **Succeeded** → derived invoice Paid. Invoice↔payment link never lost on a slow webhook. **Abandoned Pendings reaped** by a scheduler pass (older than checkout TTL → Expired) so they never block re-pay.
6. **Payment dedup = method gates the path.** `CASH/CARD/BANK` = **manual** rows only (on-spot, B2B bank). `GATEWAY/FPX` = **webhook-created only**, never hand-entered. Method enum decides who writes the row → no double-credit.
7. **Sales Order = CRM, status-engine entity; ad-hoc partial invoicing.** SO Draft→Confirmed→**Fulfilled**(derived)→Cancelled. "Create invoice from SO" (a finance flow) picks lines + qty/% → finance invoice with `sales_order_id` soft-ref. **`SO.line invoiced_qty` is denormalized onto the CRM `sales_order_line`** - finance increments it via a CRM capability `crm.so_line_invoiced@1` on invoice-from-SO, so the **Fulfilled** derived trigger reads in-module CRM data (no cross-schema query). Instalment schedule = backlog.
8. **Invoice status graph: Cancelled + Void + Refunded.** D seeds Draft→Issued→Cancelled. F extends:
   - **Cancelled** = kill a Draft (no money).
   - **Void** = kill an Issued invoice with **zero payments** (manual - voids the issued document).
   - **Partially Paid / Paid** = **derived** ← Σ succeeded payments vs total.
   - **Overdue** = **derived (time)** ← `due_date < now` while Issued/Partially-Paid; via plan-03 scheduler re-eval sweep.
   - **Partially Refunded / Refunded** = **derived** ← Σ refunds vs Σ payments.
9. **Settlement = CRM-adjacent finance entity (status engine), primary + supplementary adjustment runs.** `project.commercial_mode {SELF_RUN, AGENCY}` + `fee_type {PERCENT|FLAT|PER_TICKET}` + `fee_value`. **One PRIMARY settlement per project** (rolls up paid attendee invoices − fee → net payable); a **post-remittance refund spawns a SUPPLEMENTARY adjustment settlement** (can be negative) so the clawback is auditable. Each settlement Draft→Approved→Remitted + `remittance_ref`. Actual disbursement = manual (out of scope). Stripe-Connect split-payout = backlog.
10. **Per-ticket refund via gateway API.** Refund selected tickets → gateway `refund` → webhook → refund record; tickets Void/Refunded (QR rotated dead); **capacity RELEASED** (RESERVED→free / GA sold−−); invoice **derived** Partially Refunded/Refunded; participant **Eligible re-derived** (drops if no valid paid admission ticket); settlement gross reduced (supplementary adjustment if already remitted).
11. **Tax = exclusive, round per-line (MY SST).** Prices tax-exclusive; `tax = round(line_amount × rate, 2)` per line, summed to the invoice tax; **tax summary grouped by rate** (6%/8%/exempt). **Single currency per tenant** (no FX). Reserve buyer TIN/SST-reg/tax-code/e-invoice-type. **MyInvois (LHDN) submission = a SEPARATE later integration** (reuses integration_logs + provider framework).
12. **Invoice/receipt PDF via the template engine.** New **`invoice` TemplateContext** (facts: invoiceNumber, buyer, **line items via the F2 repeater**, subtotal, **tax summary by rate**, total, payment status, payments table, e-invoice fields) + seeded default platform template; `render_document` (WeasyPrint). **Receipt = the SAME invoice doc in Paid state** (payments table + Paid stamp) - modern MY POS (FeedMe/StoreHub) issue one receipt = simplified tax invoice; no separate OR numbering (backlog). Attach to receipt email + download endpoint.
13. **On-spot scope.** F owns the payment model + manual "record payment" path (CASH/CARD) + derived Paid; verifiable now via a back-office record-payment form on the invoice. The **event-day scan-and-collect checkpoint UI = cluster H**, consuming F's payment API.

## Standards-hardening decisions (re-grill round 2, 2026-06-23) - make it FeedMe/Eventbrite-grade

14. **Money = `Numeric(14,4)` exact decimal, NEVER Float.** *(Resolved build-time 2026-06-23: was "integer sen" at grill; switched to `Numeric(14,4)` to match CRM's already-shipped quotation lines - one money type platform-wide, no CRM re-migration. Both exact; Float is the only wrong answer.)* All finance money columns (`subtotal/tax/total/unit_price/amount` + every new col) → `Numeric(14,4)`. Arithmetic uses Python `Decimal` (quantized 4dp), serialized JSON-safe; `lib/money.ts` formats at the edge. The **gateway adapter** converts `Decimal`↔integer-cents at its own boundary (one place). **Slice 0 migration** flips the existing finance Float cols → `Numeric(14,4)`.
15. **Core Numbering engine (`app/numbering/`) - Bukku/ERP-grade, horizontal.** New core feature, mirrors Terminology/Import engine shape. Code-side **`NumberSequenceDef` registry** (modules register doc types at boot; `active_modules`-filtered); tenant-editable config at **`/settings/numbering`** (Resource shell): prefix · format pattern with tokens `{prefix}{YYYY}{YY}{MM}{DD}{NNNN…}` + literals · reset period (never/yearly/monthly) · editable next-value. `next_number(db, tenant_id, doc_type, at_date)` = atomic **`SELECT … FOR UPDATE` counter row** (NOT Postgres `SEQUENCE` - native sequences skip on rollback = gaps = illegal). **Gapless**: number taken in the SAME commit as the state change → rollback returns it. **Assigned at state-change, not create** (Draft invoice = no number; burns one at Issue). Registered doc types: invoice, **credit_note** (refunds), receipt (= Paid invoice, reuses invoice number), sales_order, quotation, settlement. `{branch}`/`{project}` segment token = deferred. Built in **Slice 0**; all F + CRM docs consume it.
16. **Invoice immutable after Issue.** Draft = freely editable (no number). **Issued and beyond = lines/amounts/tax/buyer FROZEN** (service guard → 409); only status moves (payments/refunds) + non-financial fields (notes) change. Corrections = a **credit note** + (if needed) a new invoice - never mutate the original. No "edit issued invoice" escape hatch.
17. **Payment-write concurrency + idempotency.** Payment confirm (manual AND webhook flip) runs under `SELECT invoice FOR UPDATE` → sum succeeded payments → **reject overpayment (409)**; the Pending→Succeeded flip is **idempotent** (already-Succeeded = no-op, never re-credits - a real payment emits multiple webhook event types). Out-of-order webhooks tolerated via Celery retry. **No stored credit balance** in v1 (cash overpay = change at POS, never persisted as >total). Customer wallet/store-credit = backlog.
18. **Gateway processing fee tracked (`gateway_fee` sen on `payments`).** Captured from the webhook/balance-txn where the gateway reports it (Stripe balance_transaction fee; Billplz). Distinct from the agency give-back fee. **Settlement net = gross_collected − gateway_fees − agency_fee**, all three lines visible (Eventbrite-style). Pass-to-buyer booking fee (attendee-visible "+fee" at checkout) = backlog. Platform-fee-to-tenant (Foundryx revenue) = billing BL-036, out of scope.
19. **Refund hardening + credit notes.** **Refund method mirrors payment method**: gateway payment → gateway `refund` API + webhook; CASH/BANK payment → **manual refund record** (no API). **Over-refund guard** (Σ refunds ≤ Σ payments) under FOR-UPDATE. **Per-ticket refund only** in v1 (capacity-linked); arbitrary partial-amount goodwill refund = backlog. Each confirmed refund issues a **numbered credit note** (numbering engine doc type) + credit-note PDF (reuses the invoice template/context).
20. **Disputes/chargebacks captured (v1 minimal).** Stripe `charge.dispute.created` (+ Billplz equivalent) is logged to `integration_logs` + flips the payment to a **`Disputed`** state for visibility - never silently dropped. Full dispute-response workflow = backlog. **Webhook security depth (v1, S3)**: Stripe signing-secret + Billplz X-Signature HMAC + **timestamp tolerance** (reject stale events > N min, anti-replay).

## Data model

> **All money columns below are `Numeric(14,4)` exact decimal (decision 14) - NEVER Float.** (Annotated `(sen)` in places below = read as `Numeric(14,4)` money.) `tax_rate` stays a small decimal/`Numeric(5,4)` (a rate, not money).

```
# ---- core (horizontal) ----
number_sequences        id, tenant_id, doc_type, prefix, format_pattern, reset_period {NEVER|YEARLY|MONTHLY},
                        period_key (e.g. '2026' / '2026-06'), next_val
                        UNIQUE(tenant_id, doc_type, period_key)        # FOR UPDATE counter row (gapless)
# app/numbering/ - NumberSequenceDef registry; next_number(db, tenant_id, doc_type, at_date); /settings/numbering UI
integration_logs        id, tenant_id, integration_type, provider, direction {OUTBOUND|INBOUND},
                        endpoint, request_json (masked), response_json, http_status, external_ref,
                        external_event_id, created_at
                        UNIQUE(tenant_id, provider, external_event_id)  # inbound idempotency
# app/integrations/stripe_provider.py + billplz_provider.py  (type="payment")
# core route: POST /integrations/webhooks/{provider}/{connection_id}

# ---- modules/crm (app_crm) ----
sales_orders            id, tenant_id, client_id, project_id (nullable soft-ref), quotation_id (nullable),
                        doc_number (nullable, assigned at Confirm), currency,
                        subtotal, tax, total (sen), status_id (Draft→Confirmed→Fulfilled→Cancelled)
sales_order_lines       id, sales_order_id, product_id (nullable)|description, qty, unit_price (sen),
                        tax_rate, amount (sen), invoiced_qty   # invoiced_qty denormalized; finance writes via capability
# capability: crm.so_line_invoiced@1  (db, tenant_id, {so_line_id, qty}) -> increments invoiced_qty

# ---- modules/finance (app_finance) ----
invoices  (from D) + sales_order_id (nullable soft-ref), invoice_number (nullable, assigned at Issue → frozen),
                          due_date, issued_at, tax fields (all sen),
                          e-invoice reserved (buyer_tin, sst_reg_no, tax_code, einvoice_type)
                          status: Draft→Issued→Cancelled (D) →Partially Paid(d)→Paid(d)
                                  →Overdue(d,time)→Void→Partially Refunded(d)→Refunded(d)   # (d)=derived
                          # IMMUTABLE once status ≠ Draft (decision 16) - lines/amounts/buyer frozen
invoice_lines  (from D) + tax_rate, tax_amount (sen); unit_price/amount → sen
payments                id, tenant_id, invoice_id, amount (sen), gateway_fee (sen, nullable),
                        method {CASH|CARD|BANK|GATEWAY|FPX},
                        gateway_connection_id (→ core connections, nullable), external_ref (=payment id at checkout),
                        external_payment_id (gateway, nullable),
                        status_id (Pending→Succeeded→Failed→Expired→Refunded→Disputed), paid_at
                        # confirm/flip under SELECT invoice FOR UPDATE; flip idempotent (decision 17)
refunds                 id, tenant_id, invoice_id, payment_id (nullable), credit_note_number (assigned at confirm),
                        amount (sen), method {GATEWAY|FPX|CASH|BANK}, gateway_ref, reason, status, created_at
                        # refund method mirrors payment method; over-refund guarded (decision 19)
refund_lines            id, refund_id, ticket_id   # per-ticket linkage (ticket = Cluster D, soft-ref)
settlements             id, tenant_id, project_id, client_id, kind {PRIMARY|ADJUSTMENT},
                        gross_collected, gateway_fees, fee_type, fee_amount, net_payable (all sen),
                        status_id (Draft→Approved→Remitted), remittance_ref, generated_at
                        # net = gross_collected − gateway_fees − fee_amount (decision 18)
settlement_lines        id, settlement_id, invoice_id, amount (sen)   # contribution breakdown

# project (app_ems): + commercial_mode {SELF_RUN,AGENCY}, fee_type, fee_value, payment_connection_id (nullable soft-ref)
```

## Payment provider contract extension (core)
Extend `IntegrationProvider` with a **PaymentProvider** sub-protocol:
```python
create_checkout(connection, invoice, payment_ref, return_url, cancel_url) -> {redirect_url, external_ref}
verify_webhook(connection, body, headers) -> {external_event_id, event_type, external_payment_id,
                                              external_ref, amount, status} | raise
refund(connection, external_payment_id, amount) -> {refund_ref, status}
```
Stripe + Billplz adapters implement it; registered via `register_provider` at boot. Test = balance/ping (existing Test seam). The webhook receiver verifies, logs to `integration_logs`, dedupes on `external_event_id`, then emits a core payment event carrying `external_ref` → finance subscriber.

## Status-engine + derived consumers (Cluster F = the proof of plan 03, now merged)
- **`sales_order`** (CRM), **`payment`** (finance) status entities; **`invoice`** (finance) extended to the full graph; **`settlement`** (finance) status entity.
- **Derived (plan 03 `DerivedTrigger` + `aggregate_fact`):**
  - invoice `Partially Paid`/`Paid` ← Σ succeeded payments vs total (trigger entity = payment, owner = invoice, in-module).
  - invoice `Overdue` ← time (`due_date<now`) via scheduler re-eval sweep.
  - invoice `Partially Refunded`/`Refunded` ← Σ refunds vs Σ payments.
  - SO `Fulfilled` ← `Σ invoiced_qty ≥ Σ qty` over CRM `sales_order_lines` (in-module aggregate; fed by the `crm.so_line_invoiced@1` denormalization).
  - participant `Eligible` ← has a valid paid admission ticket (+ revoke on refund) - Cluster D's derived trigger, re-evaluated on refund.
- **Workflows (EMS/finance-seeded):** invoice `status_changed→Paid` → participant Eligible + tickets Valid + receipt email (PDF). Cross-entity orchestration = workflow (boundary rule); the Paid *derivation* itself = plan 03.

## Flows
- **Attendee checkout:** confirm cart (D) → Draft invoice → "Pay" → resolve `project.payment_connection_id` → finance creates **Pending payment** → core `create_checkout(payment_ref)` → redirect → gateway → **webhook** (verify + log + idempotent + Celery) → core event → finance flips Pending→Succeeded → derived invoice Paid → post-payment workflow.
- **B2B:** Quotation (CRM, Accepted) → **Sales Order** (CRM, Confirmed) → ad-hoc **Create invoice from SO** (lines/%; increments `invoiced_qty` via capability) → send → pay (gateway or manual BANK) → derived Paid → SO **Fulfilled** (derived) when fully invoiced.
- **On-spot (event day, H consumes):** cash/card → manual payment row (CASH/CARD) → derived Paid → ticket Valid.
- **Refund:** per-ticket → core gateway `refund` → webhook → refund record → tickets Void + capacity release + re-derive invoice/eligibility + settlement gross − (supplementary adjustment if already remitted).
- **Settlement:** AGENCY project → "Generate settlement" rolls up paid attendee invoices − fee → **PRIMARY** Draft → Approve → Mark remitted (ref). Post-remit refund → **ADJUSTMENT** settlement (may be negative).

## Slices (frontend-first → backend → TDD → E2E) - re-cut to 5 (Slice 0 = financial-primitive foundation)

0. **Foundation: core Numbering engine + money→sen migration.** (a) `app/numbering/` - `NumberSequenceDef` registry + `next_number` (FOR-UPDATE, gapless, period-reset) + `/settings/numbering` Resource-shell UI + seeded doc types (invoice/credit_note/receipt/sales_order/quotation/settlement). (b) **Backfill migration** flipping existing `modules/finance` Float money cols → `BigInteger` sen (×100) + a money format helper. **Must land before any F money/doc work** - retrofitting sen after payments/settlements exist is a nightmare.
1. **Finance: invoice depth + numbering + immutability + PDF (no live gateway).** Full invoice status engine with **derived** Partially Paid/Paid (via manual "record payment" CASH/CARD/BANK, FOR-UPDATE + overpay guard) + Overdue (time) + Void; **invoice_number at Issue** + **freeze-after-Issue** guard; per-line `tax_rate`/`tax_amount` (sen) + tax summary by rate + single-currency; reserved e-invoice fields; **`invoice` TemplateContext** + seeded platform template + WeasyPrint PDF + download; receipt = Paid-state PDF. **First heavy plan-03 wiring.**
2. **CRM: Sales Order + invoice-from-SO.** SO status entity (Draft→Confirmed→Fulfilled→Cancelled, `doc_number` at Confirm), lines, ad-hoc "create invoice from SO" (lines/%) writing finance invoices + the `crm.so_line_invoiced@1` capability + denormalized `invoiced_qty` + **derived Fulfilled**.
3. **Core + finance: gateways + checkout + webhooks.** `type=payment` one-per-type relaxation; Stripe + Billplz adapters (`create_checkout`/`verify_webhook`/`refund`); core **`integration_logs`** + core webhook route (`{provider}/{connection_id}`, **signature-verify + timestamp-tolerance** + idempotent + Celery + retry); **Pending-row-at-checkout** reconciliation + idempotent flip + `gateway_fee` capture; derived Paid wired live; **dispute webhook → Disputed state**; **post-payment workflow** (Eligible + tickets Valid + receipt email w/ PDF); abandoned-Pending reaper.
4. **Finance: refunds + settlement.** Per-ticket refund (method-mirrors-payment, gateway+webhook OR manual, over-refund guard, **numbered credit note** + PDF, capacity release + re-derive eligibility); settlement entity (status engine, fee config, **net = gross − gateway_fees − agency_fee** rollup, PRIMARY generate + approve + mark-remitted); post-remit refund → **ADJUSTMENT** settlement (may be negative).

## Deferred / backlog
- **MyInvois (LHDN) e-Invoicing** integration (submission/UIN/validation-QR/consolidated B2C) - separate plan reusing integration_logs + provider framework.
- **Customer credit-balance / wallet** (overpay or refund-to-store-credit) · **pass-to-buyer booking fee** (attendee-visible "+fee" at checkout) · **gateway→tenant payout reconciliation** (match Stripe/Billplz T+2 payouts ↔ invoices, organizer payout report) · **full dispute-response workflow** (evidence submission) · **daily Z-report / cash close** (reporting cluster) · **arbitrary partial-amount goodwill refund** (non-ticket).
- Separate **Official-Receipt numbering** series (strict two-doc tenants) · `{branch}`/`{project}` numbering token · Stripe Connect split-payout · instalment **schedule** on SO · embedded (non-redirect) checkout · promo/discount codes (Discount entity) · multi-currency FX · dunning (Overdue reminders) workflow pack · **inclusive-pricing (B2C) tax mode** (touches Cluster D ticket-price display).

## Resolved open targets (were open in the 2026-06-18 grill)
- ✅ D↔F invoice split: D = Draft→Issued→Cancelled; F adds Void + derived Partially Paid/Paid/Overdue/Partially Refunded/Refunded.
- ✅ FPX pick = **Billplz** (clean REST + sandbox + X-Signature HMAC webhook).
- ✅ Webhook placement = **core** route, `connection_id` in path → tenant.
- ✅ Settlement period = **per-project PRIMARY + supplementary ADJUSTMENT** runs.
- ✅ Manual vs gateway reconciliation = **method gates the path** + Pending-row-at-checkout (no double-credit).

## Sources (gateway/webhook patterns)
- omnichannel webhook receiver + idempotency (in-repo reference).
- Billplz API + X-Signature webhook docs (sandbox).
- [Concurrency-Safe / webhook idempotency patterns - Medium](https://medium.com/@suchirreddy31/%EF%B8%8F-designing-a-concurrency-safe-ticket-booking-system-from-scratch-6922db1b6401)
