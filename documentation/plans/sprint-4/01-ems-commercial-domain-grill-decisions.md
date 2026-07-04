# EMS Commercial & Registration Domain — Grill Decisions

**Grilled:** 2026-06-18. **Feeds:** the next numbered plan (Cluster B vertical) + forward-contract for Clusters D/E/F/G/H.
**Builds on:** the live `ems` module (sprint-3/11, `app_ems` schema — Profile / ProjectType / ProjectTemplate / Project / ProjectParticipant). Reconciles the legacy `EMS_Project_Plan.md` schema (predates the module rebuild) onto the real platform.

> **Re-pointing rule (everywhere below):** every legacy `*_user_id` that meant an *attendee* now points at **`Profile`**, not core `users`. Cross-schema refs to core (`tenants`, `statuses`, `users`) stay **plain indexed columns, not DB FKs** (BL-030). Intra-`app_ems` FKs kept.

---

## 1. The two-party / two-revenue-stream model (the spine)

Two distinct subject hierarchies + two revenue streams:

```
COMMERCIAL (buyer side)          ATTENDANCE (participant side)
  Lead ──► Client                  Profile (individual identity)
            │                          │
            ▼                          ▼
         Project ◄──────────────── ProjectParticipant (scoped status, tier-2)
            │                          ▲
            ▼                          │ (admission ticket mints)
        Quotation                    Ticket ─┬─► project_product (Offering)
            │                          │     └─► capacity_unit (RESERVED only) ─► venue_seat
            ▼                          ▼
   ┌──────────────── Invoice ◄─────────┘
   │   (unified, polymorphic bill-to: Client | Profile)
   ▼
 Payment ──► (Cluster F) Settlement / give-back to Client
```

- **Stream 1 — B2B service:** Client commissions an event → Quotation (revisions) → Invoice **to the Client**.
- **Stream 2 — attendee registration:** Profile/Client buys Tickets+Add-ons (Offerings of the Product master) → Invoice **directly** (no quotation, BRD's "no Sales Order" path).
- **Give-back (agency mode):** attendee revenue can be **remitted back to the Client** minus fees — hooks reserved now, Settlement entity built in Cluster F.

**NO Sales Order** (BRD explicit). **Capacity is first-class + hybrid** (see §2) — promoted from a plain limit to an addressable unit so venue layouts (stadium/conference) can be visualized and externally imported later.

---

## 2. Locked entities (forward contract — full skeleton across B–H)

### Commercial side (Cluster B — **build now**)

**`clients`** — B2B buyer account (NEW, separate from Profile)
- `id, tenant_id, name, registration_no, contact_person, contact_email, contact_phone, status_id` (status-engine: Active→Inactive→Archived) + soft-delete + timestamps.

**`leads`** — inquiry/opportunity (NEW)
- `id, tenant_id, client_id (NULLABLE — raw inquiry pre-client), source, contact_name, contact_email, contact_phone, notes, status_id` (status-engine: New→Contacted→Qualified→Won→Lost)
- **Won** fires a workflow → spawns a `Project` (links `project.lead_id`), links-or-creates the `Client`.

**`product_categories`** — self-referencing tree (ERP taxonomy, NEW)
- `id, tenant_id, parent_id (NULLABLE, self-FK), name, sort` — grouping/reporting **only**; never branch behavior on it.

**`product_master`** — tenant catalog (NEW; replaces per-project products)
- `id, tenant_id, category_id, name, sku, kind (ENUM: ADMISSION|ADD_ON|SERVICE|MERCHANDISE), default_price, tax, uom, is_active`
- **`kind` = behavioral fixed enum** — only `ADMISSION` mints a participant + QR ticket. Code branches on `kind`, never on `category`.

**`quotations`** — B2B service quote (NEW)
- `id, tenant_id, client_id, lead_id (NULLABLE), project_id (NULLABLE — raised at lead stage, links on win), revision_number, parent_quotation_id (lineage), currency, status_id` (status-engine: Draft→Sent→Accepted→Rejected→Expired), totals.
- **At least one of `lead_id`/`project_id` set.** Revisions clone a row, `parent_quotation_id` tracks lineage. **F3 document attach** via Drive `file_links`.

**`quotation_lines`** (NEW)
- `id, quotation_id, product_id (NULLABLE → product_master, typically SERVICE), description (free-form override), qty, unit_price, amount`. Header total derived.

### Attendance / registration side (Cluster D — forward contract)

**`project_products`** — per-project **Offering** (NEW join; project picks eligible master products)
- `id, tenant_id, project_id, product_id (→ product_master), price (override, NULLABLE→default), capacity (int, the limit), allocation_mode (ENUM: GA|RESERVED), valid_from, valid_until`
- `remaining = capacity − allocated`. Run categories / VIP-vs-GA = separate Offerings, each own capacity.

**`capacity_units`** — addressable unit / "seat" (NEW; the future-proof entity)
- `id, tenant_id, project_product_id, venue_seat_id (NULLABLE → reusable venue map), label, section, row, number, zone, x, y, status (free|held|sold)`
- **Minted ONLY for `allocation_mode = RESERVED`** (GA stays limit-only, no rows — avoids 50k dead rows). **1 unit = 1 ticket, strict.** Carries layout position for visualization; `venue_seat_id` links the physical reusable seat.

**`tickets`** — one owned unit of capacity (NEW; legacy `Event_Tickets` re-pointed)
- `id, tenant_id, project_id, project_product_id, capacity_unit_id (NULLABLE — set for RESERVED, null for GA), attendee_profile_id (NULLABLE until nominated), participant_id (NULLABLE → ProjectParticipant), invoice_id, serial/bib (NULLABLE), status_id, qr_token`
- **Buyer NOT on ticket** — buyer = `invoice.bill_to`, who controls/reassigns.
- **ADMISSION** ticket: assigning `attendee_profile_id` mints/links the `ProjectParticipant` (unique per profile×project). **ADD_ON/MERCH** tickets attach to the same participant → 1 participant : N tickets.
- **Nomination/transfer:** invoice owner reassigns `attendee_profile_id`; **nominee cannot re-transfer**.

### Venue & layout (forward contract — reusable map; visual designer/import deferred)

**`venues`** (NEW): `id, tenant_id, project_id (or tenant-level reusable), name, capacity`.
**`venue_seats`** — reusable physical seat map (NEW): `id, tenant_id, venue_id, section, row, number, zone, x, y` — imported once (e.g. from a stadium), reused every event at that venue. `capacity_units.venue_seat_id` points here.
> **Deferred:** the visual layout designer + external stadium import tool → a later **Venue/Seating plan**. The data seam (venue_seats + capacity_unit.venue_seat_id + x/y/zone) is reserved now so it's no rework.

### Finance (Cluster F — forward contract)

**`invoices`** — unified across both streams (NEW)
- `id, tenant_id, project_id, bill_to_type (Client|Profile), bill_to_id, quotation_id (NULLABLE — B2B path), currency, status_id` (status-engine: Draft→Issued→Partially Paid→Paid→Overdue→Void/Refunded), totals.
- B2B: `quotation_id` set, bill_to=Client, lines from quote. Registration: `quotation_id` null, bill_to=Profile/Client, lines = purchased Offerings; `tickets.invoice_id` ties them.

**`invoice_lines`** (NEW): `id, invoice_id, project_product_id (NULLABLE) | description, qty, unit_price, amount`. Per-product revenue per project → give-back computable.

**`payments`** (NEW; legacy re-pointed)
- `id, tenant_id, invoice_id, amount, method (CASH|CARD|GATEWAY), gateway_connection_id (→ core connections framework), gateway_ref, status_id, paid_at`
- **Many per invoice** (partials → Partially Paid→Paid). On-spot = a CASH/CARD row at checkpoint.
- **Gateway = NEW payment provider on the core integration/connections framework** (Fernet creds), per-tenant + optional per-project selection; webhook calls logged via an integration-log table.

**Give-back reservation (Cluster F):** on `projects` → `commercial_mode (ENUM: SELF_RUN|AGENCY)` + client fee/commission terms (rate/flat). Full **Settlement/Payout** entity = deferred to the Cluster F finance plan.

### Submissions & Review (Cluster E — forward contract)

- **Abstract Submission = a `form_submission`** (F1; subject = participant/project). **No new submission table.**
- **`review_configurations`** (NEW): `project_id/form_id, required_review_count, window_start, window_end`.
- **`review_assignments`** (NEW): `submission_id (→ form_submission), reviewer_profile_id (→ Profile, external expert), review_form_id, status, review_submission_id (→ review's own form_submission)`.
- Allocation via **rule-engine**; score average = computed.
- **Dependency:** reviewer = Profile ⇒ **Profile portal auth (Cluster D)** is a hard prerequisite for reviewers to log in. Model locks now; workflow usable once Profile's reserved auth columns activate.

### Agenda / Event-day (Clusters G + H — forward contract)

- **`agenda_sessions`** (NEW): `project_id, venue_id, parent_session_id (nested), title, start_time, end_time, submission_id (→ form_submission), presenter_profile_id`.
- **`session_dependencies`** (NEW): `predecessor_session_id, successor_session_id, type (FINISH_TO_START)` — delay cascade recurses; reuse scheduler + omnichannel WS.
- **`checkpoints`** (NEW): `project_id, name, allowed_segment_ids, entry_type (SINGLE|MULTIPLE)`.
- **`checkpoint_logs`** (NEW): `checkpoint_id, participant_id, result (SUCCESS|DENIED), reason, scanned_at`. Eligibility = segment + payment status + tier-2 participant status.

---

## 3. Status-engine entities introduced

Unscoped, tenant-level (registered via `register_engine_entities`, mirror existing profile/project adoption):

| Entity | Graph | Notes |
|--------|-------|-------|
| `client` | Active → Inactive → Archived | soft-archive via engine |
| `lead` | New → Contacted → Qualified → Won → Lost | Won fires project-create workflow |
| `quotation` | Draft → Sent → Accepted → Rejected → Expired | revisions via `parent_quotation_id` |
| `invoice` | Draft → Issued → Partially Paid → Paid → Overdue → Void/Refunded | Cluster F |

(Existing: `profile`, `project` unscoped; `project_participant` scoped. `product_master` = simple `is_active`, NOT engine. `ticket`/`capacity_unit` status likely simple enums — confirm in Cluster D plan.)

---

## 4. First build slice — Cluster B vertical (next plan implements)

End-to-end on the **Resource shell**, frontend-first → backend → TDD → E2E → review:

1. **Clients** — Resource list + ResourceForm; status-engine (Active/Inactive/Archived); importable (id-first export).
2. **Leads** — Resource list + form; **inline quick-create** of a Client from the lead form; status-engine; **Won → convert** action spawns a Project (workflow) + links client/lead.
3. **Product categories (tree) + Product master** — category tree editor, product master list/form with `kind` enum + category SearchSelect, `is_active`. Importable.
4. **Quotations** — list + form; `quotation_lines` editor (pick product master / free-form, qty×price, derived total); **revision** action (clone + `parent_quotation_id`); status-engine; **F3 doc attach**; raised against Lead (project_id nullable), back-linked on win.

**Deferred to later numbered plans:** Offerings + capacity_units + Tickets + nomination (D), unified Invoice + Payment + gateway provider + Settlement (F), Review (E), Agenda/Checkpoint (G/H), Venue/Seating layout designer + stadium import. All modeled above as forward contract.

---

## 5. Open items for the Cluster B plan (not blocking)

- Tree-editor component: extend an existing pattern, don't rebuild (reuse mandate).
- Quotation PDF render (F2) — lands with the Invoice/F2-binding plan, not B.
- Per-module Alembic migration for the new `app_ems` tables.
- New permission keys (`clients.*`, `leads.*`, `products.*`, `product_categories.*`, `quotations.*`) → module CSV; **grep core first** for name collisions (the `templates.*` lesson).
- Terminology registrations for the new entities (Client/Lead/Product/Quotation relabelable).

---

## 6. Deep grill — Registration / Ticketing / Capacity / Venue + Submission / Review (2026-06-18, round 2)

Grilled against all five `preliminary_planning/*_Functional_Spec.md`. **Two reversals + two new foundation enhancements** surfaced. These feed the Cluster D & E overview plans (`05`, `06`) and two foundation plans (`03`, `04`).

### 6.1 Reversal — Sales Order is BACK (was "no SO")
ERP chain reinstated for the **B2B/client** stream: **Quotation → Sales Order → Invoice → Payment**.
- **`sales_orders`** (NEW): `id, tenant_id, client_id, project_id (NULLABLE), quotation_id (NULLABLE source), currency, status_id` (Draft→Confirmed→Fulfilled→Cancelled), totals. **`sales_order_lines`** = shared line shape with quote/invoice → **one-click convert** (copy lines).
- **SO → Invoice is 1:N** (deposit / milestone / instalment billing). `invoice.sales_order_id` NULLABLE.
- **Attendee self-serve registration = Invoice-direct (no SO).** SO is for B2B / corporate / bulk only.
- Placement: SO lands with the finance cluster (**F**), bridging accepted Quotation (B) → Invoice.

### 6.2 Order header — Invoice is the order; comp = invoice_id NULL
Registration checkout creates `invoice(Draft)` + `invoice_lines` (per product) + N `tickets` referencing it. One receipt per cart. **Free/comp ticket = `ticket.invoice_id` NULL** (no money), eligibility flips directly. No separate Order entity for registration.

### 6.3 Capacity hold (oversell prevention) — timed hold + TTL
- **RESERVED:** `capacity_unit.status = held` + `held_until` + holder ref.
- **GA** (no unit rows): **`capacity_holds`** (NEW): `offering_id, qty, expires_at, session` — `remaining = capacity − sold − active_holds`.
- Scheduler sweep releases expired holds (~10–15 min TTL).

### 6.4 Venue = reusable tenant-level master (NOT per-project)
- **`venues`** (tenant-level: `name, address, capacity`) configured/imported ONCE; reused across every event held there.
- **`venue_seats`** = the reusable physical map; **`venue_zones`** = sections / halls / breakout rooms.
- A Project links via **`project_venues`**. Agenda sessions reference a **zone/room**; ticketing RESERVED offerings draw `capacity_units` from this venue's seats.
- **Reverses** the decisions-doc/legacy per-project `venues.project_id`.

### 6.5 Seat ↔ Offering = zone-based
A RESERVED Offering claims one or more **`venue_zones`** → `capacity_units` minted for every `venue_seat` in those zones, tagged `project_product_id` + `venue_seat_id`. A seat belongs to **exactly one offering per event**; capacity per offering = its zones' seat count. Seat-by-seat override = backlog.

### 6.6 Ticket = status-engine entity (revised from "simple enum")
`ticket` adopts the status engine: **Issued → Valid → CheckedIn → Transferred → Void/Refunded**. Scan a ticket QR → transition the ticket. `checkpoint_logs` reference `ticket_id` (+participant) as scan audit.

### 6.7 NEW FOUNDATION — Status Engine "Derived Status" (plan `03`)
`participant.Checked-in` is **derived from its tickets**; `invoice.Paid/Partially Paid` is **derived from its payments**; same shape recurs (project ← milestones). Decision: **build first-class derived/computed status in the status engine** — a status flagged *derived* carries a rule (rule-engine) over related/aggregate facts; the engine auto-evaluates + transitions on related-entity events (reuses rule engine + `entity_events` bus); derived statuses are not manually transitionable. **Prerequisite** for Cluster D (participant check-in) + F (invoice paid). **Needs its own dedicated grill** (rule declaration, trigger events, manual-vs-derived edge coexistence, two-tier/scoped behavior, UI read-only treatment).

### 6.8 Registration form binding — per-attendee form_submission
Project configures a `registration_form_id` (F1 form). Each admission ticket's attendee fills it → one `form_submission`, `subject_type=project_participant`. Standard fields (name/email/phone) → Profile; dynamic answers stay in `answers_json`. **Bulk Excel skips the form** (standard cols only; dynamic fillable later via a claim link).

### 6.9 Submission = bare form_submission; REVISION = core form engine, REVIEW = EMS module (plans `04` + `06`)
**No EMS submission wrapper.** An "abstract submission" is just a `form_submission` of a submission-type form. The two capabilities **split along the Profile dependency** (grilled 2026-06-18 — see plan `04`):

- **REVISION = generic, core form-engine feature (plan `04`, GRILLED).** No Profile dependency → stays core, any form benefits. `form_submissions` gains **`submission_group_id` + `revision_number` + `is_current`**; form-level **`allow_revisions`**; revise = clone current answers → new row at scoped initial (Draft), pinning its own `version_id`, prior frozen `is_current=False` keeping its last status; only from a frozen status; owner or `submissions.manage`. External refs point at `submission_group_id`. Review lifecycle rides the existing **scoped status graph**.

- **REVIEW = EMS-module feature (plan `06`), because reviewer = Profile** (core can't depend on the EMS Profile table; the earlier "review is a core feature" call is REVERSED). EMS tables `review_configurations` / `review_assignment_rules` / `review_assignments` grade **core `form_submission`s**; the form engine never learns reviewers are Profiles.
  - **A review = a core `form_submission` of a designated REVIEW FORM** (rubric = a normal F1 form); `review_assignment.review_submission_id` links it. Max reuse.
  - **Status semantics mapped via `review_configuration`** to the form's own scoped status ids (`review_start_status_id`/`revisions_status_id`/`accepted_status_id`/`rejected_status_id`) — no status-model pollution.
  - **Allocation = a tenant-built WORKFLOW** (`entity.status_changed` → an EMS `ems.allocate_reviewers` action; EMS seeds a default workflow on install), **first-N by rule order**, **author-self-excluded**; escalation = a scheduled `ems.escalate_reviews` workflow.
  - **Scoring:** review form designates ONE numeric **score field** → **average** across completed reviews; **Accept/Reject = human (chair)** transition (auto-threshold = backlog).
  - **Prerequisite:** Cluster D **Profile portal auth** (reviewers log in).

### 6.10 Updated forward-contract entity list (delta from §2)
ADD: `sales_orders` + `sales_order_lines` (F) · `capacity_holds` (D) · `venues` tenant-level + `venue_seats` + `venue_zones` + `project_venues` (D/G) · `ticket` as status entity (D). MOVE: Submission/Review OUT of EMS into the **Form Engine** (plan `04`). NEW ENGINE WORK: derived status (plan `03`).

> **Sequencing impact:** the two foundation enhancements (`03` derived-status, `04` form review/revision) are **prerequisites** and should be grilled+built before their consuming clusters (D needs `03`; E needs `04`; F needs `03`).

---

## 7. Round-3 re-grill — Cluster D boundary drift (2026-06-20, post-CRM-split)

After `02`/`03`/`04` merged AND the CRM-split + catalog-to-core merge (`08`, 2026-06-20) landed, Cluster D (`05`) was re-grilled because plan 08 moved module boundaries `05` assumed. Full detail in `05-...-venue.md` "Locked decisions — round 3" (R3-1..R3-8); summary delta to this forward contract:

- **Finance becomes its OWN module `app_finance` (REVERSES §2/§6.10 "invoices in app_ems").** `invoices`/`invoice_lines` are born in D inside `app_finance`; F extends the same module (payments/SO/settlement/derived Paid). `ems requires finance`; capabilities `finance.create_invoice@1` + `invoice.resolve@1`; `ticket.invoice_id` = cross-module soft-ref. Rationale = avoid the create-in-ems-then-move-in-F churn plan 08 just punished.
- **Catalog moved to core** (`08`) — offering `product_id` = sanctioned module→core FK; bill-to Client = `app_crm` soft-ref.
- **`03` derived-status + `04` form-revision now SHIPPED** — verified the participant-`Checked-in` mechanism against the real API (cross-entity `DerivedTrigger` + scoped-seed conditioned auto-edge; `reevaluate` handles scoped owners). Form-revision orthogonal to registration (single-shot).
- **Cluster D now ships Profile portal auth** (claim→set-password→login reusing core auth + thin attendee portal) — this is the §6.9 hard prereq for Cluster E reviewers. Identity merge = email-at-confirm (no cart-merge step).
- **Offering `submission_limit_per_user` → `max_tickets_per_attendee`** (enforce-by-email, not greyed).
- Module footprint of Cluster D = **three** modules: `app_ems` (registration/ticketing/venue/portal-auth) + NEW `app_finance` (invoices) + core (catalog).
