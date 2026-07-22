# 16 — AutoCount mapping transform formulas + simulators — User Acceptance Criteria

> **Status:** DRAFT — contract for `16-autocount-mapping-formulas.md`
> **Builds on:** slice 15 (mapping editor, MERGED-pending on `sprint-4/14-autocount-sorento-masters`).
> **Source:** UI feedback 2026-07-22 — the transform column should express a real formula, with
> per-formula and whole-mapping simulation.
> **Nature:** a new safe expression engine + builder UI + two simulators. No change to the sync/push
> engine or the Sorento sink contract.

## Why this slice exists

The slice-15 mapping editor shows a fixed **Transform** dropdown (Text / T-F→Boolean / Decimal…). The
operator wants to **explicitly express** a non-trivial transform as a formula — e.g.
`if(value == "T", true, false)` — not pick an opaque named transform, and to **simulate** it (a mock
value in → the transformed value out) and simulate the **whole mapping** (a mock AutoCount record in →
the whole Sorento record out) before trusting it on live data.

## Grill decisions (2026-07-22)

| # | Decision | Rationale |
|---|----------|-----------|
| G1 | Formula is an **expression over a single input `value`** | The operator's stated shape: `if(value == "T", true, false)`. Cross-field access is out of scope this slice. |
| G2 | **Safe sandboxed parser, NO eval/Jinja** | House anti-SSTI line (form computed-expr, template merge, workflow all use own safe parsers). |
| G3 | **Client + server parity**, server authoritative | Live preview in the builder; the real sync runs the server evaluator. Parity-pinned by test (the computed-expr precedent). |
| G4 | The **type/preset column stays**; presets pre-fill the formula | "Having the type here is good." A preset (Boolean, Decimal, Date, Text-passthrough) is a named starting formula the operator can then edit — so nothing is opaque. |
| G5 | Two simulators: **per-formula** (mock value→value) and **whole-mapping** (mock record→record) | Both explicitly requested. The whole-mapping sim runs the REAL MappingEngine so it proves the actual pipeline. |

---

## Group A — The formula language + engine

### AC-16-01 `[BE][FE]` A safe expression evaluator over `value`, mirrored client + server
**Given** a transform formula string
**When** it is evaluated with an input `value`
**Then** a Python evaluator (authoritative, in the sync path) and a TypeScript evaluator (the builder's
live preview) produce the **same** result
**And** neither uses `eval`/`exec`/Jinja — a hand-written parser only (anti-SSTI)
**And** a parity test pins that both agree on a matrix of expressions (the `lib/computed-expr.ts` ↔
`computed.py` precedent).

### AC-16-02 `[BE][FE]` The grammar covers the stated need and the common vendor quirks
**Given** the formula language
**Then** it supports: the variable **`value`**; string/number/boolean/null **literals**; comparisons
`== != < <= > >=`; logical `and`/`or`/`not`; **`if(cond, then, else)`**; and a small safe function set
— at least `upper/lower/trim(x)`, `contains(x, sub)`, `number(x)`, `round(x, n)`, `default(x, fb)`,
`date(x, "format")`
**And** parentheses group
**And** `if(value == "T", true, false)` evaluates to a real boolean.
> Exact function list may extend in the plan; these are the floor. Keep it SMALL and safe.

### AC-16-03 `[BE]` A formula fails CLOSED and named, never silently wrong
**Given** a formula that references an unknown name, calls an unknown function, or is malformed
**When** it is saved
**Then** it is rejected at save with a message naming the problem (422) — a bad formula never reaches
a sync
**And** at evaluation, a runtime error (e.g. `number("abc")`) fails **that field** with the field named
(the per-field-error contract), never a silent null that would blank a Sorento field.

### AC-16-04 `[BE]` A formula's output is coerced/validated to the Sorento field's type
**Given** a formula on a row targeting a typed Sorento field (`is_active` boolean, `credit_limit`
decimal)
**When** it evaluates
**Then** the result is checked against the target type (a formula feeding `is_active` must yield a
boolean) — a type mismatch is a per-field error, not a wrong value sent to Sorento.

---

## Group B — Formula builder UI

### AC-16-10 `[FE]` A transform is edited as a formula, presets pre-fill it
**Given** a mapping row in Edit
**When** the operator sets the Transform
**Then** the type/preset picker stays (Text / Boolean / Decimal / Integer / Date / **Custom**)
**And** choosing a preset fills the formula with its canonical expression (Text → `value`, Boolean →
`if(value == "T", true, false)`, Decimal → `number(value)`, Date → `date(value, "yyyy/MM/dd HH:mm:ss")`)
which the operator can then edit
**And** a direct pass-through (`value`) needs no visible formula clutter — the simple `AccNo → Code`
row stays simple (AC: a passthrough row shows just its type, the formula affordance is secondary).

### AC-16-11 `[FE]` The formula builder is discoverable and safe to use
**Given** a row whose transform is a formula
**When** the operator opens the builder (a "Build"/edit affordance on the row)
**Then** it offers the `value` variable, operator/function buttons, and inserts at the caret (reuse the
form-engine `formula-builder` shell where it fits)
**And** it live-validates (parse errors shown inline) and never lets an invalid formula be saved
(front gate + the AC-16-03 server gate).

### AC-16-12 `[FE]` Foolproof — only valid, contextual function reference (not screen clutter)
**Given** the builder
**Then** dropdowns are searchable `SearchSelect`s and it is read-only until Edit
**And** it carries no procedural how-to copy on the main surface — BUT per-function **reference**
(signature, arguments, description) is allowed and required (AC-16-15): that is contextual API
documentation for the selected function, the sanctioned "one-line description" kind, not sprinkled
instructional prose.

### AC-16-13 `[FE]` Functions are grouped by data type + searchable (Qrvey model)
**Given** the formula builder's function catalog
**When** the operator browses it
**Then** functions are grouped by data type — **String**, **Number**, **Boolean**, **Date**, **Logical**
— selectable by a category picker (like Qrvey's "All ▾") AND searchable by name
**And** each function is inserted at the caret (an "Insert"/"Add to formula" action), never hand-typed
from memory
**And** the `value` input and any available columns are listed with their type, so the operator sees
what they can reference.

### AC-16-14 `[FE][BE]` A dedicated DATE-FORMAT tool: explicit input + output format
**Given** a date transform
**When** the operator configures it
**Then** the builder offers a **date-format tool** where they specify the **input date format**
(how AutoCount sends it, e.g. `yyyy/MM/dd HH:mm:ss`) AND the **output date format** (what Sorento
should receive, e.g. ISO `yyyy-MM-ddTHH:mm:ssZ`) — chosen from a **fixed, documented token
vocabulary**, not a free-form string
**And** the SAME token vocabulary is parsed identically client and server (this is how the client/
server date parity is guaranteed — a fixed token set, not a general date library)
**And** the tool previews a sample date through the chosen input→output formats live.
> This supersedes a free-form `date(x, "format")` string — the structured tool is both more usable and
> the thing that makes date parity (AC-16-01) provable.

### AC-16-15 `[FE]` The builder explains each function (arguments, description)
**Given** the operator selects a function in the catalog
**When** it is shown
**Then** a reference panel shows its **signature**, each **argument** (name + what it expects), a
one-line **description**, and an example (e.g. `if(condition, then, else)` — "returns `then` when
`condition` is true, else `else`")
**And** the header states the accepted value formats concisely (like Qrvey's "Date values use
`yyyy/MM/dd`…"), so the operator can author a correct formula without leaving the builder.

---

## Group C — Per-formula simulation

### AC-16-20 `[FE]` A formula can be tested with a mock value, live
**Given** the formula builder for a row
**When** the operator types a mock input `value`
**Then** the transformed output is shown live (client evaluator) as they type
**And** an error in the formula/value shows the failure, not a blank.

### AC-16-21 `[BE][FE]` The server confirms the same result (parity, authoritative)
**Given** a mock value + formula
**When** the operator asks the server (or on save-preview)
**Then** a backend evaluation returns the same output the client showed (AC-16-01 parity) — so the
operator trusts that what they simulated is what the sync will do.

---

## Group D — Whole-mapping simulation

### AC-16-30 `[BE][FE]` A mock AutoCount record maps to a whole Sorento record
**Given** the mapping editor for an entity
**When** the operator provides a **mock AutoCount record** (JSON, or pre-filled from a real sample) and
runs the simulation
**Then** the WHOLE mapping runs through the **real MappingEngine** and returns the resulting **Sorento
record** (every mapped field) + per-field results
**And** a field whose formula/coercion failed is shown as a per-field error (not omitted silently), so
the operator sees exactly what a real sync of that record would produce or reject.

### AC-16-31 `[FE]` The simulation is legible as record-in → record-out
**Given** the whole-mapping simulation result
**When** it renders
**Then** it shows the AutoCount input beside the Sorento output (the two "whole" shapes the operator
asked for), with the value-changing/failing fields legible
**And** it writes NOTHING to Sorento — it is a pure transform preview (distinct from the slice-14
dry-run, which asks Sorento what a push would do).

### AC-16-32 `[BE]` The simulator can seed a real sample (optional, if cheap)
**Given** a connected company
**When** the operator wants a realistic mock
**Then** the simulator may offer to pull ONE real AutoCount record of the entity as the mock input
(read-only fetch), so the operator isn't hand-authoring vendor JSON.
> Nice-to-have; if it complicates the slice, a hand-entered/pasted mock record satisfies AC-16-30.

---

## Out of scope
- Cross-field formulas (whole-record access) — G1, a later slice if wanted.
- Changing the canonical→Sorento contract or the sync/push engine.
- Formulas on the sink (canonical→Sorento) leg — transforms are the AutoCount→canonical leg only.

## Tests
- `[BE]` formula evaluator matrix (incl. `if`, fail-closed, type coercion), save-gate 422s, whole-mapping
  simulate endpoint (real engine, per-field errors, writes nothing), parity harness.
- `[FE]` formula parser mirror (parity with a shared matrix), builder (preset pre-fill, inline validate,
  can't-save-invalid), per-formula live sim, whole-mapping sim render.
- `[E2E]` edit a T/F formula, simulate a value, simulate a whole record, save, re-sync.
- Live-verify both viewports.
