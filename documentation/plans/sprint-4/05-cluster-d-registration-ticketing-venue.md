# Sprint 4 · Plan 05 — Cluster D: Registration · Ticketing · Capacity · Venue & Seating (EMS module)

**Status:** GRILLED (2026-06-18) + **round-3 re-grill (2026-06-20, post-CRM-split)** — design locked, ready to slice + build. See "Locked decisions — round 3" below; the original "Open build-grill targets" are now all resolved.
**Branch (future):** `sprint-4/05-cluster-d`
**Depends on:** **core catalog** (`08` — `public.products`/`product_categories`, moved out of `app_ems`) · **`02` Cluster B** (CRM clients/leads/quotations in `app_crm`) · **`03` Derived Status** (participant `Checked-in`, SHIPPED) · F1 form engine (registration form) · **`04` form-revision** (SHIPPED, orthogonal) · EMS spine (Profile/Project/Participant + template roles/segments) · Import engine (bulk reg) · status engine · **omnichannel WS + Redis pub/sub** (live seat map) · `app/secrets.py` FERNET (signed QR) · **core auth stack** (plan-10 single-use tokens/throttle/password policy — reused for Profile portal auth).
**Module footprint (post-split, round 3):** Cluster D spans **THREE** modules — `app_ems` (offerings/venues/capacity/carts/tickets/participants/portal-auth), the **NEW `app_finance` module** (invoices/invoice_lines, born here), and **core** (catalog). `app_crm` is referenced (bill-to Client) via soft-ref only.
**Source:** `01-...-grill-decisions.md` §2 + §6.2–6.6, §6.8 + this grill. BRD: `Registration_Auth_Functional_Spec.md`, `Ecommerce_Payment_Functional_Spec.md`, `Event_Day_Functional_Spec.md`, `Agenda_Scheduling_Functional_Spec.md`.

---

## Scope — the attendee revenue stream (Profile → Participant → Ticket → Invoice)

First **money-in** vertical: a published event sells tickets (GA or reserved seating), holds capacity cinema-style during checkout, collects per-attendee dynamic data, issues signed-QR tickets, and gates event-day access. **Payment itself + the invoice Paid-derivation = Cluster F**; Cluster D creates **Draft invoices** as order headers.

## Locked decisions (this grill)

1. **Cart = dedicated entity (Q1).** `carts` + `cart_items` are the browse + hold container; **confirm spawns Invoice + tickets**; TTL expiry releases holds. (Not "draft invoice as cart".)
2. **Anonymous-capable cart; profiles at confirm (Q2).** `carts.profile_id` NULLABLE + `session_token`; at confirm, **find-or-create Profile per attendee by email** (reuse the bulk-importer resolver — never overwrite a shared profile) → mint participant + ticket; new profiles get a **claim/activation mail** (workflow). Purchaser (`bill_to`) may differ (Client/Profile).
3. **Offering grants segment/role (Q3).** `project_product.grants_segment_id` / `grants_role_id` (→ template rows) copied onto `participant.segment_id`/`role_id` at mint. Pricing tier (offering) and access segment stay separate-but-linked; checkpoints gate by segment.
4. **QR = signed/opaque token (Q4).** `ticket.qr_token` = signed (Fernet/HMAC via `app/secrets.py`) encoding `ticket_id`; scanner sends it → server validates signature → resolves ticket→participant→project → checkpoint rules. **Rotated on transfer/nomination + void/refund** (old QR dies). Not forgeable/enumerable. Double-entry blocked by `checkpoint_logs` SINGLE dedup.
5. **Capacity hold = cinema-style (Q5, researched).** **DB row locks** (Postgres): RESERVED = `SELECT … FOR UPDATE`/`SKIP LOCKED` on chosen `capacity_units` (free→held atomic); GA = lock the offering counter, `sold+held+qty ≤ capacity`. **Final UNIQUE/state-check backstop** at confirm. **Hold TTL 5–10 min + ~5s server buffer** (client times out first); scheduler sweep releases. **Live held/sold seat map** via the omnichannel **WS + Redis pub/sub** (rooms per project/offering) + a visible countdown. *Redis SETNX+Lua atomic lock = flagged upgrade for hot on-sales (backlog).*
6. **Pricing v1 = currency + per-line tax + early-bird via offering windows (Q6).** Promo/discount codes + group discounts = backlog (Discount entity, with F).
7. **Public surface = D ships it (Q7).** D builds backend + admin + a **functional standalone public registration page** (existing `app/(public)/public/...` route, reuse form renderer + a new seat-map/cart/checkout UI). F5 website builder LATER wraps it (branded CMS block). Revenue flow not blocked on F5.

## Locked decisions — round 3 (2026-06-20, post-CRM-split re-grill)

The CRM-split + catalog-to-core merge (plan `08`) landed AFTER the 06-18 grill and moved boundaries this plan assumed. Re-grilled; these supersede where they conflict.

R3-1. **Finance is its OWN module `app_finance` (was: invoices in `app_ems`).** `invoices` + `invoice_lines` are **born in D inside `app_finance`**; the invoice status entity (`Draft→Issued→Cancelled`) is registered + seeded **by finance** in D. Cluster F extends the SAME module additively (payments, gateway provider, sales_orders, settlement, the derived `Paid`/`Partially Paid`/`Overdue`/`Refunded`). Rationale: invoice/payment/SO/settlement is one cohesive finance domain F owns anyway — birthing invoices in EMS then growing payments in F = the exact re-home churn plan 08 just punished. *Same call class as catalog→core, but a module (heavy domain, not a horizontal primitive, not every tenant needs it).*
   - **Dependency edges:** `ems requires finance` (the registration vertical hard-needs invoices; comp tickets keep `invoice_id` NULL so spine-only EMS still installs). `finance optional crm + ems` (resolve bill-to names for display). Requires-graph acyclic → install order `finance → ems`.
   - **Capabilities finance provides:** `finance.create_invoice@1(db, tenant_id, {project_id, bill_to_type, bill_to_id, lines[], currency}) → invoice_id` (registration confirm + F's quotation/SO→invoice both call it) and `invoice.resolve@1(db, tenant_id, {id})` (cross-module header read, BL-030 soft-ref pattern).
   - **Finance → outward** for bill-to display: calls `client.resolve@1` (crm) / `profile.resolve@1` (ems); orphan → None.
   - **`ticket.invoice_id`** (in `app_ems`) = plain **soft-ref column**, resolved via `invoice.resolve@1`. NO cross-module FK.
   - **Atomicity:** the registration confirm runs ems (cart→participant→ticket) + `finance.create_invoice@1` in **one request session** (capability handlers take the caller's `db`) — multi-schema, single Postgres txn, atomic. Comp = skip the capability call (`invoice_id` NULL).

R3-2. **Participant `Checked-in` = pure build on the SHIPPED derived-status API (plan 03).** Verified against `app/status_engine/derived.py` + `app/services/status_machine.reevaluate` (handles scoped owners via `_tier_and_scope`/`_scope_guard`) + `app/status_engine/scoped.py` (`ScopeSeedEdge` already carries `conditions` + `trigger_mode`). Mechanism: (a) add a `Checked-in` status + a conditioned **auto-edge** into it to `PARTICIPANT_SCOPE_SEED_STATUSES`/`_EDGES` (new templates materialize it, new projects copy it via `copy_scope`); (b) register a cross-entity `DerivedTrigger(owner_entity="project_participant", trigger_entity="ticket", resolve_owners=…)`; (c) register aggregate facts `checkedInTicketCount` / `admissionTicketCount`. Checked-in rides the participant's existing **scoped** eligibility graph (one axis, not a second status field). **Caveat:** participant graphs materialized BEFORE D won't have the node — dev destructive-reseed (plan-08 pattern) covers it; a prod backfill migration is required.

R3-3. **Form-revision (plan 04) is orthogonal.** Registration submissions are single-shot (`allow_revisions=false`); the binding just creates a normal `form_submission` (`subject_type=project_participant`). No revision interaction.

R3-4. **Seat-map admin editor = functional generator + grid (A1 resolved).** D ships: zone → "generate N rows × M seats" bulk-mint (auto labels), an editable **list/grid** of resulting `capacity_units` (relabel / toggle / set zone), x/y stored as **auto-grid coordinates**. NO drag canvas. The slice-2 live cinema-style seat map RENDERS these coords read-only. The visual x/y designer + external stadium import stay deferred to the Venue/Seating plan — the data seam (x/y/zone/`venue_seat_id`) is reserved so it's no rework.

R3-5. **Bulk-import ticket mode (A3 resolved).** The EMS participant importer gains job-level controls on the import page (where abort/trigger toggles live): **Ticket mode** = `Participants-only` (no ticket) | `Comp` (ticket, `invoice_id` NULL, QR + invitation mail) | `Paid` (ticket + Draft invoice). **Offering** SearchSelect required when mode ≠ Participants-only — **GA offerings only in v1** (RESERVED needs interactive seat-pick → RESERVED bulk = admin add-one). **Paid** also picks a **bill-to Client** → **one consolidated Draft invoice** to that Client for all N tickets (via `finance.create_invoice@1`); Comp = no invoice. **Capacity validated at the Test phase** (`sold + held + import_qty ≤ capacity`) → over-capacity rejects at Test, never oversells at commit.

R3-6. **Identity merge = email-at-confirm; registration is GUEST checkout + a confirmation email (cinema model — REVISED 2026-06-20).** There is **no post-auth cart-merge step** — the merge key is the **attendee email at confirm** (find-or-create Profile reusing the bulk-importer resolver). An abandoned anonymous cart just expires; a repeat buyer with the same email find-or-creates the SAME Profile (purchases accumulate). **Confirm → Draft invoice → a confirmation email** (tickets/QR + the invoice/pay link); **payment itself = Cluster F**. NO forced "claim your account" step at registration — attendees register as guests, exactly like a cinema booking.
   - **Portal auth is DEMOTED to optional / deferred** (was: "D ships Profile portal auth, mandatory claim"). The confirmation email MAY carry an optional "create a password to manage your tickets" link, but it's never required to register or attend. The Profile reserved auth columns stay reserved; a thin attendee `/portal` is a later nice-to-have, not slice-2 scope.
   - **Cluster E reviewers still need login** — but that's a SEPARATE population handled when E is built (reviewer Profiles get an invite/set-password), decoupled from attendee registration. E's prerequisite becomes "reviewer auth" (E-local), not "every attendee has a portal account".

R3-7. **`max_tickets_per_attendee` (was `submission_limit_per_user`) — enforce-by-email, not greyed (A5 resolved).** The offering column is **renamed `max_tickets_per_attendee`** (drops the form-engine "submission" + core-"user" vocab — this is a per-attendee ticket cap). Registration ALWAYS captures attendee email, so the cap **is enforceable even anonymous** (the form-engine "grey when unenforceable" precedent applies to identity-less forms, not here). Enforced at confirm: find-or-create Profile → count its existing non-void tickets for the offering + cart qty ≤ cap → **409** if exceeded. **Documented bypass:** different emails evade it (true of any email-based cap) — accepted.

R3-9. **Checkout wizard = UI, not status; payment is IN the flow; `payment_policy` is the only tenant knob (added 2026-06-20).** The registration wizard steps (tickets→details→review→**payment**→done) are **ephemeral front-end navigation** — NOT persisted, NOT entity state, NEVER on the status engine. Durable lifecycle lives only on **ticket / invoice / participant** (all engine-backed + tenant-configurable). The **cart**'s `open|converted|abandoned|expired` is a **plain internal enum** (ephemeral/TTL-swept), NOT the status engine.
   - **Payment happens ON the registration page** (inline card step), not via an emailed invoice link. **Pay now → confirmation email** (tickets/QR); **pay later → "payment pending" email + a Complete-payment link** that resumes the payment step. The mail is a CONFIRMATION (after pay) or a PENDING notice (if skipped) — never a "claim account" mail (supersedes the R3-6 wording).
   - **`payment_policy` = a PROJECT (or offering) setting** `{pay_now_required | pay_later_allowed}` — the ONE real tenant variation. It gates whether the "pay later" option shows + which email fires; the *consequence* (invoice Paid vs Issued-unpaid + reminder) rides the **invoice status engine** (configurable). Wired in slice-2 backend.
   - **Arbitrary per-tenant step add/remove (e.g. "skip review") = BACKLOG**, not v1 (the registration FORM is already configurable via F1; the review/payment screens stay fixed). If ever needed, a flow-config like the form engine — not status.
   - Payment PROCESSING (gateway/connections, Fernet creds) = **Cluster F**; slice-2 frontend mocks the card step.

R3-8. **Module homes (no-grill build placement).** `offerings (project_products)` / `venues` / `venue_zones` / `venue_seats` / `project_venues` / `capacity_units` / `capacity_holds` / `carts` / `cart_items` / `tickets` / Profile-portal-auth = **`app_ems`**. `invoices` / `invoice_lines` = **`app_finance`**. `products` / `product_categories` = **core** (offering `product_id` = sanctioned module→core FK). Bill-to Client = `app_crm` soft-ref. **Grep core for permission-key collisions** before adding `finance.*` / `tickets.*` / `offerings.*` / `venues.*` / `carts.*` / `portal.*` (the `templates.*` / `wa_templates.*` lesson). Terminology registrations for ticket / offering / venue / invoice (relabelable).

## Data model (`app_ems` — EXCEPT invoices/invoice_lines, which live in the NEW `app_finance` module per R3-1)

```
project_products (Offering)
  id, tenant_id, project_id, product_id (→ product_master), price (override, nullable→default),
  currency, tax_rate, capacity (int), allocation_mode {GA, RESERVED}, valid_from, valid_until,
  grants_segment_id (nullable), grants_role_id (nullable), max_tickets_per_attendee (nullable)  # R3-7 (was submission_limit_per_user)

venues (tenant-level master)      id, tenant_id, name, address, capacity
venue_zones                       id, tenant_id, venue_id, name, kind {section|hall|room}, sort
venue_seats (reusable map)        id, tenant_id, venue_id, zone_id, section, row, number, x, y, label
project_venues                    id, tenant_id, project_id, venue_id

capacity_units (RESERVED only)    id, tenant_id, project_product_id, venue_seat_id (nullable),
                                  label/section/row/number/zone, x, y,
                                  status {free|held|sold}, held_until (nullable), held_by_cart_id (nullable)
capacity_holds (GA)               id, tenant_id, project_product_id, cart_id, qty, expires_at

carts                             id, tenant_id, project_id, profile_id (nullable), session_token,
                                  status {open|converted|abandoned|expired}, expires_at,
                                  bill_to_type/bill_to_id (nullable until checkout)
cart_items                        id, cart_id, project_product_id, qty, capacity_unit_id (nullable RESERVED),
                                  unit_price_snapshot, attendee_email, attendee_name, registration_answers (draft, nullable)

tickets (status-engine entity)    id, tenant_id, project_id, project_product_id, capacity_unit_id (nullable GA),
                                  attendee_profile_id (nullable), participant_id (nullable), invoice_id (nullable=comp),
                                  serial_bib (nullable), qr_token, status_id
                                  (Issued→Valid→CheckedIn→Transferred→Void/Refunded)

# --- app_finance module (NEW, born in D per R3-1) ---
invoices (app_finance)            id, tenant_id, project_id, bill_to_type {Client|Profile}, bill_to_id,
                                  sales_order_id (nullable, F), currency, status_id, subtotal, tax, total
invoice_lines                     id, invoice_id, project_product_id (nullable)|description, qty, unit_price, tax, amount

# project.registration_form_id (nullable → F1 form)
# ticket.invoice_id = SOFT-REF to app_finance.invoices (plain col, no cross-module FK — R3-1)
```

> **Invoice split D↔F (R3-1):** the NEW **`app_finance`** module introduces `invoices`/`invoice_lines` + registers/seeds the invoice status engine **Draft→Issued→Cancelled** in D. EMS-registration mints invoices via the `finance.create_invoice@1` capability (one atomic ems+finance session). **Cluster F extends the same module** with `payments` + gateway provider + `sales_orders` + the **derived `Paid`/`Partially Paid`** (plan `03`) + `Overdue`/`Refunded`/settlement. Comp/free = ticket with `invoice_id` NULL (no capability call), eligibility flips directly.

## Status engine + derived consumers
- **`ticket`** status entity (Issued→Valid→CheckedIn→Transferred→Void/Refunded) — registered + seeded.
- **`invoice`** status entity (Draft→Issued→Cancelled here; F extends).
- **First plan-03 derived-status consumer:** **participant `Checked-in`** ← `checkedInTicketCount == admissionTicketCount (>0)`. D registers the `DerivedTrigger` (ticket→participant) + the aggregate facts + seeds the system auto-edge. (Validates plan 03 in a real domain.)

## Flows
- **Self-serve (public):** browse offerings (filtered by window + remaining) → RESERVED: pick seats on the live seat map → checkout-start (cart + holds, DB-locked, WS broadcast, countdown) → per-attendee registration form → confirm: find-or-create Profile → participant (copy grants) → ticket (signed QR, seat→sold) → Draft invoice + lines; new profiles → claim mail; per-attendee `form_submission`. Payment = F.
- **Admin add-one:** register an attendee directly → ticket + Draft invoice (or comp).
- **Bulk (Excel):** extend the EMS participant importer with a chosen offering → create tickets + Draft invoice + **invitation mail** (two modes: participants-only/comp vs with-ticket). Reuses F8 + the spine's find-or-create resolver.
- **Nomination/transfer:** invoice owner reassigns `attendee_profile_id` → ticket Transferred + **QR rotated**; nominee can't re-transfer; money untouched.
- **Event-day (preview only; full = H):** `checkpoints` + `checkpoint_logs` (ref ticket_id+participant); scan QR → segment + eligibility + entry-type checks.

## Slices (frontend-first → backend → TDD → E2E)
1. **Offerings + Venue master + seat map + capacity minting** — product→offering config (price/tax/capacity/allocation_mode/window/grants); venue + zones + seats master (reusable) + `project_venues`; zone→offering `capacity_units` minting; admin **seat-map** UI (functional grid/x-y; the fancy visual designer + stadium import = the Venue plan).
2. **Cart + holds + checkout + tickets + Draft invoice** — `carts`/`cart_items`; DB-locked holds (RESERVED seat-lock + GA counter) + TTL sweep + final backstop; **cinema-style interactive seat map** (WS live held/sold + countdown); per-attendee registration form binding; confirm → find-or-create Profile + participant (grants) + signed-QR ticket + Draft invoice; comp path; admin add-one; bulk-import extension; **standalone public registration page**.
3. **Nomination/transfer + QR + check-in preview + derived check-in** — ticket status engine; nomination (QR rotate); checkpoint scan stub + `checkpoint_logs`; **participant `Checked-in` as the first plan-03 derived-status consumer**. (Full event-day = H.)

## Deferred to other clusters
Payment + gateway + integration-log + invoice `Paid`-derivation + Settlement/give-back (+ Sales Order) → **F**. Full event-day checkpoints/badge/silent-print → **H**. Agenda on venue zones → **G**. F5 branded registration wrapper → **F5**. Visual seat-map designer + external stadium import → **Venue/Seating plan**. Promo/discounts → backlog.

## Open build-grill targets — RESOLVED (round 3, 2026-06-20)
All five closed in "Locked decisions — round 3":
- Seat-map admin editor scope → **R3-4** (functional generator + grid; visual designer deferred).
- Invoice status-engine seeding split at D/F → **R3-1** (finance module owns it; D = Draft→Issued→Cancelled).
- Bulk-import ticket-mode UX → **R3-5** (3 modes, GA-only v1, Paid → consolidated Client invoice).
- Anonymous cart → authenticated handoff → **R3-6** (collapses to email-at-confirm; D ships Profile portal auth).
- `submission_limit_per_user` enforcement → **R3-7** (renamed `max_tickets_per_attendee`; enforce-by-email, not greyed).

## Sources (capacity-hold research)
- [DB Locking in Reservation Systems — Medium](https://akshitbansall.medium.com/db-locking-in-reservation-systems-3b3d574c7676)
- [Designing a Concurrency-Safe Ticket Booking System — Medium](https://medium.com/@suchirreddy31/%EF%B8%8F-designing-a-concurrency-safe-ticket-booking-system-from-scratch-6922db1b6401)
- [Ticket Booking System (BookMyShow) HLD — DEV](https://dev.to/arghya_majumder/ticket-booking-system-bookmyshow-high-level-system-design-3one)
