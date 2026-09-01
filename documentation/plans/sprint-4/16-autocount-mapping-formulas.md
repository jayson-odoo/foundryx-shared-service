# 16 - AutoCount mapping transform formulas + simulators

> **Contract:** `16-autocount-mapping-formulas-acceptance-criteria.md` (governs).
> **Builds on:** slice 15 mapping editor. Same branch/feature.
> **Nature:** a safe expression engine (client+server), a formula builder, two simulators. The
> sync/push engine and Sorento sink are untouched - this only enriches the AutoCount→canonical
> transform leg.

## 1. The formula language (safe, over a single `value`)

A hand-written recursive-descent parser + evaluator. NO `eval`/`exec`/Jinja (anti-SSTI, house line).
Mirrored: `modules/autocount/formula.py` (authoritative, runs in the sync path) and
`lib/autocount-formula.ts` (the builder's live preview), parity-pinned by a shared golden matrix (the
`computed.py` ↔ `lib/computed-expr.ts` precedent).

Grammar (EBNF-ish):
```
expr    := or
or      := and ( "or" and )*
and     := not ( "and" not )*
not     := "not" not | comparison
comparison := add ( ("=="|"!="|"<"|"<="|">"|">=") add )?
add     := mul ( ("+"|"-") mul )*          # numeric + string concat via "&"
mul     := unary ( ("*"|"/") unary )*
unary   := "-" unary | call
call    := primary | IDENT "(" args? ")"    # function call
primary := NUMBER | STRING | "true" | "false" | "null" | "value" | "(" expr ")"
```
- Input variable: **`value`** (the raw AutoCount source value - usually a string; the vendor sends
  `"T"`, `"30000.0"`, `"2026/03/18 16:03:21"`).
- Functions (the floor - small + safe), **catalogued by data type** (AC-16-13):
  - **String**: `upper(x)`, `lower(x)`, `trim(x)`, `contains(x, sub)`, `replace(x, a, b)`, `concat(...)`
  - **Number**: `number(x)`, `round(x, n)`, `abs(x)`
  - **Boolean**: `bool(x)`, the comparisons `== != < <= > >=`
  - **Date**: `parseDate(x, inFmt)`, `formatDate(x, outFmt)` - driven by the date-format tool below
  - **Logical**: `if(cond, then, else)`, `and`/`or`/`not`, `default(x, fb)`
  Each function carries metadata (signature, arg names, description, example) so the builder can show
  reference (AC-16-15). String concat via `&`.
- **Dates use a FIXED token vocabulary, not a general date library** (AC-16-14, and the resolution of
  the parity risk): a small documented token set (`yyyy MM dd HH mm ss`, ISO `yyyy-MM-ddTHH:mm:ssZ`)
  parsed by the SAME hand-written formatter in `formula.py` and `lib/autocount-formula.ts`. The
  operator picks an **input format** and an **output format** in the date-format tool; there is no
  free-form date string to drift between client and server. This is why date parity is provable.
- Depth/length capped (reuse `MAX_GROUP_DEPTH` convention); a parse error is a named failure.
- **Fail closed** (AC-16-03): unknown name/function → parse-time 422; runtime error (`number("abc")`)
  → per-field error naming the field, never a silent null.
- **Output typing** (AC-16-04): the row's target Sorento field has a type; the evaluated result is
  coerced/validated to it (boolean field ⇒ must be bool). Reuse the existing coercion the transforms
  already do; a mismatch is a per-field error.

Presets are canonical formulas (AC-16-10): `Text → value`, `Boolean → if(value == "T", true, false)`,
`Decimal → number(value)`, `Integer → round(number(value), 0)`, `Date → date(value, "yyyy/MM/dd HH:mm:ss")`.
Picking a preset fills the formula; the operator edits from there. The existing named transforms
(`string`/`t_f_bool`/`slash_datetime`/`decimal`) map onto these presets so **existing mappings keep
working unchanged** (back-compat: a row with a named transform and no formula behaves exactly as today).

## 2. Data + integration

- **`ac_field_mapping.formula`** - new nullable text column. NULL ⇒ use the named `transform` (today's
  behavior). Set ⇒ the formula is authoritative. Per-module Alembic migration, existence-checked
  (`ADD COLUMN IF NOT EXISTS`; revision ≤32 chars; the module's create_all-before-migrate lesson).
  Existing rows: NULL formula, unchanged. `update_tenant`/seed unaffected (seed still writes named
  transforms; the formula is an operator addition).
- **MappingEngine** (`mapping.py`): when a row has a formula, evaluate it via `formula.py` instead of
  the named transform; else the current path. One branch, in the existing coerce step. The per-field
  error plumbing already exists (FieldError) - reuse it.
- **Mapping GET/PUT** (slice 15): each row gains `formula` (nullable). PUT validates the formula
  (parse + save-gate 422, AC-16-03); the accepted-target/transform guards stay.

## 3. Backend endpoints

- **`POST .../entities/{entityType}/mapping/simulate`** (AC-16-30) - body `{ record: {..mock AutoCount..},
  rows?: [..override rows..] }`. Runs the REAL MappingEngine over the mock record (using the saved rows,
  or the supplied draft rows so the operator can simulate UNSAVED edits) → returns the projected Sorento
  payload + per-field results (ok/value/error). Writes NOTHING. Perm `autocount.companies.manage`.
- **`POST .../mapping/test-formula`** (AC-16-21) - body `{ formula, value }` → `{ ok, output, error }`.
  Server-authoritative single-formula eval, so the builder can confirm parity beyond the live client
  preview. (The client evaluates live for AC-16-20; this is the trust/parity check.)
- **`GET .../mapping/sample`** (AC-16-32, optional) - pull ONE real AutoCount record of the entity
  (read-only fetch through the existing client) to seed the whole-mapping simulator. If it complicates
  the slice, drop it - a pasted/hand-entered mock satisfies AC-16-30.

## 4. Frontend

- **Formula in the row** (`mapping-table.tsx`): the Transform cell keeps the preset `SearchSelect` +
  gains a **Build** affordance (opens the formula builder) when the transform is a formula; a
  passthrough row stays visually simple (AC-16-10).
- **Formula builder** (`components/platform/autocount/formula-builder` or reuse/generalize the
  form-engine `formula-builder.tsx`) - modelled on the Qrvey layout the operator referenced:
  - a formula text area with **Formula | Testing** tabs;
  - a **function catalog grouped by data type** (category picker String/Number/Boolean/Date/Logical +
    search), each inserted at the caret (AC-16-13); the `value` input + available columns listed with
    their type;
  - a **function reference panel** (AC-16-15): selecting a function shows its signature, arguments,
    one-line description + example; the header states accepted value/date formats concisely;
  - the **Testing** tab = the per-formula simulator: a mock-value input with **live output**
    (AC-16-20) via `lib/autocount-formula.ts`, and a "check on server" parity call (AC-16-21);
  - live parse/validate, cannot save invalid.
- **Date-format tool** (AC-16-14): for a Date transform, a structured sub-panel - **input format**
  picker + **output format** picker over the fixed token vocabulary, with a live sample preview
  (sample date → parsed → reformatted). It writes `parseDate`/`formatDate` into the formula; the
  operator never hand-types a date pattern that could drift client/server.
- **Whole-mapping simulator** (a panel/dialog on the mapping editor): a mock AutoCount record input
  (JSON editor, or "Load a sample" via GET sample), Run → shows **input record beside the output
  Sorento record** + per-field errors (AC-16-30/31). Pure preview, writes nothing; wording keeps it
  distinct from the slice-14 Sorento dry-run.
- Types in `types/autocount.ts`; service methods (simulate, test-formula, sample) real+mock. No `any`.

## 5. Build order

1. Backend formula engine (`formula.py`) + the parity matrix + `formula` column migration + MappingEngine
   integration + PUT validation. Tests.
2. `lib/autocount-formula.ts` mirror + shared parity matrix test.
3. Backend simulate + test-formula (+ optional sample) endpoints. Tests.
4. FE formula builder + per-formula live sim.
5. FE whole-mapping simulator.
6. Live-verify (both viewports): edit a T/F formula, simulate a value, simulate a whole record, save,
   re-sync; E2E; test report.

## 6. Definition of Done

- No `eval`/Jinja anywhere; the parser is hand-written; client+server parity is TESTED, not assumed.
- A bad formula cannot be saved (front + 422) and cannot silently blank a field at runtime.
- Back-compat: existing named-transform rows behave identically (formula NULL).
- Column added on an existing table → existence-checked migration, verified on real Postgres (the
  module's create_all-before-migrate gotcha), revision ≤32 chars.
- Simulators write NOTHING; the whole-mapping sim runs the real engine.
- Read-only-until-Edit, searchable dropdowns, no instructional prose, responsive 375+1280, verified live.

## 7. Notes / risks

- Keep the function set SMALL - every function is surface to secure and to mirror. Add on demand.
- **Date parity RESOLVED via the structured tool** (was the open risk): a FIXED token vocabulary
  (`yyyy MM dd HH mm ss`, ISO) with one hand-written formatter mirrored client/server, driven by the
  input/output format pickers - no general date library, no free-form pattern to drift. Keep the token
  set minimal in v1 (the known vendor format + ISO out) and expand tokens on demand; every added token
  is mirrored + parity-tested.
- The whole-mapping simulator running the real MappingEngine is the high-value bit - it turns "will
  this mapping work?" into a testable question BEFORE a sync stages a broken batch (the null-record
  failure class from slice 15's live verify).
