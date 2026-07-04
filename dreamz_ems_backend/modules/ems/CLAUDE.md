# EMS module — scope-local rules (`modules/ems/`)

> Read `../../../PRINCIPLES.md` first (governs) + `../../CLAUDE.md` (backend rules). This file = EMS-module essentials. Deep history in `../../../CLAUDE.md` ("EMS module" + Cluster sections).

## What this is
The EMS domain vertical (first big module), schema `app_ems` (`db.py EmsBase`). Entities: `profiles` (participant identity, NOT staff `users`), Type→Template→Project hierarchy, `project_participants`, and Cluster D (offerings/venues/capacity/carts/tickets/checkpoints). Invoices live in the separate `app_finance` module (born in Cluster D); `ems requires finance`.

## Hard rules
- **Cross-schema FKs to core (`tenants`/`statuses`/`products`) = plain indexed columns, NOT DB FKs** (BL-030); intra-`app_ems` FKs OK. Cross-module (invoice, client) = capability soft-ref (`invoice.resolve@1`, `client.resolve@1`), never a join.
- **Status entity adoption:** register in `bootstrap.py` (`_register_status_entities`) + seed graph; KEYS (`issued`/`valid`/`checked_in`/`transferred`/...) are a **code contract** — services look up by key, so they must stay locked from tenant rename. Participant eligibility is a SCOPED graph (scope=project_id); `Checked-in` is DERIVED (ticket→participant `DerivedTrigger` + aggregate facts), not manual.
- **New column/engine on an existing entity → backfill** existing rows AND existing tenant graphs (`update_tenant` seed-if-absent does NOT repair what already exists — bit us: ticket `status_id=NULL`, forked tenant graphs).
- **All engine registration** (status/terminology/importers/capabilities/product-kinds) flows through boot `register_engine_entities` — idempotent, additive.
- **Conftest wiring:** new EMS models must be imported before `create_all` + the module installed for the default tenant via `AppStoreService.install`.

## Permissions
EMS keys (`tickets.*`/`checkpoints.*`/`offerings.*`/`venues.*`/...) in `permissions/permissions.csv`. **Grep core first** (core owns `templates.*`; namespace module keys). A new key needs an existing-tenant grant sweep.

## Frontend
EMS UI on the Resource shell under `dreamz_ems_frontend/app/(protected)/ems/`. Tickets/Invoices tabs are REAL (BL-120) — `event-billing-service.ts` is wired to the backend; don't reintroduce the in-memory mock.

## Tests
`tests/test_ems_spine.py`, `tests/test_cluster_d*.py`. Synthetic status entities in the status/rule suites are named `synthetic_ticket` (the real `ticket` entity owns `ticket` in the shared registry — last-register-wins collides).
