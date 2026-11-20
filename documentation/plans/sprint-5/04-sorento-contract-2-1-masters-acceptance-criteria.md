# 04 - Sorento contract 2.1: master payloads (omit null, drop credit_limit) - User Acceptance Criteria

> **Status:** ACCEPTED (written 2026-09-06 alongside the build; the lane started from a live 422 drill,
> the UAC was reconstructed before review round 2 so the test report keys back to it).
> **Builds on:** `sprint-4/14` masters ESB (`CanonicalMaster`, `SINK_FIELDS`, `SorentoSink`),
> `sprint-5/02-autocount-document-mapping-sorento-addendum.md` (the cross-repo contract change log).
> **Contract of record:** Sorento `documentation/plans/autocount/PLAN-autocount-cross-repo-contract.md`
> section 10 (branch `feat/ingest-parity`, ref 39ddd8c0a, their PR #699; `GET /api/v1/external/contract`
> answers `version "2.1"`, `field_notes.products` = "name is transitional, maps to description when
> description is absent").
> **Target:** every master push from the ESB is accepted by a Sorento that answers contract 2.1
> (`extra="forbid"` on `CanonicalCustomer`, `null` on a master field = clear, absent = leave alone),
> while staying behaviour-neutral against Sorento 1.x/2.0 (which ignore `credit_limit` and read an
> absent key exactly like an explicit null).

## Scope

**In (backend only):** `CanonicalCustomer.SINK_FIELDS` loses `credit_limit`; `CanonicalMaster.sink_payload`
omits every None-valued key for all seven master entities; the customer default mapping and the
source-column suggestions stop offering `CreditLimit`; existing tenants' saved enabled customer rows
targeting `credit_limit` are disabled by a delivered backfill (module Alembic revision + App Store
version bump + `update_tenant`); mapping validation counts only enabled rows toward the required set;
addendum change-log entry naming the Sorento ref and the removal sequencing.

**Out:** a contract-version gate (both changes are safe on every Sorento version, a knob would prevent
no failure); D24 (`Item.Description` -> `description` on products) - next lane; an explicit-clear
path for masters under 2.1 (BL entry, see AC-04-08); documents (their wire is unchanged); frontend
(the mapping editor is catalog-driven, the target simply disappears from the picker).

## Definitions

- **Sink field** - a canonical attribute listed in an entity's `SINK_FIELDS`; only these cross the wire.
- **Omitted key** - a sink field whose canonical value is None; it is absent from the payload dict,
  never serialised as `null`. Falsy non-None values (`0`, `""`, `False`, `[]`) are still sent.
- **Inert row** - a saved `ac_mapping_row` whose `canonical_field` is no longer in the entity's
  accepted target set. Invisible in the editor, pruned on the next save, never reaches the wire.
- **Delivered backfill** - a data fix that reaches EVERY existing tenant without operator action:
  a module Alembic revision (runs at container start on deploy) and, for the App Store update path,
  `update_tenant` behind a manifest version bump (an update is refused when installed >= manifest).

## Acceptance criteria

**AC-04-01 [BE] Customers never send credit_limit.**
Given a customer whose canonical `credit_limit` is set (any value),
When `sink_payload()` is built,
Then the dict has no `credit_limit` key, and `credit_limit` is not in `CanonicalCustomer.SINK_FIELDS`
(`accepted_field_names("customer")` therefore no longer offers it as a target).

**AC-04-02 [BE] Masters omit None keys, keep falsy values.**
Given any of the seven master entities with some sink fields None and some falsy-but-set,
When `sink_payload()` is built,
Then every None-valued sink field is absent, every populated field (including `0`, `""`, `False`) is
present with its value, and every populated sink field still crosses (no over-pruning).
Documents are untouched by this rule (their payload builder is separate and its suite stays green).

**AC-04-03 [BE] Default customer mapping and suggestions carry no credit_limit.**
Given a freshly registered company,
When `seed_company_defaults` runs,
Then no seeded customer row targets `credit_limit`, and `mapping_catalog` does not suggest
`CreditLimit` as a source column for customer or supplier.

**AC-04-04 [BE] Existing tenants' inert credit_limit rows are disabled, and the fix is delivered.**
Given a tenant with a saved ENABLED customer mapping row targeting `credit_limit` (and a supplier
row or another entity's row that happens to share the name),
When the module is upgraded (Alembic `0013_autocount_drop_credit_limit` on deploy, OR the App Store
update from 0.4.0 to 0.5.0 running `update_tenant`),
Then the customer row is disabled, rows of other entity types are untouched, a second run changes
nothing, and the manifest version is greater than the version every existing tenant holds (0.4.0).
A test must fail if the `update_tenant` wiring is removed (kill-test M4 of review round 1).

**AC-04-05 [BE] A required target present only as a disabled row fails the save.**
Given a mapping draft where a required target (e.g. `is_active`) exists only with `isEnabled: false`,
When the mapping PUT is evaluated,
Then the request is rejected as missing the required field instead of silently dropping it from the
wire (under Sorento main `is_active` defaults True, so an absent key would silently activate the record).
Simulate previews a disabled required row as absent and never rejects (it writes nothing; a partial
draft must still preview, sprint-5/02 contract).

**AC-04-06 [BE] Behaviour-neutral on Sorento 1.x/2.0.**
Given a Sorento that still declares `credit_limit` / `payment_terms_*` and reads an absent key as None,
When the ESB pushes the 2.1-shaped payload,
Then the record lands identically to before (verified in the sibling repo's ingest service; no
version gate added).

**AC-04-07 [DOC] Contract-as-diff.**
Given the wire change above,
When the lane merges,
Then the addendum change log names the Sorento ref verified against, the contract of record section,
the `field_notes.products` text, and the sequencing rule: the ESB stops sending `credit_limit` BEFORE
Sorento removes it (D15); Sorento's removal 422s only once 2.1 answers the contract endpoint.

**AC-04-08 [DOC] Known capability loss is logged, not hidden.**
Given 2.1 defines `null` = clear on masters,
When every None is omitted,
Then the ESB has no explicit-clear path for a master field; a backlog entry names the case and the
seam (enabled mapped field resolving to None = real clear vs unmapped field = omission; the distinction
exists in the mapping engine, not in the canonical model). Sorento's ruling (2026-09-06, matches the
xlsx importer under D14): a MAPPED field whose AutoCount value is blank must arrive as `null` (clear);
only UNMAPPED fields are omitted; `credit_limit` / `payment_terms_*` stay absent (no longer in the schema).
The 2.1 wire needs no change for it; the ESB change is the follow-up lane.

## Live verification (against the Sorento local ingest-parity lane on :8042)

- SIM customers task: 27/27 created or updated, zero `credit_limit` 422 (round 1 of the drill: 27/27 422).
- SRT products re-offer after the hash clear + watermark reset: 11,784 pushed, 0 failed; Sorento
  verifies the D24 derivations on their lane DB (about 2,871 discontinued, about 2,282 with dimensions).
- Any new warning code is reported back to Sorento and added to the addendum.

## Decision log

- 2026-09-06: unconditional, no contract-version gate (captain + reviewer agree: v1/v2 ignore both
  changes, a gate prevents no failure).
- 2026-09-06 review round 1: the sweep alone was not a delivered backfill (manifest still 0.4.0, no
  migration, wiring untested) - AC-04-04 rewritten to require all three; AC-04-03 and AC-04-05 added
  from findings 3 and 4; the sweep docstring's "trips the PUT guard" justification was wrong and is
  replaced by the real one (table matches the accepted target set; visible change behind the bump).
