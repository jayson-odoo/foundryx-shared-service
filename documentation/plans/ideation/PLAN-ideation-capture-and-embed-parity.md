# PLAN — Ideation Capture Quality + Embed Parity

**Status:** plan, pre-build, PRE-GRILL. Fulfils `ideation-capture-and-embed-parity-acceptance-criteria.md`.
**Classification:** MODULE (ideation) enhancement, both repos. `public`/`app_ideation` schema, no new tables.
**Cross-repo:** sorento_crm (turn service, capture) + foundryx-shared-service (intake sink, embed FE + embed-authed writes) + optional n8n (name fallback in the turn payload).
**Owner note:** grill THIS plan before code (feedback: grill-plan-before-implementing). Three
workstreams; WS-A/WS-B are small + independent, WS-C is the big one (security + scope).

## WS-A — Submitter name (AC-CAP-1..4) — SMALL

1. **Sorento turn service** (`app/services/ideation_turn_service.py`): extend `_get_contact_row`
   SELECT to include `name, first_name, last_name`; derive a display name (name → "first last" →
   None). Add `submitter_name` to the create_idea payload (alongside `submitter` = phone).
2. **n8n fallback:** the turn endpoint accepts an optional `submitter_name` from the caller; if the
   DB name is blank, use the payload value (n8n reads the Respond.io profile name). Turn service
   precedence: DB name → payload name → None.
3. **Shared-service intake** (`services/intake.py` `create_idea` + `_persist`): accept
   `submitter_name`; when resolving/creating the Contact by phone, set its `first_name` (or store
   `idea.submitter_name` directly — the serializer already prefers `idea.submitter_name`, ideas.py:61).
4. Tests: pytest — name from DB, name from payload fallback, both-blank → "Unknown", no FK violation.

## WS-B — Cumulative transcript (AC-CAP-5..8) — SMALL

1. **Sorento turn service:** accumulate each submitter turn into `session_vars.ideation.transcript`
   (append-on-turn, capped length for safety); on every create_idea call send the joined transcript
   as a NEW payload field `raw_transcript`. Keep `message_text` = current turn.
2. **Shared-service intake:** `create_idea`/`_persist` — store `raw_transcript` (when present) into
   `idea.raw_text`; fall back to `message_text` when absent (back-compat). Remove the
   overwrite-with-last-message behaviour (intake.py:288) in favour of the transcript.
3. Tests: pytest — 3-turn convo → raw_text has all 3; dedup still keyed on message_text (unchanged);
   partial/missing session_vars safe.

## WS-C — Embed = operator UI parity (AC-CAP-9..13) — BIG, the grill focus

**Decision (D3): full operator grid inside the iframe.** Two hard sub-problems:

### C1. One component, two modes (FE)
- Refactor the operator Ideas list/grid + detail into components that take a `mode: 'operator' |
  'embed'` (or a data-source prop). Embed mode = chrome-less + points its query/mutation hooks at
  the embed-authed endpoints + carries the embed token from the URL fragment.
- Delete `embed-ideas-board.tsx` / `embed-idea-detail.tsx`; `/embed/ideas` mounts the shared
  component in embed mode. Serve chrome-less (no shell/nav).

### C2. Embed-authed operator writes (BE) — SECURITY
- Today: `/embed/ideas` (GET) is read-only under the embed token; operator writes (create, status,
  reorder, vote, bulk, delete, export) are under app JWT + `require_permission`.
- Options to grill:
  - **(rec) Broaden the embed principal:** add embed-token-authed write routes under `/embed/*`
    that reuse the operator services, scoped to `principal.tenant_id` AND `principal.product_id`
    (from the connection). One dependency (`require_embed_principal`) authorizes them; every write
    asserts tenant+product scope. Pro: clean boundary, no app-JWT leakage. Con: duplicate route
    surface.
  - **(alt) Shared service + dual auth dependency:** a dependency that accepts EITHER an app JWT
    (operator) OR an embed token (scoped) and yields a common principal; mount the operator routers
    once. Pro: no route duplication. Con: subtle — a scoping miss leaks across tenants; harder to audit.
- **Product scope wiring (prereq):** put `connection.product_id` into the embed token at mint
  (`verify_and_mint`) + `EmbedTokenPrincipal`; `/embed/ideas` passes it to
  `IdeaReadService.list/board(product_id=…)` (param already added by the ideas-list fix). Every
  embed write filters by it too.

### C3. Session longevity (AC-CAP-12)
- 5-min token breaks an interactive grid. Options to grill: (a) iframe silently re-mints via the
  sorento `/embed/session` handshake on 401/expiry (host still gates who can mint); (b) a longer
  embed-session TTL with idle expiry. Rec: (a) — keeps the short token + host stays the gate.

## Phasing
- **Phase 1 (FE prototype):** WS-C1 component-with-mode against mocks; embed page renders the real
  grid chrome-less with mock data + all actions visible (disabled). Verify sizing/states via
  Playwright MCP. WS-A/WS-B need no prototype.
- **Phase 2 (test-first):** WS-A, WS-B (pytest first), then WS-C2 embed-authed writes (pytest:
  happy + cross-tenant/product denied + expired), WS-C1 wired to real endpoints (vitest), WS-C3
  refresh. Playwright: capture an idea via the turn path → name + transcript correct; iframe grid
  create/vote/reorder round-trips under the embed token, no cross-tenant leak.
- **Phase 3:** `/code-review` per repo; gated deploy (shared-service then sorento) ONLY on explicit
  permission (feedback_deploy_only_with_explicit_permission).

## Grilled decisions (user, 2026-07-20)
- **G1 — RESOLVED: truly everything.** The embed exposes ALL operator writes incl. hard-delete +
  bulk. Security posture that makes this acceptable (all mandatory): (a) sorento gates who may mint
  (host handshake); (b) every embed write is scoped to `principal.tenant_id` AND
  `principal.product_id` — cross-scope denied; (c) iframe origin allow-listed by the connection;
  (d) short 5-min token + silent re-mint (G5); (e) same validation + AUDIT as operator writes.
- **G5 — RESOLVED: silent re-mint via host.** Keep the 5-min token; the iframe re-runs the sorento
  `/embed/session` handshake on 401/expiry and retries. No long-lived embed token.
- **G2 — rec (proceed): broaden the embed principal** — dedicated embed-token-authed write routes
  under `/embed/*` reusing the operator services, each asserting tenant+product scope. Chosen over
  the dual-auth dependency for auditability (explicit scope on every route, no app-JWT path to leak).
- **G3 — rec (proceed): cap the transcript** (e.g. last N turns / M chars) and note `raw_text` now
  holds the full conversation → covered by existing idea retention/visibility; no new PII surface
  beyond what the operator already sees. Revisit if a redaction need appears.
- **G4 — rec (proceed): store `idea.submitter_name` directly** (serializer already prefers it,
  ideas.py:61); do NOT stamp the name onto the shared Contact copy (keeps vote attribution clean).
