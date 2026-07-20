# Ideation — Capture Quality + Embed Parity — Acceptance Criteria (UAC)

**Status:** contract, pre-build. Written FIRST (PRINCIPLES: UAC → plan → grill → build).
**Scope:** cross-repo — sorento (`sorento_crm`), shared-service (`foundryx-shared-service`),
optional n8n (`sorento_crm_n8n`) for the name fallback.
**Origin:** user review of the live embed (2026-07-20), three defects/asks:
1. idea submitter renders "Unknown"; 2. `raw_text` captures only the last message
("okay i confirm"), not the conversation; 3. the iframe renders a bespoke simplified
list/detail, duplicating the operator UI — should reuse ONE component.

**Locked decisions (user, 2026-07-20):**
- **D1 Submitter:** `respond_contacts.name/first_name` first; n8n Respond.io-profile-name
  fallback when the DB name is blank. NO new WhatsApp channel — identity rides the existing
  Respond.io → n8n → turn flow.
- **D2 Raw notes:** sorento accumulates the running transcript in `session_vars.ideation`
  and sends the FULL transcript (new field) → shared-service stores it as `raw_text`.
  `message_text` stays the current turn (extraction + trigram dedup unchanged).
- **D3 Embed UI:** the iframe reuses the FULL operator grid + detail (one component, embed
  mode), NOT a separate simplified list. Implies embed-authed operator writes (see WS-C).

---

## WS-A — Submitter identity (D1)

**AC-CAP-1** — When an idea is captured from WhatsApp, its **Submitter** shows the sender's
human name (not "Unknown"). **Boundary:** `respond_contacts` is a SORENTO table; the name is
resolved SORENTO-side and passed to shared-service as a plain `submitter_name` string in the
create_idea payload. Shared-service NEVER queries `respond_contacts` (stays a no-LLM sink, D20).
- **Given** a sorento `respond_contacts` row with a name for the sender, **when** the idea is
  created, **then** the Idea's submitter renders that name in list + detail + operator grid.

**AC-CAP-2** — The sorento turn service reads the sender's name (extends `_get_contact_row`
SELECT beyond phone + session_vars) and passes `submitter_name` in the create_idea payload;
shared-service `create_idea` stores that string on `idea.submitter_name` (G4 — not on the
Contact copy).

**AC-CAP-3** — Fallback: when `respond_contacts.name` is blank, n8n supplies the Respond.io
profile name in the turn payload; the turn service uses it as `submitter_name`. When BOTH are
blank, submitter falls back to "Unknown" (today's behaviour) — never errors.

**AC-CAP-4** — No new channel / no embed-signin is required for capture (regression guard):
the capture path is unchanged except for threading the name.

## WS-B — Cumulative raw notes (D2)

**AC-CAP-5** — `Idea.raw_text` contains the CUMULATIVE conversation that produced the idea
(every submitter turn in order), NOT just the finalizing message.
- **Given** a 3-turn ideate conversation ending in "okay i confirm", **when** the idea is
  created, **then** `raw_text` contains turns 1–3, not just "okay i confirm".

**AC-CAP-6** — Sorento accumulates the transcript in `session_vars.ideation` across turns and
sends the full transcript as a dedicated field (e.g. `raw_transcript`); `message_text` remains
the current turn only.

**AC-CAP-7** — Extraction + trigram dedup are unaffected (they read `message_text` = current
turn), i.e. dedup behaviour is byte-identical to today for the same turns.

**AC-CAP-8** — Restart/dropout safety: an interrupted conversation still stores whatever
transcript accumulated so far; no crash on missing/partial `session_vars`.

## WS-C — Embed = operator UI parity (D3)

**AC-CAP-9** — The iframe (`/embed/ideas` + `/embed/ideas/{id}`) renders the SAME list/grid +
detail components as the operator Ideas pages — chrome-less (no shared-service shell/nav), one
source of truth. The bespoke `embed-ideas-board.tsx` / `embed-idea-detail.tsx` are removed.

**AC-CAP-10** — The operator components accept an `embed`/read-write mode so a single component
serves both surfaces (searchable-dropdown "one component, two modes" doctrine).

**AC-CAP-11 (full-grid writes)** — Operator actions available in the iframe (Capture, status
change, drag-reprioritize, vote, bulk, export, delete) work under the EMBED token, scoped to
the connection's tenant AND product. A write outside that tenant/product is denied (never
leaks / never mutates another tenant).

**AC-CAP-12 (session longevity)** — The embed session supports interactive use beyond the
5-min token: the iframe refreshes/re-mints the embed token (or the token TTL is raised for
embed sessions) so a working grid session does not break mid-edit; an expired session still
degrades to the clean "session expired — refresh" state (no silent write failures).

**AC-CAP-13 (security)** — Embed-authed writes carry the same validation + audit as operator
writes; the signing secret / embed token are never logged; the iframe origin stays
allow-listed by the connection (AC-E-12 unchanged).

## D. Non-regression

**AC-CAP-14** — Operator (non-embed) Ideas pages are unchanged in behaviour + permissions.
**AC-CAP-15** — With the embed unconfigured, capture + operator UI are unaffected (additive).

---

## Test report keys back to AC-CAP-1 … 15 (PASS/FAIL/DEFERRED), authored in Phase 2.
