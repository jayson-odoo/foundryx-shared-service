# PLAN - Ideation Phase A: Capture (shared-service)

**Status:** Planning (UAC-first; no code yet) - 2026-07-18. Fulfils
`ideation-phase-a-capture-acceptance-criteria.md` (AC-A-01..47).
**Classification:** MODULE / **Service** on the Foundryx shared-service platform. New module
`service_backend/modules/ideation/` (schema `app_ideation`, `IdeationBase`), `requires:["omnichannel"]`.
Tenant = Foundryx-internal for now (D1).
**Spine (authoritative):** `PLAN-ideation-to-delivery-program.md` - §2 (D1-D21, incl. D20 no-LLM + D21 respond.io cron sync), §3 (entities), §5
(Cross-Repo Contracts). §5.1 (`create_idea`) and §5.3 (product-domain link + embed SSO) are copied into
this plan verbatim and **must not drift** - change the master first.
**Cross-repo siblings (separate plans):** sorento `ideate` intent + iframe host (§5.2); n8n `ideate`
routing (§5.5). This plan stops at the shared-service boundary.
**Out of scope:** all of Phase B (BR/FR, grilling chat, Outline RAG) and Phase C (AgentRunner, Mac Mini
daemon, GitHub, preview) - including the `github`/`agent_runner`/`deploy` adapter kinds, which are
*registered-but-dormant* here (AC-A-07).

---

## 1. Problem & goal

Raw ideas must land via the **existing CRM WhatsApp number** (D6), get structured into a durable **Idea**
against a **Product**, be deduped, triaged on a Canny-style board, and surfaced back to submitters - all
on the shared-service platform, embeddable seamlessly into each product's own domain via iframe SSO. The
capture surface must be a **generic Conversational-Intake engine** (D18) so ideation is just its first
*definition*; the intake logic must live in **exactly one place** - the `create_idea` HTTP endpoint (D7)
- so sorento/n8n stay thin.

**Hard constraint - shared-service runs NO LLM (D20).** It is **data + UI + relay only**: no assistant
port, no LLM key, no embedding pipeline. In Phase A this means `create_idea` is a **deterministic** path
(validate-against-schema + `pg_trgm` text-similarity dedup + persist) - field-extraction already happened
in sorento's brain. Dedup and cluster suggestions use `pg_trgm`, **not** embeddings. respond.io contact
resolution is a **cron sync of shared-service's own contact copies matched by phone** (D21), not an LLM
or a passed ref.

## 2. Grounding in what exists (cited)

The design reuses, not reinvents, these shared-service primitives:

- **Module/App-Store doctrine** - `app/module_loader.py` (`discover_manifests`, `load_modules` gate
  injection, `bootstrap_modules`, `register_module_boot`), `app/module_platform/` (dependencies,
  capabilities, active). Reference module = `modules/omnichannel/` (manifest.json, `bootstrap.py` with
  `install`/`install_tenant`/`update_tenant`/`uninstall_tenant`/`tenant_has_data`, `db.py` `OmniBase`
  + schema `app_omnichannel`, per-module `alembic/`). Ideation copies this shape.
- **form_engine (core)** - `app/form_engine/schemas.py` (`FormDocument` Page→Section→Field, stable answer
  keys, `validate_form_doc` publish gate), `computed.py`, `validation.py`. Backs `IntakeDefinition.target_schema`.
- **status_engine (core)** - `app/status_engine/registry.py` (`StatusEntity`, `register_status_entity`,
  tenant-owned vs scoped, `count_records`/`migrate_records`, derived/traits hooks). Idea rides this.
- **catalog (core)** - `app/models/catalog.py` `Product` + `app/catalog/kinds.py` product-kind registry.
  **NB collision:** this core `public.products` is the *quotation/ticketing* catalog (`kind∈{good,service}`).
  The program's **Product** (kind goods|software, adapters) is a **different entity** - see Decision D-A2.
- **Connection registry (core)** - `app/models/connection.py` (one active row per (tenant, provider),
  `config_json` non-secret + `credentials_json` Fernet). Used for `provider="respond_io"` (AC-A-26) and
  the embed connection (`provider="ideation_shared"`, AC-A-39). `app/secrets.py` for encryption,
  `app/integrations/base.py` for the provider framework.
- **Embed framework (in omnichannel today)** - `modules/omnichannel/embed_auth.py`
  (`get_conversation_principal`, `EmbedPrincipal`, scope/caps enforcement), `services/embed_session_service.py`
  (`exchange`: HS256 assertion → `typ="embed"` token, single-use `jti`, `parentOrigin` allow-list,
  `allowed_origins_for`), `routers/embed.py` (`POST /embed/session`, `GET /embed/frame-policy`),
  models `ExternalAgent` + `EmbedJti`. FE precedents:
  `service_frontend/app/embed/omnichannel/{thread,inbox}/page.tsx`. **This is what D17 says to generalize.**
- **Omnichannel contacts + respond.io-shaped gateway** - `modules/omnichannel/models.py` (`Contact`,
  `ContactChannelIdentity`, `Workspace`), `routers/api_v1.py` + `schemas.py` `Rio*` (the public gateway is
  already respond.io-*compatible* as a server - see Decision D-A4). `messaging.send@1` capability handler
  in `bootstrap.py::_messaging_send` (resolved via `app/module_platform/capabilities.py::resolve_capability`)
  backs submitter notifications (AC-A-43).

## 3. Decision log

- **D-A1 - Ideation is a MODULE (Service), not core.** Reusable capability a tenant installs; own schema
  `app_ideation`, own `IdeationBase`, per-module alembic, `require_module("ideation")`. `requires:["omnichannel"]`
  (needs contacts + `messaging.send`). Cross-schema **normal FKs** into `public`/`app_omnichannel` where a
  real relationship exists (doctrine: cross-schema FKs are fine).
- **D-A2 - REVISED 2026-07-19 (owner decision): ONE Product entity = core `public.products`.** The program
  Product is **combined into the core catalog** rather than a separate `app_ideation.products` table. The
  active kind set becomes `goods|service|software`: core seeds `good`/`service`; the **ideation module
  registers the `software` kind at install** via `register_product_kind` (the same extensibility EMS uses to
  add its kinds), so `software` is visible only while ideation is installed and appears automatically in the
  core `/products/kinds` endpoint. Product CRUD **reuses the existing core catalog product API**
  (`/products`, `products.*` perms) - no duplicate CRUD. Delivery-target attributes that only a software
  product needs (`product_domain_base`, adapters) live in an ideation **extension table**
  `app_ideation.product_delivery` (+ `app_ideation.product_adapters`) keyed 1:1 to `public.products` via a
  normal cross-schema FK - the catalog table stays clean, one product identity. Ideas carry a normal
  cross-schema FK `product_id → public.products`. *(Supersedes the original "separate entity / schema
  namespacing" call; the earlier contract gap is resolved by unification, not separation.)*
- **D-A3 - Idea rides the status engine as a tenant-owned entity.** `register_status_entity("idea", …)` with
  the §3 lifecycle; triage board columns = statuses (drag = `status_machine.transition`, server-authoritative).
  Contrast: catalog `Product.is_active` is a plain flag (not the engine) - Idea deliberately uses the engine
  because its lifecycle *is* the product surface (the Canny board).
- **D-A4 - respond.io in shared-service = workspace↔Product binding + its OWN cron-synced contact copies
  (D21), NOT a new BSP send adapter and NOT a passed ref.** The public `/api/v1/omnichannel/*` gateway is
  already respond.io-*shaped* (Rio* schemas) - it is a server FOR respond.io-style consumers. Per D6 the
  *sends* ride the CRM WhatsApp (sorento's respond.io) through omnichannel. Per **D21**, shared-service
  keeps **its own copies of the respond.io contacts** (mirroring sorento's sync): a scheduled cron job
  pulls contacts from the **respond.io API** on the bound workspace's `Connection provider="respond_io"`
  and upserts them into shared-service's own contact store (omnichannel `Contact` + `ContactChannelIdentity`,
  keyed by phone E.164). So Phase A adds: the `Connection` (contact-sync creds) + an
  `app_ideation.product_bindings` table binding `(connection_id, external_workspace_id) → product_id` + a
  **`ContactSyncService`** cron. On `create_idea`, the submitter phone (E.164) is **matched** to a synced
  copy; an unmatched phone create/enriches the copy from the respond.io API on the fly - shared-service
  never blindly trusts a contact id handed over by sorento. (Resolves the earlier sync-direction gap: the
  sync pulls from respond.io's API, D21.)
- **D-A5 - `create_idea` = one authenticated shared-service HTTP endpoint (§8-R3), no LLM (D20).**
  Shared-service owns ALL intake logic (`POST /ideation/intake/create-idea`, integration/workspace-key
  auth, uniform error envelope), called **server-to-server** by the sorento brain - **not** an MCP tool
  (shared-service has no MCP write server; `sorento_crm_mcp` is read-only). The sorento side wraps it behind
  its own `POST /api/v1/external/ideation/turn`. The endpoint runs **no LLM**: deterministic
  validate-against-schema + `pg_trgm` dedup + persist; extraction already happened in sorento's brain (D7,
  reconciled §8-R3).
- **D-A6 - dedup is `pg_trgm` text-similarity, NOT pgvector/embeddings (D10/D20).** Shared-service runs no
  LLM/embedding model, so the ideation migration provisions `CREATE EXTENSION IF NOT EXISTS pg_trgm` + a
  **GIN trigram index** (`gin_trgm_ops`) on the Idea dedup text; there is **no `vector` extension and no
  `embedding` column**. Dedup is a single inline `similarity()` / `%` query per-product, tenant-scoped,
  above a configured similarity threshold. **No embedding worker, no async pipeline** (unlike sorento).
  Semantic (embedding-based) dedup, if ever wanted, is delegated to Claude Code/sorento - never in
  shared-service. (Resolves the earlier pgvector/pipeline gap.)
- **D-A7 - Embed generalization: extract a core embed primitive, adopt in both modules.** D17 says
  "generalize the omnichannel embed framework". The clean call is to lift `embed_session_service` +
  `embed_auth` scope/caps + `EmbedJti` into a core `app/embed/` primitive parameterized by
  `(provider, audience, principal-scopes)`, and have omnichannel and ideation both register into it.
  **Pragmatic fallback if extraction is too costly for Phase A:** copy the pattern into the ideation module
  with `provider="ideation_shared"` / audience `"ideation-embed"` and a follow-up refactor ticket. Decide at
  Slice J kickoff. Either way the assertion→token/`parentOrigin`/`frame-policy` semantics stay identical.
- **D-A8 - clustering is a proposal engine; humans decide (D5/D16).** No auto-merge, no auto-promote.
  Cluster suggestions reuse the same **`pg_trgm` text-similarity** as dedup (no LLM/embedding - D20);
  acceptance writes `idea_clusters` - the seam Phase B BR promotion consumes.
- **D-A9 - Notifications are milestone-only + idempotent** (D12), via `resolve_capability("messaging.send")`
  keyed to `submitter_contact_id`; template/merge-field content, never free text; at-most-once per milestone.

## 4. Data model (schema `app_ideation`, per-module alembic baseline)

- **Product = core `public.products`** (REVISED D-A2). No `app_ideation.products`. Ideation registers the
  `software` product-kind at install; CRUD reuses the core catalog product API.
- `product_delivery` - `id, tenant_id, product_id FK public.products (UNIQUE), product_domain_base
  (validated origin), created_at, updated_at`. The software product's delivery config; source of the
  product-domain link origin (AC-A-38). (D-A2 revised)
- `product_adapters` - `id, tenant_id, product_id FK public.products, kind ('embed_connection'|'github'|
  'agent_runner'|'deploy'), config_json, credentials_ref (Connection id, nullable)`. Phase A wires only
  `embed_connection`. (AC-A-07)
- `product_bindings` - `id, tenant_id, product_id FK public.products, connection_id FK public.connections,
  external_workspace_id`, UNIQUE `(connection_id, external_workspace_id)`. (AC-A-27/29)
- `ideas` - `id, tenant_id, product_id FK public.products, status_id FK public.statuses, intake_definition_key,
  problem, raw_text, source, submitter_contact_id (FK app_omnichannel.contacts), captured_json,
  upvotes (int), created_at, updated_at`. **No `embedding` column** - dedup is `pg_trgm` (D-A6). (AC-A-09)
- `idea_attachments` - `id, tenant_id, idea_id FK ideas, kind ('audio'|'image'|'file'), storage_key/ref,
  meta_json`. (AC-A-24; rides the generic storage-locations declaration like omnichannel media.)
- `idea_upvotes` - `id, tenant_id, idea_id FK ideas, submitter_contact_id`, UNIQUE `(idea_id,
  submitter_contact_id)` (idempotent upvote, AC-A-21).
- `idea_clusters` + `idea_cluster_members` - accepted clusters + membership (AC-A-35).
- `intake_drafts` - thin pointer/index if needed; **the draft Idea itself is the durable SoR** (D8) so no
  separate draft store - `ideas` with `status=draft` IS the draft.
- pg_trgm: `CREATE EXTENSION IF NOT EXISTS pg_trgm` + a **GIN trigram index** (`gin_trgm_ops`) on the Idea
  dedup text (`problem` / normalized `raw_text`), used with a `(tenant_id, product_id)` filter. **No
  `vector` extension.** (AC-A-30, D-A6)

Migration: Postgres-only DDL (extension + schema + tables); no-op on the SQLite test engine (conftest
`create_all`). Follow the omnichannel per-module alembic baseline pattern (BL-029). Revision id ≤ 32 chars.

## 5. Backend layering

- **Registries (code-side, boot-time, idempotent):**
  - `app_ideation` adapter-kind registry (`product_adapters.kind`) - mirrors `app/catalog/kinds.py`.
  - `IntakeDefinition` registry - `{key, target_schema, completion_rule, on_complete_sink, agent_role}`;
    `ideation` is the one entry (D18). Registered in `bootstrap.register_engine_entities`.
  - Idea `StatusEntity` via `register_status_entity` (D-A3), + storage-locations declaration for attachments.
- **Services:**
  - `IntakeService` (the Conversational-Intake engine) - schema application, `completion_rule` eval
    (captured/missing over `target_schema`), `on_complete_sink` (idempotent draft→captured + link mint).
  - `CreateIdeaService` - the §5.1 endpoint body: input validation, product_id-from-binding resolution,
    submitter phone→contact-copy match (D-A4), draft-on-turn-1, dup-check, output assembly. **Deterministic,
    no LLM** (D20); **the single home of intake logic** (D7).
  - `DedupService` - `pg_trgm` `similarity()` / `%` query over existing Idea rows, per-product/tenant, above
    a similarity threshold. No embeddings (D-A6).
  - `ClusterSuggestionService` - proposal-only clustering over the same `pg_trgm` similarity (D-A8).
  - `ProductBindingService` + respond.io `ContactSyncService` - the **cron** that pulls contacts from the
    respond.io API and upserts shared-service's own contact copies (omnichannel `Contact` +
    `ContactChannelIdentity`, keyed by phone E.164); on intake, matches the submitter phone (E.164) to a copy
    and create/enriches it if unmatched (D21, D-A4).
  - `IdeaNotificationService` - milestone-only, idempotent, via `resolve_capability("messaging.send")`.
  - `IdeationEmbedService` - the generalized embed exchange (D-A7).
- **Routers (manifest):** `products`, `ideas` (+ triage/board + clustering), `intake` (public,
  integration-key), `bindings`/`settings`, `embed` (public: `/embed/session`, frame-policy), `embed_reads`
  (public: board/detail reads). Public-flag exactly the tenant-unresolvable endpoints (AC-A-45).
- **Permissions CSV** - `ideation.products.manage`, `ideation.ideas.view`, `ideation.ideas.submit`,
  `ideation.ideas.upvote`, `ideation.triage.manage`, `ideation.clusters.manage`, `ideation.bindings.manage`,
  mapped to Submitter/Triager/Maintainer (AC-A-36).

## 6. Cross-repo contract restatements (byte-for-byte - do not drift)

**§5.1 `create_idea`** (authenticated HTTP endpoint, server-to-server, **no LLM** - §8-R3/D20):
- Input: `{ product_id, submitter_contact_id, message_text, audio_attachment_ref?, draft_id? }`
  (`product_id` derived from the workspace↔Product binding, never the human; `submitter_contact_id` passed
  as **phone E.164** and **matched** to shared-service's own cron-synced respond.io contact copy, D21;
  `draft_id` absent turn 1).
- Output: `{ draft_id, status: "collecting"|"complete"|"duplicate", captured: {...}, missing: ["field", ...],
  reply_text, link?, duplicate_of? }`. `complete` → Idea `captured` + `link` = product-domain deep link;
  `duplicate` → `duplicate_of`. Idempotent on `draft_id`.

**§5.3 link + embed:** link = `{product_domain_base}/ideas/{idea_id}` (never a shared-service URL). Sorento
`/ideas/{id}` renders `<iframe src="{shared_service}/embed/ideas/{id}">`; sorento BE mints a signed
assertion → `POST {shared_service}/embed/session` → embed token (`typ="embed"`); connection `allowedOrigins`
includes the sorento origin; `frame-policy` permits the frame.

## 7. Three-phase build (shared-service methodology: FE-prototype → TDD-backend → review)

### Phase 1 - FE prototype (mock data, no backend)
Build against mock fixtures / stubbed hooks in `service_frontend`:
- Ideation Service nav entry + **triage board** (Canny columns by status, drag between columns, upvote,
  submitter shown human-readable) - mock ideas covering every state (draft/captured/triaged/linked/
  duplicate/rejected) + a cluster-suggestion panel (accept/reject).
- **Idea detail** page (all sections always rendered, empty states with CTA).
- **Product** + **binding** admin screens (list + modal create/edit per CRUD-UX standard).
- **Embed board/detail** chromeless pages (`app/embed/ideas/*`) mirroring the omnichannel embed pages,
  handshake stubbed.
- Verify each state via Playwright MCP (through the sidebar, not deep URL); screenshot golden + edge cases.
- Output: the **expected API contract** documented at the top of the ideation service files (matching §5).
  No backend, no tests yet.

### Phase 2 - TDD backend + wire off mocks (test-first, red→green→refactor)
Author failing tests first, then implement:
- **pytest (BE):** `create_idea` contract (input/output byte-for-byte, draft-on-turn-1, idempotency,
  complete→captured+link, duplicate→upvote, product_id-from-binding refuses spoof, submitter phone→contact
  match + unmatched-phone create/enrich), interrupt/resume, IntakeDefinition/completion-rule, **`pg_trgm`
  dedup** (real duplicate → upvote; below-threshold proceeds; cross-product isolation), Idea status
  transitions + triage drag authorization, clustering proposals (`pg_trgm`), respond.io binding +
  **cron contact-copy sync from the respond.io API**, embed exchange (assertion→token, jti replay, origin
  allow-list, scope/caps 403, frame-ancestors), notifications (milestone-only + idempotent), module
  install/uninstall + reverse-dep guard, public-router exceptions.
- **vitest (FE):** board/detail/product/binding components (loading/empty/error/data), intake-status
  rendering, embed handshake hook.
- **playwright (E2E):** AC-A-47 round-trip (brain-harness `create_idea` across turns → captured Idea →
  board drag → minted product-domain link → `/embed/ideas/{id}` renders + wrong-origin blocked). Real
  fixtures (audio sample) committed under `e2e/fixtures/`.
- Provision `pg_trgm` (not pgvector); run `alembic upgrade head` against live Postgres (broken migration is
  invisible to SQLite pytest). Replace all FE mocks with real hooks/services/api-client.

### Phase 3 - review
`/code-review` on the merged Phase 1+2 branch; address findings; verify DoD gate (AC-A-46) - no unswapped
mock, server-side enforcement proven, embed at 375px + 1280px on a fresh prod build, no omnichannel/catalog
regression; test report keys every AC-A-NN. Then open the PR.

## 8. Risks & mitigations

- **Product naming collision** (D-A2) - mitigated by schema namespacing; flagged to program owner.
- **Embed extraction cost** (D-A7) - decide extract-vs-copy at Slice J; either preserves the contract.
- **`pg_trgm` net-new** (D-A6) - extension provisioning + GIN trigram index must be validated on live
  Postgres, not just SQLite tests; the similarity threshold is a small Slice-E tuning sub-decision. No
  embedding model/worker is introduced (D20).
- **respond.io cron sync** (D-A4/D21) - the contact-copy sync pulls from the respond.io API on a schedule;
  first-turn cold-start (unmatched phone) must create/enrich the copy inline so intake never blocks.
- **Live-flow / cross-repo** - the sorento `ideate` intent + n8n routing are separate plans; this plan must
  not assume their internals beyond §5.1/§5.2/§5.5.
- **Transport** (D-A5) - `create_idea` is an HTTP endpoint (reconciled §8-R3), not an MCP tool;
  shared-service has no MCP write server and runs no LLM.

## 9. Contract gaps - status after the 2026-07-18 reconciliation (master §8)

1. **Product entity name collides** with core `public.products` (catalog). **Resolved (§8-R1)** locally via
   `app_ideation.products`; the master notes the distinction (or rename the program entity, e.g.
   `DeliveryTarget` / `SoftwareProduct`).
2. **respond.io role - RESOLVED (D21 / §8-R2).** Shared-service **cron-syncs its own contact copies from the
   respond.io API** and **matches by phone (E.164)** on `create_idea`; contact identity is NOT a passed ref.
   The *sends* still ride the CRM number (D6). No further clarification needed.
3. **Transport - RESOLVED (§8-R3).** `create_idea` is an authenticated **HTTP endpoint**, server-to-server;
   shared-service has no MCP write server (`sorento_crm_mcp` is read-only). Not an MCP tool.
4. **Dedup - RESOLVED (D10/D20 / §8-R4).** No pgvector/embedding in shared-service (it runs no LLM); dedup is
   **`pg_trgm` text-similarity** with a GIN trigram index. Semantic dedup, if ever wanted, is delegated to
   Claude Code/sorento.
5. **Embed generalization depth** - D17 says "generalize"; unspecified whether that means extracting a core
   primitive (cleanest) or per-module reuse. Plan defaults to extraction with a documented fallback (§8-R5).
