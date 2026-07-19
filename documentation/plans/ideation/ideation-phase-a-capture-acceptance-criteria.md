# Ideation Phase A — Capture · Acceptance Criteria (shared-service)

**Contract this plan must satisfy.** The independently-verifiable Given/When/Then items for the
**shared-service portion** of Phase A ("Capture") of the Ideation → Delivery program. Each item has a
stable id `AC-A-<NN>`, is grouped by area, and is tagged `[BE]` / `[FE]` / `[E2E]` / `[T]`. The Phase-2
test report keys back to these ids (PASS/FAIL/DEFERRED).

**Spine reference (authoritative):** `PLAN-ideation-to-delivery-program.md` §2 (D1–D21, incl. D20 no-LLM + D21 respond.io cron sync), §3 (entities),
§5 (Cross-Repo Contracts). Any contract wording below is copied from §5 and **must stay byte-for-byte**;
if it changes it changes in the program master first.

**Scope reminder — shared-service ONLY.** sorento's `ideate` intent + iframe host and n8n's `ideate`
routing are separate per-repo plans (§5.2 / §5.5). The items here stop at the shared-service boundary:
the `create_idea` HTTP endpoint, the Product/Idea entities, the IntakeDefinition registry, respond.io
workspace↔Product binding + **cron-synced own contact copies matched by phone** (D21), dedup via
**`pg_trgm` text-similarity** (D10/D20), the triage board, the embeddable board/detail, and submitter
notifications. Delivery (AgentRunner, Mac Mini daemon, GitHub) is Phase C — out of scope.

**No LLM in shared-service (D20).** Shared-service is **data + UI + relay only** — it runs no LLM, no
assistant port, no embedding pipeline. `create_idea` is deterministic (validate + `pg_trgm` dedup +
persist); field-extraction happens in sorento's brain; the BR→FR grill (Phase B) relays to Claude Code
on the Mac Mini. Any AC below is written against that constraint.

---

## Area 0 — Ideation Service scaffold (App-Store module)

### AC-A-01 — module manifest + guard [BE][T]
- **Given** the repo, **when** the app boots, **then** `service_backend/modules/ideation/manifest.json`
  is discovered by `app/module_loader.discover_manifests`, declares `module_name:"ideation"`,
  `schema:"app_ideation"`, `alembic_version_table:"alembic_version_ideation"`, `requires:["omnichannel"]`
  (the intake rides omnichannel contacts + `messaging.send`), and its routers are mounted with the
  `require_module("ideation")` gate injected by `load_modules` (public routers excepted, per AC-A-30).

### AC-A-02 — global install idempotent [BE][T]
- **Given** `bootstrap_modules()`, **when** it runs (twice), **then** `ideation.bootstrap.install`
  creates schema `app_ideation` + all module tables + syncs the permissions CSV, is idempotent (second
  run is a no-op), and the module appears once in the `modules` catalog.

### AC-A-03 — per-tenant install/uninstall [BE][T]
- **Given** a tenant installs Ideation via the App Store, **when** `install_tenant` runs, **then** it
  seeds the tenant's Idea status set + the `ideation` IntakeDefinition binding and grants the module
  permission keys to the tenant Admin role; **when** `uninstall_tenant` runs, **then** every
  `app_ideation.*` row for that tenant is wiped (reverse-dependency order) while core `public.products`,
  omnichannel contacts, and other tenants' rows are untouched.

### AC-A-04 — reverse-dependency guard [BE][T]
- **Given** Ideation `requires:["omnichannel"]`, **when** an operator tries to uninstall/deactivate
  omnichannel while Ideation is active, **then** the module platform blocks it with the standard
  reverse-dependency error (Ideation must go first).

---

## Area 1 — Product (unified core entity) + software kind + delivery config (D3, §3)

> **REVISED 2026-07-19 (owner decision — supersedes the original "separate entity").** The program
> Product is **combined into the core `public.products` catalog**, not a separate `app_ideation.products`
> table. There is now **one Product entity** with `kind ∈ {goods, service, software}` (core seeds
> `good`/`service`; ideation **registers the `software` kind** at install via the product-kind registry,
> exactly like EMS adds its kinds). Delivery-target attributes that only a software product needs
> (`product_domain_base`, adapters) live in an ideation **extension table** keyed 1:1 to the core product,
> so the catalog table is not overloaded but there is a single product identity. Ideas carry a normal
> **cross-schema FK into `public.products`**. (Reverses old D-A2; see PLAN §Decision log.)

### AC-A-05 — one Product entity, software kind registered by ideation [BE][T]
- **Given** the core `public.products` catalog (`kind` = product-kind registry key), **when** the ideation
  module installs, **then** it **registers a `software` product kind** (`register_product_kind`) so the
  active kind set is `goods|service|software` (visible only while ideation is installed; core `good` covers
  goods), and the core `/products/kinds` endpoint returns it. No separate `app_ideation.products` table is
  created; the program Product IS the core catalog Product.

### AC-A-06 — software delivery config + link origin [BE][T]
- **Given** a software Product, **when** its delivery config is set, **then** `product_domain_base` (a
  validated absolute origin, e.g. `https://fe-sorento.foundryx.my`) is stored in the ideation extension
  table `app_ideation.product_delivery` (`product_id` FK `public.products`, unique per product) and used
  verbatim to mint product-domain links (AC-A-38). One Product per Idea (`Idea.product_id` NOT NULL, FK
  `public.products`).

### AC-A-07 — polymorphic adapters registry [BE][T]
- **Given** a software Product, **when** adapters are declared, **then** they are stored as
  `app_ideation.product_adapters` rows `(product_id FK public.products, kind, config_json, credentials_ref?)`
  with `kind ∈ {embed_connection, github, agent_runner, deploy}`; a code-side adapter-kind registry validates
  `kind` (mirrors the product-kind / status-entity registry pattern). **Phase A wires only
  `embed_connection`**; `github`/`agent_runner`/`deploy` kinds are registered-but-dormant (Phase C).

### AC-A-08 — Product CRUD + delivery-config API [BE][FE][T]
- **Given** a Maintainer, **when** they create/edit/list Products, **then** product CRUD reuses the **core
  catalog product API** (`/products`, `products.*` permissions) with `kind` validated against the active
  registry (incl. `software`); a software product's `product_domain_base`/adapters are set via an ideation
  delivery-config route (`ideation.products.manage`), and the ideation UI lists products (core list) with
  their delivery config. `kind`/`product_domain_base` are validated.

---

## Area 2 — Idea entity + lifecycle (D16, §3)

### AC-A-09 — Idea entity fields [BE][T]
- **Given** the Idea entity, **when** modelled as `app_ideation.ideas`, **then** it carries
  `id, product_id (cross-schema FK public.products), status, problem, raw_text, source, submitter_contact_id,
  attachments[], upvotes, created_at, updated_at` per §3, plus `intake_definition_key` and a
  `captured_json` holding the form_engine answers. **No `embedding` column** — dedup is `pg_trgm`
  text-similarity (Area 6), and shared-service runs no embedding model (D20).

### AC-A-10 — Idea lifecycle on the status engine [BE][T]
- **Given** the Idea statuses `draft → captured → triaged → linked → building → delivered → closed`
  (+ `duplicate`, `rejected`), **when** the module boots, **then** Idea registers as a **tenant-owned
  status entity** (`register_status_entity(entity_type="idea", …)`) with `count_records`/`migrate_records`,
  the initial status is `draft`, and transitions go through `status_machine.transition` (no key-branching;
  triage columns map to statuses via traits/derived where needed).

### AC-A-11 — draft is the durable system-of-record (D8) [BE][T]
- **Given** the intake creates a draft Idea on turn 1 (AC-A-19), **when** the conversation is interrupted
  and later resumed by `draft_id`, **then** the same draft row is enriched (never duplicated) and its
  status advances `draft → captured` only when the completion rule is satisfied.

### AC-A-12 — Idea detail read API [BE][FE][T]
- **Given** an idea id, **when** `GET /ideation/ideas/{id}` is called, **then** it returns the Idea with
  its product, submitter (human-readable, no raw UUID in the UI), captured fields, attachments, upvote
  count, status, and cluster/BR linkage placeholders — every section always rendered with an empty state.

---

## Area 3 — IntakeDefinition registry (D18, form_engine-backed)

### AC-A-13 — generic Conversational-Intake definition [BE][T]
- **Given** the generic Conversational-Intake engine, **when** the module boots, **then** an
  `IntakeDefinition` registry holds entries `{key, target_schema (form_engine FormDocument),
  completion_rule, on_complete_sink, agent_role}`; **ideation is exactly one definition** with
  `key="ideation"`, `target_schema` = the Idea capture FormDocument, `on_complete_sink` = create/enrich
  an Idea. Adding a future "form over WhatsApp" flow is a **new registry entry, no new conversation code**.

### AC-A-14 — target_schema is a valid form_engine document [BE][T]
- **Given** the ideation `target_schema`, **when** validated, **then** it passes
  `app.form_engine.schemas.validate_form_doc` (Page→Section→Field, stable answer keys), and its input
  fields are the intake's captured/missing surface: `problem` (problem statement),
  `proposed_solution`, `impact`, `department` (all required). (Revised from the earlier
  `problem/module/who/impact` set — business submitters don't know the module, and the
  submitter identifies who.)

### AC-A-15 — completion_rule computes captured/missing [BE][T]
- **Given** a partial answer set, **when** the completion rule is evaluated, **then** it returns
  `captured` (answered keys→values) and `missing` (required keys not yet answered) deterministically over
  the `target_schema`; `missing == []` ⇒ the intake is `complete`.

### AC-A-16 — on_complete_sink is the ONLY promotion path [BE][T]
- **Given** `status="complete"`, **when** the sink fires, **then** it transitions the draft Idea to
  `captured` and mints the product-domain link; the sink is idempotent (re-firing on the same draft does
  not create a second Idea and does not double-advance status).

---

## Area 4 — `create_idea` HTTP endpoint + Conversational-Intake engine (D7/D20, §5.1 — CANONICAL)

> §5.1 wording is authoritative and copied verbatim; the endpoint is the **ONLY** place intake logic lives
> (sorento/n8n never re-implement it). `product_id` is derived by shared-service from the
> workspace↔Product binding, **never from the human**. `create_idea` runs **no LLM** (D20): it is a
> deterministic validate-against-schema + `pg_trgm` dedup + persist path — field-extraction already
> happened in sorento's brain. It is an authenticated **HTTP endpoint** (reconciled §8-R3), not an MCP
> tool (shared-service has no MCP write server).

### AC-A-17 — endpoint input contract [BE][T]
- **Given** `create_idea`, **when** called, **then** it accepts
  `{ product_id, submitter_contact_id, message_text, audio_attachment_ref?, draft_id?, fields?, remove?, confirm? }`
  (D-CONFIRM: `fields` = sorento-brain-extracted answer updates, `remove` = keys to clear, `confirm` = explicit
  user confirmation bool); `product_id` is
  resolved/validated against the workspace↔Product binding (AC-A-27) — a caller-supplied `product_id` that
  does not match the binding is rejected; **`submitter_contact_id` is passed as a phone number (E.164)**
  which shared-service **matches** to its own cron-synced respond.io contact copy (D21, AC-A-28), never a
  sorento row id it blindly trusts; `draft_id` is absent on the first `ideate` turn and present on
  continuation.

### AC-A-18 — tool output contract [BE][T]
- **Given** any call, **when** it returns, **then** the output is exactly
  `{ draft_id, status: "collecting"|"review"|"complete"|"duplicate", captured: {...}, missing: ["field", ...],
  reply_text, link?, duplicate_of? }` — field names byte-for-byte per §5.1 (D-CONFIRM adds `review`).
  `reply_text` is composed **deterministically** (template over `captured` + schema labels, no LLM):
  collecting = "captured so far + still missing"; review = full-summary + confirm/revise ask; complete = link.

### AC-A-18b — confirmation gate: review before capture (D-CONFIRM) [BE][T]
- **Given** all required fields are captured (`missing == []`) but `confirm != true`, **when** `create_idea`
  returns, **then** `status="review"` — the Idea **stays `draft`**, `reply_text` echoes the full captured
  summary and asks the user to confirm or say what to change; it **NEVER** auto-advances to `captured`. This
  holds **even when the first turn is fully complete** (a one-shot complete input still returns `review` first).

### AC-A-18c — revision loop merges then re-reviews (D-CONFIRM) [BE][T]
- **Given** a draft in `review`, **when** a turn carries `fields` (add/change) and/or `remove` (clear),
  **then** `create_idea` merges them into `captured_json` deterministically, recomputes `missing`, and
  re-returns `review` (re-echoing the updated summary) — or `collecting` if a now-`remove`d field was required.
  The loop repeats across ≥3 turns until an explicit `confirm=true`; a `fields` re-send with identical values
  is idempotent.

### AC-A-19 — draft on turn 1 [BE][T]
- **Given** no `draft_id`, **when** `create_idea` is called, **then** it **creates a draft Idea**
  (status `draft`) and starts collection, applies `message_text` to the Idea's form_engine schema, runs
  dup-check, and computes captured/missing per the `completion_rule`.

### AC-A-20 — completion → captured + link (ONLY on explicit confirm) [BE][T]
- **Given** the completion rule is satisfied **and `confirm == true`** (D-CONFIRM), **when** the tool returns,
  **then** `status="complete"`, the Idea moves `draft → captured`, `link` is the **product-domain** deep link
  (§5.3, AC-A-38), and the caller is expected to clear `session_vars.ideation` (contract note; enforced
  sorento-side). Without `confirm`, a complete-but-unconfirmed draft returns `review` (AC-A-18b), not `complete`.
  `confirm=true` on an already-`captured` idea is an idempotent no-op returning `complete` + `link`.

### AC-A-21 — duplicate → upvote (D10) [BE][T]
- **Given** the incoming idea is a high **text-similarity** match to an existing Idea (`pg_trgm`, AC-A-31),
  **when** the endpoint returns, **then** `status="duplicate"`, `duplicate_of` = the existing idea id, the
  existing Idea's `upvotes` is incremented (once per submitter, idempotent), and `reply_text` relays
  "similar to … upvoted".

### AC-A-22 — idempotency on draft_id [BE][T]
- **Given** repeated calls with the same `draft_id`, **when** re-invoked, **then** they are safe — they
  enrich the existing draft, never duplicate it, and never regress captured fields already collected.

### AC-A-23 — interrupt/resume correctness (D8) [BE][E2E]
- **Given** a draft mid-collection and an unrelated turn in between, **when** the next `ideate` turn
  arrives with the stored `draft_id`, **then** collection resumes on the same draft with prior `captured`
  intact; the draft is never cleared/corrupted by an interleaved non-ideate turn.

### AC-A-24 — voice reaches the tool as text + attachment (D9) [BE][T]
- **Given** a voice note transcribed at n8n, **when** `create_idea` receives `message_text` (transcript)
  + `audio_attachment_ref`, **then** the transcript feeds the schema and the audio is linked to the Idea's
  `attachments[]` (the tool does not transcribe — that is n8n's job).

### AC-A-25 — endpoint transport / auth (§8-R3) [BE][T]
- **Given** the endpoint is exposed for the sorento brain to call per turn, **then** it is served as an
  authenticated shared-service **HTTP endpoint** (`POST /ideation/intake/create-idea`,
  integration/workspace-key auth, uniform `{error:{code,message}}` envelope), called server-to-server —
  **not** an MCP tool (shared-service has no MCP write server; `sorento_crm_mcp` is read-only). The
  sorento side wraps it behind its own `POST /api/v1/external/ideation/turn` (§5.1); no intake logic is
  re-implemented outside this endpoint (D7).

---

## Area 5 — respond.io workspace↔Product binding + cron-synced contact copies (D21)

### AC-A-26 — respond.io connection registered [BE][T]
- **Given** respond.io as the 2nd integration after omnichannel, **when** an operator configures it,
  **then** a core `Connection` row `provider="respond_io"` (secrets in `credentials_json`, Fernet) is
  created via the integration framework and appears in the connections UI.

### AC-A-27 — workspace↔Product binding derives product_id [BE][T]
- **Given** a respond.io workspace bound to a Product, **when** an intake turn arrives, **then**
  shared-service derives `product_id` from the **workspace↔Product binding** (`app_ideation.product_bindings`
  `(product_id, connection_id, external_workspace_id)`), never from the human — this is the input to
  `create_idea` (AC-A-17).

### AC-A-28 — cron-synced own contact copies + match by phone (D21) [BE][T]
- **Given** shared-service keeps **its own copies** of the respond.io contacts (mirroring sorento's sync),
  **when** a scheduled cron job runs, **then** it pulls contacts from the **respond.io API** on the bound
  workspace's connection and upserts them into shared-service's own contact store (omnichannel Contact +
  `ContactChannelIdentity`, keyed by phone E.164) — separate copies kept fresh, not a ref handed over by
  sorento. **When** `create_idea` receives the inbound submitter phone (E.164), **then** it **matches** it
  to an existing copy; an **unmatched phone** triggers an on-the-fly create/enrich of the contact copy from
  the respond.io API, so `submitter_contact_id` always resolves to a real, shared-service-owned contact.

### AC-A-29 — binding uniqueness + tenant scope [BE][T]
- **Given** the binding table, **when** rows exist, **then** `(connection_id, external_workspace_id)` is
  unique (one workspace → one Product), all bindings are tenant-scoped, and an unbound workspace turn is
  rejected cleanly (no silent default Product).

---

## Area 6 — Dedup via `pg_trgm` text-similarity (D10/D20)

### AC-A-30 — pg_trgm provisioned + trigram index [BE][T]
- **Given** dedup must run with **no LLM/embedding model** in shared-service (D20), **when** the Ideation
  migration runs on Postgres, **then** `CREATE EXTENSION IF NOT EXISTS pg_trgm` succeeds and a **GIN
  trigram index** (`gin_trgm_ops`) is created on the Idea's dedup text (e.g. `problem` / normalized
  `raw_text`) scoped for `(tenant_id, product_id)` filtering. There is **no `vector` extension and no
  `embedding` column**. The migration is a no-op / gracefully skipped on the SQLite test engine.

### AC-A-31 — text-similarity high-match dedup [BE][T]
- **Given** a new/enriched Idea's problem text, **when** compared via `pg_trgm` similarity
  (`similarity()` / `%` operator over the same tenant+product), **then** a match above the configured
  similarity threshold yields `status="duplicate"` + `duplicate_of` (AC-A-21); below threshold the Idea
  proceeds. The similarity threshold + per-product scope prevent cross-product false positives.

### AC-A-32 — dedup is deterministic + inline, source-of-truth is OLTP [BE][T]
- **Given** the dedup check runs **inline in the deterministic `create_idea` path** (no embedding worker,
  no LLM — D20), **when** it executes, **then** it is a single `pg_trgm` query against existing OLTP Idea
  rows (the source of truth); no derived vector artifact is stored, and the Idea row is fully valid without
  any secondary index state. Semantic (embedding-based) dedup, if ever wanted, is delegated to Claude
  Code/sorento — never run in shared-service (D10/D20).

---

## Area 7 — Triage board (Canny) + AI clustering (D16)

### AC-A-33 — Canny-style triage board [FE][E2E]
- **Given** a Triager, **when** they open the Ideation triage board, **then** ideas render as cards in
  columns keyed by Idea status (e.g. Captured / Triaged / Linked / Rejected), each card shows problem +
  product + submitter (human-readable) + upvotes, and dragging a card transitions the Idea's status via the
  status API (server-authoritative; illegal transitions are refused).

### AC-A-34 — suggested clustering, human decides [BE][FE][T]
- **Given** captured ideas, **when** the board requests suggestions, **then** shared-service returns
  **suggested clusters** (grouping text-similar ideas via the same `pg_trgm` similarity used for dedup —
  **no LLM/embedding**, D20) as *proposals only*; a human Triager accepts/rejects a cluster — the system
  never auto-merges or auto-promotes (D5/D16).

### AC-A-35 — cluster persistence + linkage [BE][T]
- **Given** an accepted cluster, **when** saved, **then** an `app_ideation.idea_clusters` row +
  membership links the ideas, and this is the seam BR promotion (Phase B) consumes; Idea status can move to
  `linked`. Rejecting a suggestion leaves ideas untouched.

---

## Area 8 — Roles & permissions (D16)

### AC-A-36 — Submitter / Triager / Maintainer permissions [BE][T]
- **Given** the module permissions CSV, **when** synced, **then** it declares the ideation permission keys
  mapping to the three roles: **Submitter** (create ideas via intake + view/upvote own), **Triager**
  (triage board, clustering, status transitions), **Maintainer** (Products, bindings, intake defs, all of
  Triager). Keys are granted per role by the App Store on install; the embed board honours a Submitter-scoped
  token (AC-A-40).

### AC-A-37 — permission enforcement server-side [BE][T]
- **Given** each ideation route, **when** called without the required key (native) or capability (embed),
  **then** it returns 403 — the backend is the boundary, regardless of what the UI shows.

---

## Area 9 — Embeddable idea board + detail (D17, §5.3 — generalize omnichannel embed)

### AC-A-38 — product-domain link minting (§5.3) [BE][T]
- **Given** a captured Idea, **when** the link is minted, **then** it is
  `{product_domain_base}/ideas/{idea_id}` (e.g. `https://fe-sorento.foundryx.my/ideas/123`) — **never a
  shared-service URL** — byte-for-byte per §5.3.

### AC-A-39 — generalized embed framework [BE][T]
- **Given** the omnichannel embed framework (assertion→token, `parentOrigin`/`allowedOrigins`,
  `frame-policy`, single-use `jti`, `typ="embed"`), **when** Ideation embeds its board/detail, **then** it
  reuses that framework generalized to a **new provider** (`provider="ideation_shared"`, audience
  `"ideation-embed"`) over the same `Connection` + jti-ledger + `/embed/session` exchange semantics — the
  assertion is the credential, `parentOrigin ∈ connection.allowedOrigins`, and rotating the embedSecret
  invalidates outstanding assertions. (Extraction of a shared core embed primitive vs. per-module reuse is
  a plan decision — see PLAN §Decision log.)

### AC-A-40 — embed board + detail routes [FE][E2E]
- **Given** `{shared_service}/embed/ideas/{id}` (detail) and `{shared_service}/embed/ideas` (board),
  **when** loaded inside the sorento iframe, **then** they render chromeless (no app shell, no login
  redirect), obtain the token via the postMessage handshake (assertion never in the URL), and enforce the
  token scope/caps server-side (a Submitter-scoped token cannot triage).

### AC-A-41 — frame-ancestors clickjacking guard [BE][E2E]
- **Given** the ideation embed routes, **when** served, **then** the response carries
  `Content-Security-Policy: frame-ancestors <connection.allowedOrigins>` via the same `/embed/frame-policy`
  mechanism; embedding from a non-allowed origin is browser-blocked.

### AC-A-42 — product linkage = embed connection [BE][T]
- **Given** a software Product's `embed_connection` adapter (AC-A-07), **when** configured, **then** it
  carries the connection's `allowedOrigins` + signing (`embedSecret`) + `product_domain_base`, so the
  product-domain link (AC-A-38) and the embed exchange (AC-A-39) are two ends of the same binding.

---

## Area 10 — Notifications (submitter ← milestones, via omnichannel/WhatsApp)

### AC-A-43 — submitter milestone notifications [BE][T]
- **Given** a submitter's Idea reaches a milestone status (`captured`, `triaged`/`linked`, later
  `delivered`), **when** the transition fires, **then** shared-service sends the submitter a WhatsApp
  message through the omnichannel `messaging.send@1` capability (resolved via `resolve_capability`), keyed
  to `submitter_contact_id`; content is a template/merge-field message, not free text.

### AC-A-44 — notifications are milestone-only + idempotent [BE][T]
- **Given** the same milestone re-entered or a rapid double transition, **when** notifications fire,
  **then** each milestone notifies at most once per Idea (idempotent guard); non-milestone status churn
  does not notify (D12 milestone-only).

---

## Cross-cutting

### AC-A-45 — public router exceptions correct [BE][T]
- **Given** the manifest, **when** routers mount, **then** only the endpoints with no authenticated user
  to resolve a tenant from are `"public": true` — `/embed/session`, the embed read routes, and the
  intake/tool endpoint (integration-key authed) — every operator/triage/product route stays behind
  `require_module("ideation")` + permission.

### AC-A-46 — Definition-of-Done gate [BE][FE][E2E]
- No unswapped mock; the `create_idea` output matches §5.1 byte-for-byte; `product_id` is proven derived
  from the binding (a spoofed human-supplied product is refused); dedup proven with a real duplicate;
  interrupt/resume proven; the embed board renders inside a real sorento-origin iframe at ~375px and
  ~1280px on a freshly rebuilt frontend; no regression to omnichannel (embed, gateway, inbox) or core
  catalog suites; the test report keys every AC-A-NN to PASS/FAIL/DEFERRED.

### AC-A-47 — E2E: WhatsApp → captured Idea → board → embed [E2E]
- **Given** a test harness posing as the sorento brain, **when** it calls `create_idea` across turns
  (draft on turn 1 → collecting → complete), **then** a real Idea is captured, a duplicate second idea
  upvotes the first, the Idea appears on the triage board and can be dragged to `triaged`, the minted link
  is `{product_domain_base}/ideas/{id}`, and mounting `/embed/ideas/{id}` with a validly-signed assertion
  renders the detail and refuses a wrong-origin embed — real interactions, report keyed to these ACs.
