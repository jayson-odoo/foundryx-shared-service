# Sprint-3 Roadmap - Closing the Foundation Gaps Before EMS Clusters

**Status:** In progress. Each foundation gets its own `grill-me` session + numbered plan before code. This doc frames *what*, *why now*, *in what order* - and now also tracks completion.

**Source baseline:** BRD v1.0 (`documentation/requirements/`), `EMS_Project_Plan.md`, current state = all sprint-1 + sprint-2 plans (01-10) merged to main.

**Progress (as of 2026-06-23):** F1/F2/F3 (blocking foundations) **DONE**; the F4 re-scope's three new foundations **F8 Terminology / F9 Import / F10 Module-Platform DONE** (sprint-3 plans 08-10); **F4 EMS domain spine DONE** (plan 11, `app_ems` module). The EMS verticals are now landing in **sprint-4**: **Cluster B** (CRM split + catalog→core, plans sprint-4/08) **MERGED**, **Cluster D** (Registration/Ticketing/Venue + finance module, sprint-4/05) **MERGED**, **Cluster E** (Profile Portal + generic Review/Approval engine, sprint-4/06) **MERGED** (`9067dd1`, 2026-06-23). **Next: Cluster F** (payment/finance depth) / **Cluster G** (agenda). F5 website builder still pending (isolated module).

| Plan | Foundation | Status |
|------|-----------|--------|
| 01 + 02 | F1 Form Engine | ✅ MERGED (`baffcaf`) |
| 03 + 03b | F2 Multi-format render (PDF + badge canvas) | ✅ MERGED (`f0b0562`, `9b53238`) |
| 04 + 05 | F3 Document Mgmt (Drive + sharing) | ✅ MERGED (`99b1a5f`, `aebe22b`) |
| 06 + 07 | Omnichannel WABA mgmt (config/profile/templates) | ✅ MERGED (`162459e`) - module work, not an F-gap |
| 08 | F10 Terminology engine | ✅ MERGED |
| 09 | F8 Import engine | ✅ MERGED |
| 10 | F9 Module Platform v2 (deps + capabilities) | ✅ MERGED |
| 11 | F4 EMS domain spine (`app_ems` module) | ✅ MERGED |
| sprint-4/08 | Cluster B - CRM module split + catalog→core | ✅ MERGED |
| sprint-4/05 | Cluster D - Registration/Ticketing/Venue + finance module | ✅ MERGED |
| sprint-4/06 | Cluster E - Profile Portal + generic Review/Approval engine | ✅ MERGED (`9067dd1`) |
| - | F6 / Cluster F - Payment + finance depth | ⬜ NEXT |
| - | F7 / Cluster G - Agenda builder | ⬜ pending |
| - | F5 Website builder | ⬜ pending (late isolated module) |

---

## 1. Where we stand

What is **LIVE** (the configure-not-code spine - BRD Cluster A is ~80% done):

- Multi-tenant SaaS, subdomain tenancy, tenant lifecycle on the status engine
- Auth / RBAC / impersonation / hardening / change-email / avatars
- **4 core engines**: Status & State Machine, Rule, Template (**email surface only**), Workflow
- Integration framework (connections, providers, Fernet secrets) + SMTP/email outbox + Storage (S3/R2/local)
- App Store (per-tenant module lifecycle) + first module (omnichannel/WhatsApp)
- Branding / white-label, datetime hygiene
- Reusable substrate: Resource shell, FlowCanvas, SearchSelect/MultiSelect, MergeFieldEditor, EmailEditor, rule-builder

What is **EMPTY**: the actual EMS domain. No Client, Lead, Project(Event), Product, Ticket, Invoice, Payment, Participant↔event-role, Submission, Review, Agenda/Session, Checkpoint. The platform was *built for* these (engines wire onto them) - but nothing in clusters B-H exists yet.

**Verdict:** the hard platform spine is done and reusable. But three cross-cutting foundations that multiple clusters consume are still missing. Building a vertical EMS feature before they exist forces rework (forms rebuilt 3×, render forked, attachments bolted on). Close the foundations first, then clusters become "domain entities + Resource shell + engine wiring" - which is what the platform was designed to make cheap.

---

## 2. The gaps (ranked)

| # | Gap | Type | BRD reqs | Consumed by | State today |
|---|-----|------|----------|-------------|-------------|
| F1 | **Form Builder engine** | 5th cross-cutting engine | R17, R14, R18/19, R6 | submissions, registration dynamic fields, review forms, onboarding checklists | ✅ **DONE** (plans 01+02) |
| F2 | **Multi-format render** (Template → PDF + image/badge) | extend existing engine | R3, R21, R29 | invoices, badges, tickets, certificates | ✅ **DONE** (plan 03+03b: WeasyPrint PDF + Konva badge canvas) |
| F3 | **Resource & Document Mgmt** | semi-foundation feature | R9 | quotation attach, invoice supporting docs, e-Perolehan PO upload | ✅ **DONE** (plans 04+05: Drive + sharing) |
| F4 | **EMS domain model** (now a **module**, not core) | first vertical module | every cluster | clusters B-H | ⬜ grilled+planned ([decisions](F4-foundations-grill-decisions.md)); blocked on F8/F9/F10 |
| F5 | **Website builder + subdomain publishing** | large, self-contained + infra | R10, R11 | Cluster C only | none; BL-076 (Puck front-runner) |
| F6 | **Payment + finance** | provider on integration fwk + entities | R22, R23 | Cluster F | framework ✓, finance ✗ |
| F7 | Agenda builder | feature, not foundation | R24-27 | Cluster G | none - reuses scheduler + WS |
| **F8** | **Import Engine** (generic bulk import, every Resource list) | 6th cross-cutting engine | R (bulk reg) | participant bulk-reg + every list | ⬜ grilled+planned ([decisions](F4-foundations-grill-decisions.md)) |
| **F9** | **Module Platform v2** (inter-module deps + 3rd-party extension) | core/governance | App Store | EMS-as-module + ecosystem | ⬜ grilled+planned; closes BL-029 |
| **F10** | **Terminology** (per-tenant entity relabeling) | core, small | - | every list/menu title | ⬜ grilled+planned |

> **F4 became a module.** Grill (2026-06-16) re-scoped the EMS domain from "core" to the **first vertical module** (`app_ems`), so core stays a horizontal platform sellable to non-EMS clients and the App Store has a flagship + 3rd-party room. That surfaced three new foundations (F8/F9/F10) that must land first. Full design: **[F4-foundations-grill-decisions.md](F4-foundations-grill-decisions.md)**.

---

## 3. Foundations to build first (F1-F3) - ✅ ALL DONE

> **All three blocking foundations shipped to main.** Plans 01-05 + reports in this dir. The remaining sections below are kept as the original framing; per-gap status banners record what landed.

### F1 - Form Builder engine *(highest blast radius)* - ✅ DONE (plans 01+02)
**Shipped:** 5th core engine (`app/form_engine/`, `types/forms.ts`), drag-drop builder + runtime renderer + server validator, scoped status-engine extension (`statuses.scope_id`), public anonymous surface, `form.submitted` workflow trigger, file/signature uploads, table/repeater/aggregate/integer/computed field types. Follow-ups: BL-086 (payment field), BL-087 (entity-sourced options), BL-088 (`entity.create` action), BL-089/090/093.

The BRD says "4 engines" but R17/R14/R18 all need a drag-drop JSON-schema form builder + runtime renderer + server-side validator. That is a **5th engine**, same shape as the others (block/field document + code-side registry + two-tier platform/tenant + merge/fact seams).

- **Builder**: drag-drop field palette (text, number, select, date, file, section, …), per-field validation (regex, min/max, required), conditional visibility (reuse rule-engine).
- **Runtime**: render a saved schema as a fillable form; save partial as draft; validate against schema on submit (front mirror + backend gate - the real boundary).
- **Storage**: `form_definition_json` (forever-contract, `types/forms.ts` ↔ `app/form_engine/schemas.py` parity), tenant-scoped, two-tier.
- **Consumers**: abstract submissions (E), registration dynamic fields (D), review forms (E). Build once, bind everywhere.
- **Reuse**: FlowCanvas patterns aren't a fit (it's a form, not a graph) - but Resource shell, SearchSelect, rule-builder, MergeFieldEditor seams carry over.
- **Grill targets**: field-type taxonomy, validation model, draft/version semantics, how a submitted entry binds to a domain record, file-field ↔ F3 storage, reviewer read-only rendering.

### F2 - Multi-format render *(extend Template engine, don't fork it)* - ✅ DONE (plan 03+03b)
**Shipped:** slice 1 = block-doc → WeasyPrint flowing PDF (table/repeater, no-Node), slice 2 = fixed-canvas Konva badge/ticket/cert designer (x/y element placement, fact binding, QR, fonts). Shared merge+brand seam reused; no engine fork. Binding to attendee/event entities lands with F4.

Template engine already proves block-doc + merge (anti-SSTI substitution) + brand seams. Add **render targets**, not a new engine. Research doc already concluded: separate *editors*, shared merge+brand seam.

- **PDF render**: invoices / certificates - flowing document → PDF (WeasyPrint = no-Node, fits the mrml/native stance; evaluate vs headless-chrome).
- **Fixed-canvas designer** (BL-071): badges / tickets - x/y placement canvas (Konva/Fabric) → fixed-size HTML → PDF; per-element fact binding + rule visibility; batch render.
- **Repeater block** (BL-072): structural list iteration for invoice line items / agenda rows - block-level, merge stays substitution-only.
- **Consumers**: R21 invoices, R29 badges, R3 tickets/certificates.
- **Grill targets**: WeasyPrint vs Puppeteer, fixed-canvas editor library, where badge/ticket designers live in the UI, batch-render trigger, font/asset embedding, **needs F4 attendee/event entities to bind** (designer can ship ahead, binding lands with the domain).

### F3 - Resource & Document Management *(domain-layer warm-up)* - ✅ DONE (plans 04+05)
**Shipped:** slice 1 = Drive (nested folders, versioned files on storage keys, upload/rename/move, list+grid, universal drawers, right-click menu, multi-target zip), slice 2 = sharing (FileShare tokens, access levels, expiry, Shared-with-me, CSP-sandboxed serving). Built as a **core hub** (not a module). Follow-ups: BL-094..102.

Google-Drive-ish repo. Storage service already does the bytes; this is the entity layer on top.

- **Entities**: Folder (nested), File (storage key + metadata), FileShare (token + access level + expiry).
- **Ops**: upload/rename/move, folder tree, attach a file to a quotation/invoice, expiring share links (view/edit), CSP-sandboxed serving (reuse branding-asset hardening).
- **Consumers**: R7 quotation attachments, R21 invoice docs, e-Perolehan PO upload.
- **Why early**: smallest of the three, sets the domain-layer + Resource-shell-for-a-real-entity patterns, and Cluster B (quotations) needs it.
- **Grill targets**: scope (project-scoped vs tenant-global), share-link security model, edit-access semantics, storage-key convention reuse, whether this is core or a module.

---

## 4. Then the domain (F4) - Cluster B as the first vertical

Once F1-F3 land, start the EMS proper with **Cluster B (CRM → Event → Quotation)** - the first real vertical slice. It exercises every new foundation + the existing engines:

- Lead/Client wizard (Resource shell + inline quick-create)
- Event(Project) from Project Type → auto checklist + tasks on a **status-engine Kanban**
- Quotation with revision lineage + **F3 document attach**
- DNS checker (**new provider on the integration framework**)

Then sequence **D → E → F → G → H**, each = new domain entities + Resource shell + engine wiring:
- **D** Registration/portal: unified profile, two-tier validity, ala-carte + bulk(Excel) reg, ticket transfer/nomination - consumes **F1** (dynamic fields)
- **E** Submissions/Review: **F1** forms, **rule-engine** reviewer allocation, **workflow** reminders/escalation, auto score average
- **F** E-commerce/Invoicing/Payment: invoices via **F2** PDF, **F6** payment provider + webhook logging, post-payment **workflow** automation
- **G** Agenda builder: drag-drop calendar, finish-to-start dependencies + delay cascade, real-time agenda (reuse omnichannel **WS** pattern), scheduler
- **H** Event day: QR checkpoint (**rule-engine** eligibility), on-spot payment, silent badge print (**F2** + local daemon), reminders (**workflow + template**)

Most of B-H is wiring, not new infrastructure - the engines were built for exactly this.

---

## 5. F5 - Website builder + subdomain publishing (open question - see discussion)

Largest unknown + its own infra (wildcard DNS, reverse proxy, dynamic SSR, SSTI surface on custom-HTML/pro-code uploads). Cluster C, self-contained. BL-076 scoped (Puck = MIT, JSON→own React components, front-runner; Craft.js downgraded for bus-factor). Blocked on Projects/Events (F4) existing for data-bound blocks (registration/agenda/speakers/tickets).

**Recommendation: isolate as a late module, not a foundation** - it gates nothing in B/D/E/F/H. Timing is the one open decision below.

---

## 6. Proposed order

1. ✅ **F1 Form Builder** + **F2 render** - DONE (plans 01-03)
2. ✅ **F3 Document Mgmt** - DONE (plans 04-05)
3. ✅ **F10 Terminology** ([`08`](08-terminology.md)) → **F8 Import Engine** ([`09`](09-import-engine.md)) → **F9 Module Platform** ([`10`](10-module-platform.md)) - the F4 prerequisites - DONE
4. ✅ **F4 EMS domain spine** ([`11`](11-ems-domain-spine.md), `ems` module) - DONE
5. ✅ **Cluster B** (CRM split + catalog→core, sprint-4/08) - DONE
6. 🟡 **D → E → F(+F6) → G → H** - clusters: **D** (sprint-4/05) ✅, **E** (sprint-4/06 - Profile Portal + generic Review engine) ✅; **F (payment/finance depth) NEXT**, then G, H
7. ⬜ **F5 Website builder** - isolated module (also hosts the participant registration portal), slot after the clusters

Detailed locked design for steps 3-4: **[F4-foundations-grill-decisions.md](F4-foundations-grill-decisions.md)**.

> Side track also merged this sprint (not on the F-path): **omnichannel WABA management** (plans 06+07) - config/profile/template tabs on the channel form.

Each step: `grill-me` → numbered plan in `sprint-3/` → frontend-first → backend → TDD → E2E → review → merge.

---

## 7. Open decision

- **F5 website builder timing** - defer to a late isolated module (recommended) vs pull earlier? Trade-off in the chat thread; not yet locked.
