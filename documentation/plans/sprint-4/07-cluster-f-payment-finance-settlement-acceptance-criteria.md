# Sprint 4 · Plan 07 — Cluster F: Payment · Finance · SO · Settlement · Acceptance Criteria

**Source plan:** `07-cluster-f-payment-finance-settlement.md` (RE-GRILLED ×2, 2026-06-23)
**Scope:** the close-the-money-loop cluster + its two financial-primitive foundations (core Numbering engine, money→sen). FeedMe/Eventbrite-grade bar.

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. The Test Execution Report keys back PASS/FAIL/DEFERRED per AC id.

**Modules:** `app/numbering` + `app/integrations` (CORE) · `modules/finance` (`app_finance`) · `modules/crm` (`app_crm`) · `app_ems` (project fields).

> **Money type (resolved 2026-06-23, build-time):** all money columns = **`Numeric(14,4)`** (exact decimal, Python `Decimal`) — matches CRM's already-shipped quotation lines, one money type platform-wide. The original grill said "integer sen"; switched to `Numeric(14,4)` to avoid re-migrating built CRM tables (both are exact — **Float is the only wrong answer**). The gateway adapter converts `Decimal`↔integer-cents at its own boundary (one place). Wherever an AC below says "sen", read **`Numeric(14,4)` money**. `tax_rate` stays a small decimal (a rate, not money).

---

## Slice 0 — Foundation: core Numbering engine + money→sen

### AC-07-01 — money columns are `Numeric(14,4)`, never Float [BE][T]
- **Given** the Slice-0 migration ran, **when** inspecting every money column across `app_finance` (invoices/invoice_lines/payments/refunds/settlements), **then** each is **`Numeric(14,4)`** (exact decimal) — **zero `Float`/`Double` money columns remain**. CRM money stays its existing `Numeric(14,4)`. `tax_rate` stays a small decimal (a rate, not money).
- **Given** an existing finance invoice that held `total=12.5` (Float), **when** the migration runs, **then** it reads `12.5000` (`Numeric`), no precision loss.

### AC-07-02 — money arithmetic is Decimal, formatted at the edge [BE][T]
- **Given** finance services, **when** any money sum/tax/total is computed, **then** it uses Python `Decimal` (never float), quantized to 4 dp; the wire/Pydantic serializes it JSON-safe (string or number) and the frontend `lib/money.ts formatMoney` renders it in the tenant currency. No float appears in any money arithmetic path.

### AC-07-03 — Numbering registry + active-module filter [BE][T]
- **Given** `NumberSequenceDef`s registered at boot (invoice, credit_note, receipt, sales_order, quotation, settlement), **when** listing the numbering catalog for a tenant, **then** only doc types whose owning module is **active for that tenant** appear (core types always; finance/crm types only when installed). `'core'` types always visible.

### AC-07-04 — `next_number` is gapless + concurrency-safe [BE][T]
- **Given** a tenant invoice sequence at `next_val=1`, **when** two concurrent transactions each call `next_number(db, tenant, 'invoice')`, **then** they receive **distinct consecutive** numbers (1, 2) via a `SELECT … FOR UPDATE` counter row — never the same number, never a skip.
- **Given** a transaction that calls `next_number` then **rolls back**, **then** the counter is **not advanced** (the number is returned, no gap).
- It uses a FOR-UPDATE table row, **NOT** a Postgres `SEQUENCE` (a sequence skips on rollback = illegal gap).

### AC-07-05 — format tokens + per-period reset [BE][T]
- **Given** a config `prefix=INV`, `format={prefix}/{YYYY}/{NNNNNN}`, `reset_period=YEARLY`, **when** issuing the first invoice of 2026, **then** the number is `INV/2026/000001`; the 2nd is `INV/2026/000002`.
- **Given** the same config crossing into 2027, **when** issuing the first 2027 invoice, **then** the counter resets → `INV/2027/000001` (period_key bucket). `{YY}/{MM}/{DD}` + padding `{NNNN…}` (N count = pad width) + literals all resolve.

### AC-07-06 — number assigned at state-change, not create [BE][T]
- **Given** a Draft invoice, **when** inspected, **then** `invoice_number` is **NULL** (a deleted draft burns no number).
- **Given** the same invoice transitioning Draft→Issued, **then** `invoice_number` is assigned in the **same commit** as the status change and is non-NULL thereafter.

### AC-07-07 — numbering settings UI (Resource shell) [FE][E2E]
- **Given** a `terminology.manage`-class authorized user at `/settings/numbering`, **when** the page loads, **then** it is the **Resource-shell** list (search/sort/column-prefs) of doc types showing prefix/format/reset/next-val — **not** a hand-rolled table.
- **When** the user edits the invoice prefix to `INV` + next-val to `100` and saves, **then** the next issued invoice is numbered from `100`. Verified at 375px AND 1280px.

---

## Slice 1 — Finance: invoice depth + numbering + immutability + PDF (no live gateway)

### AC-07-08 — full invoice status graph seeded/extended [BE][T]
- **Given** a tenant with finance installed, **when** inspecting the `invoice` status entity, **then** the graph is Draft→Issued→Cancelled (from D) **extended** with Void + derived Partially Paid/Paid/Overdue/Partially Refunded/Refunded. Existing tenants' graphs are **backfilled** (not seed-if-absent only) so pre-F invoices gain the new states.

### AC-07-09 — invoice frozen after Issue [BE][T]
- **Given** an **Issued** invoice, **when** a `PATCH` attempts to change any line/amount/tax/buyer, **then** **409** (immutable after Issue).
- **Given** a **Draft** invoice, **then** the same edit succeeds. Non-financial fields (notes) remain editable post-Issue.

### AC-07-10 — manual record-payment, CASH/CARD/BANK only [BE][FE][T]
- **Given** an Issued invoice, **when** an authorized user records a CASH/CARD/BANK payment via the back-office form, **then** a `payment` row is created (method ∈ {CASH,CARD,BANK}) and the invoice re-derives.
- **Given** an attempt to manually create a `GATEWAY`/`FPX` payment row, **then** it is **rejected** (those are webhook-created only — method gates the path).

### AC-07-11 — derived Partially Paid / Paid from Σ payments [BE][T]
- **Given** an Issued invoice `total=10000` sen with one Succeeded payment of `4000`, **when** derivation runs, **then** the invoice is **Partially Paid**.
- **When** a second Succeeded payment of `6000` lands (Σ=10000), **then** it derives to **Paid**. Sums are exact integer sen.

### AC-07-12 — overpayment rejected under lock [BE][T]
- **Given** an invoice `total=10000` with `7000` already Succeeded, **when** two concurrent payments of `5000` each try to confirm, **then** under `SELECT invoice FOR UPDATE` only the set that keeps Σ ≤ total succeeds; the excess is **rejected (409)** — Σ payments never exceeds total. No stored credit balance.

### AC-07-13 — Overdue is time-derived [BE][T]
- **Given** an Issued/Partially-Paid invoice with `due_date < now` and not fully Paid, **when** the scheduler re-eval sweep runs, **then** it derives to **Overdue**.
- **Given** the same invoice once fully Paid, **then** it is **not** Overdue (Paid wins; no Overdue from a terminal-paid state).

### AC-07-14 — Void only from Issued + zero payments [BE][T]
- **Given** an Issued invoice with **no** payments, **when** an authorized user Voids it, **then** it moves to **Void**.
- **Given** an invoice with any Succeeded payment, **then** Void is **not** available (use refund); **given** a Draft, **then** Cancel (not Void) applies.

### AC-07-15 — per-line tax exclusive, round per-line, summary by rate [BE][T]
- **Given** lines with `tax_rate` 0.06 and 0.08, **when** the invoice computes tax, **then** `tax_amount = round(line_amount × rate)` **per line** (in sen), summed to the invoice tax; the invoice carries a **tax summary grouped by rate** (6%/8%/exempt). Prices are tax-exclusive.

### AC-07-16 — reserved e-invoice fields present, inert [BE][T]
- **Given** an invoice, **when** inspecting columns, **then** `buyer_tin/sst_reg_no/tax_code/einvoice_type` exist and are settable but drive **no** submission logic (MyInvois = separate later plan).

### AC-07-17 — invoice TemplateContext + PDF + download [BE][FE][E2E]
- **Given** the seeded platform `invoice` template, **when** rendering an invoice, **then** `render_document` (WeasyPrint) produces a PDF with invoiceNumber, buyer, **line items via the F2 repeater block**, subtotal, tax-summary-by-rate, total, payment status, e-invoice fields.
- **When** a user clicks Download on the invoice detail, **then** the PDF downloads. Verified 375px AND 1280px.

### AC-07-18 — receipt = Paid-state invoice PDF [BE][T]
- **Given** a fully-Paid invoice, **when** the PDF renders, **then** it shows a **payments table + Paid stamp** = the receipt (same template/number, no separate OR series in v1).

---

## Slice 2 — CRM: Sales Order + invoice-from-SO

### AC-07-19 — SO status entity + doc number at Confirm [BE][T]
- **Given** the `sales_order` status entity, **when** inspecting the graph, **then** Draft→Confirmed→Fulfilled→Cancelled. `doc_number` is NULL in Draft, assigned at **Confirm** via the numbering engine.

### AC-07-20 — SO with lines, from quotation [BE][FE][T]
- **Given** an Accepted quotation (CRM), **when** a user creates a Sales Order, **then** the SO carries lines (product/description, qty, unit_price sen, tax_rate, amount sen, `invoiced_qty=0`) and links `quotation_id`.

### AC-07-21 — create invoice from SO (partial lines/%) [BE][FE][E2E]
- **Given** a Confirmed SO, **when** a user runs "Create invoice from SO" picking lines + qty/%, **then** a **finance** invoice is created with `sales_order_id` set; only the chosen qty is invoiced.

### AC-07-22 — invoiced_qty denormalized via capability [BE][T]
- **Given** "create invoice from SO" invoicing 3 of 10 units of an SO line, **when** the finance flow calls the CRM capability `crm.so_line_invoiced@1`, **then** the CRM `sales_order_line.invoiced_qty` increments to 3 (finance is the writer; no cross-schema query).

### AC-07-23 — SO Fulfilled derived (in-module aggregate) [BE][T]
- **Given** an SO whose every line has `invoiced_qty ≥ qty`, **when** the CRM derived trigger re-evaluates (via the in-module `aggregate_fact` over `sales_order_lines`), **then** the SO derives to **Fulfilled**.
- **Given** any line still under-invoiced, **then** the SO stays Confirmed (not Fulfilled).

---

## Slice 3 — Core + finance: gateways + checkout + webhooks

### AC-07-24 — payment connections, one-per-type relaxed [BE][T]
- **Given** `type=payment`, **when** a tenant adds a second payment connection of a **different provider**, **then** it is allowed (one-per-type lifted for payment); a duplicate **same-provider** connection is still rejected.

### AC-07-25 — per-project connection resolution [BE][T]
- **Given** a project with `payment_connection_id` set, **when** checkout resolves the gateway, **then** it uses the project's connection; **given** none, **then** it falls back to the tenant default (`resolve_for_type`).

### AC-07-26 — PaymentProvider adapters (Stripe + Billplz) [BE][T]
- **Given** the Stripe and Billplz adapters, **when** registered at boot, **then** both implement `create_checkout` / `verify_webhook` / `refund` and a Test (balance/ping) via the existing seam.

### AC-07-27 — checkout creates Pending row + redirect [BE][FE][E2E]
- **Given** an Issued invoice, **when** the buyer clicks Pay, **then** finance creates a **Pending** payment row (knows invoice_id), passes its id as `external_ref` into `create_checkout`, and the user is **redirected** to the gateway hosted page.

### AC-07-28 — webhook route, tenant from connection_id, masked log [BE][T]
- **Given** an inbound `POST /integrations/webhooks/{provider}/{connection_id}`, **when** received, **then** the tenant is resolved from `connection_id`; the call is logged to `integration_logs` with **masked** request/response (no raw secrets/PAN).

### AC-07-29 — webhook signature + timestamp tolerance [BE][T]
- **Given** a webhook with an **invalid** signature (Stripe signing-secret / Billplz X-Signature HMAC), **then** it is **rejected** (no state change).
- **Given** a validly-signed but **stale** event (timestamp older than the tolerance window), **then** it is rejected (anti-replay).

### AC-07-30 — idempotent ingest + idempotent flip [BE][T]
- **Given** two deliveries of the **same** `external_event_id`, **when** processed, **then** the second is a **no-op** (`UNIQUE(tenant,provider,external_event_id)`).
- **Given** a payment already **Succeeded**, **when** another success event (different event_id, same payment) arrives, **then** the Pending→Succeeded flip is a **no-op** — **never re-credited** (guard on payment state).

### AC-07-31 — webhook flips Pending→Succeeded → derived Paid [BE][E2E]
- **Given** a Pending payment, **when** the success webhook is verified, **then** finance finds the row by `external_ref`, flips it to **Succeeded** under `FOR UPDATE`, and the invoice derives toward Paid.

### AC-07-32 — gateway_fee captured [BE][T]
- **Given** a success webhook/balance-txn reporting a processing fee, **when** the payment is confirmed, **then** `gateway_fee` (sen) is stored on the payment row.

### AC-07-33 — abandoned Pending reaped [BE][T]
- **Given** a Pending payment older than the checkout TTL with no webhook, **when** the reaper sweep runs, **then** it is set to **Expired** (frees the buyer to re-pay; never blocks a new checkout).

### AC-07-34 — out-of-order webhook tolerated [BE][T]
- **Given** a refund event that references a payment not yet processed, **when** ingested, **then** it is **retried** (Celery) rather than hard-failing.

### AC-07-35 — post-payment workflow fires [BE][E2E]
- **Given** an invoice deriving to **Paid**, **when** the `status_changed→Paid` workflow runs, **then** the participant becomes **Eligible**, admission tickets become **Valid**, and a **receipt email with the PDF** is enqueued — all failure-isolated (a workflow error never 500s the webhook).

### AC-07-36 — dispute webhook → Disputed [BE][T]
- **Given** a `charge.dispute.created` (Stripe / Billplz equivalent) webhook, **when** ingested, **then** the payment flips to **Disputed** and the event is logged — never silently dropped. (Full dispute response = backlog.)

---

## Slice 4 — Finance: refunds + settlement

### AC-07-37 — per-ticket refund, gateway path [BE][FE][E2E]
- **Given** a Paid invoice with admission tickets paid via a gateway, **when** an operator refunds selected tickets, **then** a gateway `refund` is called → webhook → a `refund` record + `refund_lines` (per ticket) is created.

### AC-07-38 — refund method mirrors payment method [BE][T]
- **Given** a payment made by **CASH/BANK**, **when** refunded, **then** the refund is a **manual** record (no gateway API call); **given** a GATEWAY/FPX payment, **then** the refund routes through the gateway API.

### AC-07-39 — over-refund guarded [BE][T]
- **Given** Σ payments = 10000 sen, **when** refunds totalling > 10000 are attempted (incl. concurrently), **then** under `FOR UPDATE` the excess is **rejected** — Σ refunds never exceeds Σ payments.

### AC-07-40 — numbered credit note + PDF [BE][T]
- **Given** a confirmed refund, **then** a **credit_note number** is assigned (numbering engine) and a credit-note PDF renders (reuses the invoice template/context).

### AC-07-41 — tickets Void + QR dead [BE][E2E]
- **Given** refunded tickets, **then** they move to **Void/Refunded** and their **QR is rotated dead** (a prior QR scan no longer validates).

### AC-07-42 — capacity released on refund [BE][T]
- **Given** a refunded RESERVED-seat ticket, **then** the seat is **freed**; **given** a GA ticket, **then** the sold count **decrements** — capacity is re-sellable.

### AC-07-43 — invoice re-derives Partially/Refunded [BE][T]
- **Given** Σ refunds < Σ payments, **then** the invoice derives to **Partially Refunded**; **given** Σ refunds = Σ payments, **then** **Refunded**.

### AC-07-44 — participant eligibility re-derived [BE][T]
- **Given** a participant whose only valid paid admission ticket is refunded, **when** eligibility re-derives, **then** the participant **drops** from Eligible.

### AC-07-45 — project commercial mode + fee config [BE][FE][T]
- **Given** a project, **when** set to `commercial_mode=AGENCY` with `fee_type ∈ {PERCENT,FLAT,PER_TICKET}` + `fee_value`, **then** the config persists and drives settlement; `SELF_RUN` projects produce no give-back settlement.

### AC-07-46 — PRIMARY settlement nets three ways [BE][FE][E2E]
- **Given** an AGENCY project with paid attendee invoices, **when** an operator clicks "Generate settlement", **then** a **PRIMARY** settlement (Draft) rolls up `gross_collected`, `gateway_fees`, `fee_amount` and computes **net_payable = gross − gateway_fees − fee_amount** (all sen, all three lines shown).

### AC-07-47 — settlement lifecycle [BE][E2E]
- **Given** a Draft settlement, **when** Approved then Marked remitted with a `remittance_ref`, **then** it moves Draft→Approved→**Remitted** (status engine).

### AC-07-48 — post-remit refund → ADJUSTMENT settlement [BE][T]
- **Given** a ticket whose invoice is in a **Remitted** settlement, **when** it is refunded, **then** a **supplementary ADJUSTMENT** settlement is spawned (kind=ADJUSTMENT, may be **negative**) — the clawback is auditable; the original Remitted PRIMARY is untouched.

---

## Cross-cutting / non-functional (verified across slices)

### AC-07-49 — tenant isolation everywhere [BE][T]
- **Given** any finance/crm/settlement query or capability handler, **then** it is **tenant-scoped**; no cross-tenant read/write is reachable (incl. webhook-resolved tenant, soft-ref resolution, capability calls).

### AC-07-50 — failure isolation [BE][T]
- **Given** a broken/slow post-payment workflow or derivation, **when** it errors, **then** the triggering request/webhook **never 500s or blocks** — the error is logged + isolated (each event commits independently).

### AC-07-51 — money exact end-to-end [BE][T]
- **Given** any multi-line invoice with mixed tax rates + multiple partial payments + a partial refund, **when** all sums are computed, **then** subtotal/tax/total/Σpayments/Σrefunds/settlement-net **reconcile exactly** (integer sen, zero float drift).

### AC-07-52 — responsive surfaces [FE][E2E]
- **Given** every new F surface (numbering settings, invoice detail + PDF, SO, payment/refund forms, settlement), **when** viewed at **375px AND 1280px**, **then** no horizontal scroll / clipped controls; side-by-side panels stack on mobile.

### AC-07-53 — Definition-of-Done gate [BE][FE]
- No phase-1 mock survives a "done" slice (all swapped to real + verified on real data). New columns/states on existing entities are **backfilled** (not seed-if-absent only). No code hardcode-looks-up a tenant-editable status/numbering key. New permissions are granted to existing tenants' Admin (grant sweep).
