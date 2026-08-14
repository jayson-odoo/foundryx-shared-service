# Sprint 4 · Plan 05 - Cluster D: Registration · Ticketing · Capacity · Venue - User Acceptance Criteria

**Source plan:** `05-cluster-d-registration-ticketing-venue.md` (GRILLED 2026-06-18 + round-3 re-grill 2026-06-20).
**Scope:** the attendee revenue stream (Profile → Participant → Ticket → Invoice) across `app_ems` + the NEW `app_finance` module + core catalog. Payment/gateway/SO/settlement = Cluster F; full event-day = H; visual seat designer = Venue plan.
**Format:** Given / When / Then. Each AC independently verifiable. ID = `AC-05-<area>-NN`. Areas: `FIN` finance module · `OFF` offerings/venue/capacity · `CART` cart/holds/checkout · `TKT` tickets/nomination/QR · `CHK` check-in/derived status · `IMP` bulk import · `AUTH` portal auth/identity · `PUB` public surface · `GOV` module/governance.

---

## A. Finance module & invoice (R3-1)

### AC-05-FIN-01 - `app_finance` installs as its own module
- **Given** a tenant installing the registration vertical
- **When** modules resolve
- **Then** `finance` is a distinct module (`app_finance` schema, own manifest + per-module Alembic baseline `alembic_version_finance`); `ems` declares `requires: [finance]` and install order resolves `finance → ems`.

### AC-05-FIN-02 - EMS install pulls finance (requires-guard)
- **Given** `finance` is NOT installed for a tenant
- **When** an operator/tenant installs `ems`
- **Then** the App-Store requires-guard either installs `finance` first (cascade-with-consent) or blocks with a clear "requires finance" message - never a half-install.

### AC-05-FIN-03 - Invoice status engine owned by finance
- **Given** finance is installed
- **When** the status entities load
- **Then** an `invoice` status entity is registered + seeded by **finance** with graph `Draft → Issued → Cancelled` (Cluster F extends it); it appears under finance, not ems.

### AC-05-FIN-04 - `finance.create_invoice@1` mints a Draft invoice
- **Given** a tenant with finance active
- **When** any caller invokes `finance.create_invoice@1(db, tenant_id, {project_id, bill_to_type, bill_to_id, lines[], currency})`
- **Then** an `invoice(Draft)` + `invoice_lines` are created in `app_finance`, totals (subtotal/tax/total) derived from lines, and the new `invoice_id` is returned.

### AC-05-FIN-05 - `invoice.resolve@1` is the cross-module read seam
- **Given** an invoice exists
- **When** ems calls `invoice.resolve@1(db, tenant_id, {id})`
- **Then** it returns the invoice header for display; an id from another tenant or a missing id returns None (tenant-scoped, BL-030), never raises.

### AC-05-FIN-06 - Bill-to name resolves cross-module, orphan-safe
- **Given** an invoice with `bill_to_type=Client` (app_crm) or `Profile` (app_ems)
- **When** finance renders the bill-to label
- **Then** it resolves via `client.resolve@1` / `profile.resolve@1`; if the referenced record is gone or its module inactive, the label is empty/None - no crash.

### AC-05-FIN-07 - `ticket.invoice_id` is a soft-ref, not an FK
- **Given** the `tickets` table in `app_ems`
- **When** schema is inspected
- **Then** `invoice_id` is a plain indexed column (no DB FK to `app_finance.invoices`); resolution is via `invoice.resolve@1`.

---

## B. Offerings, Venue master & capacity minting (slice 1, R3-4)

### AC-05-OFF-01 - Offering config from a core product
- **Given** a project and a core `product` of `kind=ADMISSION`
- **When** an admin creates a `project_product` (Offering)
- **Then** it stores price-override/currency/tax_rate/capacity/allocation_mode (GA|RESERVED)/valid_from/valid_until/grants_segment_id/grants_role_id/`max_tickets_per_attendee`; `product_id` is a sanctioned module→core FK.

### AC-05-OFF-02 - Venue master is tenant-level + reusable
- **Given** a tenant
- **When** a venue is created with zones + seats
- **Then** `venues`/`venue_zones`/`venue_seats` are tenant-level (not per-project) and a Project links via `project_venues`; the same venue is reusable across events.

### AC-05-OFF-03 - Seat generator mints capacity_units (functional grid)
- **Given** a RESERVED offering linked to a venue zone
- **When** the admin runs "generate N rows × M seats"
- **Then** `capacity_units` are minted (one per seat, status `free`) with auto labels (A1..), `section/row/number`, `x/y` as auto-grid coords, tagged `project_product_id` + `venue_seat_id`; an editable list/grid allows relabel/toggle/zone-set. **No drag canvas** (deferred).

### AC-05-OFF-04 - GA offerings mint NO unit rows
- **Given** an offering with `allocation_mode=GA`
- **When** it is saved
- **Then** zero `capacity_units` rows exist for it (counter-only); `remaining = capacity − sold − active_holds`.

### AC-05-OFF-05 - A seat belongs to exactly one offering per event
- **Given** a venue seat already drawn into one offering's capacity for a project
- **When** another offering of the same project tries to claim the same seat
- **Then** it is rejected (one offering per seat per event).

---

## C. Cart, holds, checkout, tickets & invoice (slice 2)

### AC-05-CART-01 - Anonymous cart with session token
- **Given** an unauthenticated visitor
- **When** they start a cart
- **Then** a `cart(open)` is created with `profile_id` NULL + `session_token` + `expires_at`.

### AC-05-CART-02 - RESERVED hold = atomic seat lock
- **Given** a free RESERVED seat
- **When** a visitor adds it to a cart
- **Then** the unit flips `free → held` atomically (`SELECT … FOR UPDATE`/`SKIP LOCKED`), with `held_until` + `held_by_cart_id`; a concurrent attempt on the same seat fails to acquire and sees it as held.

### AC-05-CART-03 - GA hold = counter guard
- **Given** a GA offering with remaining < requested
- **When** a visitor adds qty
- **Then** the add is rejected when `sold + active_holds + qty > capacity`; otherwise a `capacity_holds` row (qty, expires_at, cart) is created.

### AC-05-CART-04 - Hold TTL sweep releases expired holds
- **Given** a cart whose hold TTL (5-10 min) has elapsed without confirm
- **When** the scheduler sweep runs
- **Then** RESERVED units return to `free` (clear held_until/holder) and GA `capacity_holds` rows are deleted; the released capacity is purchasable again.

### AC-05-CART-05 - Live seat map broadcasts held/sold
- **Given** the interactive seat map is open for an offering
- **When** another visitor holds/releases/buys a seat
- **Then** the map updates live via omnichannel WS + Redis pub/sub (room per project/offering), and a visible countdown reflects the viewer's own hold TTL.

### AC-05-CART-06 - Confirm is atomic: profile + participant + ticket + invoice
- **Given** an open cart with valid holds + per-attendee registration answers
- **When** the visitor confirms
- **Then** in ONE session: per attendee find-or-create Profile by email → mint/link ProjectParticipant (copy `grants_segment_id`/`grants_role_id` onto participant) → mint Ticket (signed QR; RESERVED unit `held → sold`) → and (paid) one Draft invoice via `finance.create_invoice@1` with `ticket.invoice_id` set. Any failure rolls the whole txn back (no orphan seat/ticket/invoice).

### AC-05-CART-07 - Final backstop prevents oversell at confirm
- **Given** a race where a hold expired between add and confirm
- **When** confirm runs
- **Then** a final UNIQUE/state-check rejects the now-invalid seat/over-capacity confirm (409) rather than overselling.

### AC-05-CART-08 - Comp path = invoice_id NULL
- **Given** an admin issuing a free/comp ticket
- **When** the ticket is minted
- **Then** `ticket.invoice_id` is NULL, no `finance.create_invoice@1` call is made, and participant eligibility flips directly.

### AC-05-CART-09 - Admin add-one
- **Given** an admin on an event
- **When** they register one attendee directly against an offering
- **Then** a ticket (+ Draft invoice, or comp) is created without going through the public cart.

### AC-05-CART-10 - New-profile claim mail
- **Given** confirm find-or-creates a brand-new Profile
- **When** the txn commits
- **Then** a claim/activation mail is enqueued (workflow), addressed to that attendee; an already-existing Profile gets no duplicate claim mail.

---

## D. Tickets, nomination & QR (R3-1 ticket entity)

### AC-05-TKT-01 - Ticket rides the status engine
- **Given** the `ticket` status entity
- **When** it loads
- **Then** graph = `Issued → Valid → CheckedIn → Transferred → Void/Refunded`, registered + seeded.

### AC-05-TKT-02 - QR is signed/opaque
- **Given** a minted ticket
- **When** its `qr_token` is generated
- **Then** it is a signed token (Fernet/HMAC via `app/secrets.py`) encoding `ticket_id` - not forgeable, not enumerable; a tampered token fails signature validation at scan.

### AC-05-TKT-03 - Nomination/transfer rotates the QR
- **Given** an invoice owner reassigning `attendee_profile_id`
- **When** the transfer commits
- **Then** the ticket → `Transferred`, the QR token is rotated (old token no longer validates), and the nominee CANNOT re-transfer; money/`invoice_id` untouched.

### AC-05-TKT-04 - Void/refund kills the QR
- **Given** a ticket voided or refunded
- **When** the transition fires
- **Then** the QR is rotated/invalidated (old QR dies) and the seat (RESERVED) returns to sellable per the void rules.

---

## E. Check-in & derived participant status (R3-2)

### AC-05-CHK-01 - Checkpoint scan validates the chain
- **Given** a scanner posts a QR token
- **When** the server validates it
- **Then** it verifies the signature → resolves ticket → participant → project → checkpoint rules (segment + eligibility + entry-type); an invalid signature or wrong-segment ticket is denied with a reason logged.

### AC-05-CHK-02 - Double-entry blocked by dedup
- **Given** a ticket already scanned at a SINGLE-entry checkpoint
- **When** the same ticket is scanned again
- **Then** the second scan is denied (single `checkpoint_logs` dedup on ticket_id + checkpoint).

### AC-05-CHK-03 - Participant `Checked-in` is derived, not manual
- **Given** a project participant on its scoped eligibility graph (seeded with a `Checked-in` node + a conditioned auto-edge)
- **When** the participant's admission tickets reach CheckedIn such that `checkedInTicketCount == admissionTicketCount (>0)`
- **Then** the cross-entity `DerivedTrigger(participant ← ticket)` re-evaluates and the auto-edge fires the participant to `Checked-in`; the status is NOT manually transitionable.

### AC-05-CHK-04 - Derivation is failure-isolated
- **Given** a check-in scan committing a ticket transition
- **When** the derived re-evaluation runs
- **Then** it rides the after-commit drain's isolated commit - a broken/slow derivation NEVER 500s the scan; loop-safe (DERIVED-origin events skipped).

### AC-05-CHK-05 - New projects inherit the Checked-in node
- **Given** D seeded `PARTICIPANT_SCOPE_SEED_STATUSES`/`_EDGES` with Checked-in
- **When** a new template is created and a project created from it
- **Then** the materialized (template) and copied (project) participant graphs both contain the `Checked-in` node + auto-edge. *(Pre-D scopes require a backfill - dev reseed covers.)*

---

## F. Bulk import ticket mode (R3-5)

### AC-05-IMP-01 - Three ticket modes on the import page
- **Given** the EMS participant importer in a project context
- **When** the import page renders
- **Then** a job-level **Ticket mode** control offers `Participants-only` | `Comp` | `Paid`.

### AC-05-IMP-02 - Offering required when issuing tickets, GA-only v1
- **Given** Ticket mode = Comp or Paid
- **When** the page renders
- **Then** an **Offering** SearchSelect is required and lists **GA offerings only** (RESERVED excluded in v1); Participants-only hides the offering picker.

### AC-05-IMP-03 - Paid bulk = consolidated Client invoice
- **Given** Ticket mode = Paid with a bill-to Client picked
- **When** the import commits N rows
- **Then** N tickets are created and **one consolidated Draft invoice** to that Client (via `finance.create_invoice@1`) covers all N lines; Comp creates tickets with `invoice_id` NULL and no invoice.

### AC-05-IMP-04 - Capacity validated at Test, never oversells
- **Given** an import whose qty would exceed an offering's remaining GA capacity
- **When** the **Test** phase runs (dry-run, zero writes)
- **Then** it reports a per-row/aggregate capacity error (`sold + held + import_qty ≤ capacity`) and the Import (commit) is blocked - no oversell.

### AC-05-IMP-05 - Blocked-status profiles refused (engine gate carries over)
- **Given** a row whose existing profile has a `blocks_access` tier-1 status (Suspended/Blacklisted)
- **When** Test runs
- **Then** that row errors (422) and is not ticketed - matching the existing participant-add gate.

---

## G. Profile portal auth & identity (R3-6)

### AC-05-AUTH-01 - Claim link sets a password
- **Given** a new-profile claim mail
- **When** the attendee clicks the claim link and sets a password
- **Then** the Profile's reserved auth columns activate (password hashed via core `security.py`), reusing the core single-use-token + password-policy machinery (plan 10); the token is single-use + expiry-bound.

### AC-05-AUTH-02 - Profile portal login
- **Given** an activated Profile
- **When** they log in at the public/portal
- **Then** they authenticate via the reused core auth stack (throttle applies) and reach a thin attendee `/portal`.

### AC-05-AUTH-03 - Attendee portal shows own tickets only
- **Given** a logged-in Profile
- **When** they open `/portal`
- **Then** they see their own tickets / registrations (tenant + profile scoped) - never another attendee's.

### AC-05-AUTH-04 - Identity merge = email-at-confirm, no cart-merge
- **Given** a repeat anonymous buyer using the same email
- **When** they confirm a new cart
- **Then** find-or-create returns the SAME Profile and purchases accumulate on it; an abandoned anonymous cart simply expires (no separate cart-merge step, no duplicate profile).

---

## H. `max_tickets_per_attendee` (R3-7)

### AC-05-OFF-06 - Column renamed
- **Given** the `project_products` schema
- **When** inspected
- **Then** the per-attendee cap column is `max_tickets_per_attendee` (nullable) - NOT `submission_limit_per_user`.

### AC-05-OFF-07 - Cap enforced by email at confirm (incl. anonymous)
- **Given** an offering with `max_tickets_per_attendee = K`
- **When** an attendee (resolved by email at confirm) would exceed K across their non-void tickets for that offering (existing + cart qty)
- **Then** confirm returns **409**; the cap is enforced even for anonymous checkout (email is captured), NOT greyed out.

---

## I. Public registration surface (Q7)

### AC-05-PUB-01 - Standalone public registration page works
- **Given** a published event with public offerings
- **When** an anonymous visitor opens the public registration page (`app/(public)/public/...`)
- **Then** they can browse offerings (filtered by window + remaining), pick seats (RESERVED) on the live map, hold, fill the per-attendee registration form (reused `FormRenderer`), and confirm - all without F5.

### AC-05-PUB-02 - Closed/full events show friendly state
- **Given** an event outside its sales window or at capacity
- **When** the public page loads
- **Then** it shows a friendly closed/full state (not a crash/404).

---

## J. Module, governance & permissions (R3-8)

### AC-05-GOV-01 - Entities land in the correct module
- **Given** the Cluster D schema
- **When** inspected
- **Then** offerings/venues/zones/seats/project_venues/capacity_units/capacity_holds/carts/cart_items/tickets/portal-auth live in `app_ems`; invoices/invoice_lines in `app_finance`; products/product_categories in core.

### AC-05-GOV-02 - No permission-key collisions
- **Given** new permission keys (`finance.*`, `tickets.*`, `offerings.*`, `venues.*`, `carts.*`, `portal.*`)
- **When** module CSVs sync at bootstrap
- **Then** none collide with existing GLOBAL `permissions.key` rows (grep-core-first done) - no UNIQUE violation; keys grant to the tenant Admin via the install-aware grant.

### AC-05-GOV-03 - Terminology relabelable
- **Given** the new entities
- **When** terminology loads
- **Then** ticket / offering / venue / invoice are registered as relabelable `TermDef`s.

### AC-05-GOV-04 - No core-table mutation; cross-schema rules honored
- **Given** the modules' migrations
- **When** reviewed
- **Then** neither module ALTERs core `public` tables; cross-schema refs to core (`tenants`/`statuses`/`products`) are plain indexed columns or sanctioned module→core FKs; cross-module refs (Client, invoice) are capability soft-refs (BL-030).
