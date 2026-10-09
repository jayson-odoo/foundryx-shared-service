# 22 - Stateful AI state contract for real LLMs - User Acceptance Criteria

Contract for `22-stateful-ai-state-contract.md`. Fixes a plan-19 S1 correctness bug. Backlog: BL-SS-035.

Stateful AI Agent outputs only ever worked with the dev STUB. With a REAL LLM every state patch is rejected, because the model is never told the state contract and returns `set` patches with no `evidence` - the reducer requires evidence (an exact substring of the current message) and drops the patch. Net: `stateRejectedFields` fills, nothing is saved, the confirmation renders blank. This slice makes stateful agents work with real models.

Tags: `[BE]` backend, `[T]` test.

## Slice - state contract + evidence robustness

### The model is told the contract

- **AC-SC-01 [BE]** For a STATEFUL AI Agent run, the system prompt sent to the model includes a platform-generated "state contract" (in addition to the agent's skills + the node instructions). It describes: the JSON input shape (`currentMessage`, `acceptedState`, `outputParameters`, `pendingClarification`); the required output shape (transient values under `outputs`, one patch per stateful field under `statePatches`); the four operations (`set`, `clear`, `no_change`, `ambiguous`); the enum-mapping rule (map free text to a declared enum value); and the readiness rule (only signal ready when all required stateful fields are known, else ask via the clarification output and set the pending field).
- **AC-SC-02 [BE]** The state contract states the EVIDENCE rule explicitly: every `set`/`clear` patch MUST include `evidence` = an exact verbatim substring copied from `currentMessage` (for an enum, the exact word(s) in the message that indicate the value); a patch whose evidence is not found in the current message is dropped; never reuse prior `acceptedState` as evidence.
- **AC-SC-03 [BE]** The contract is added ONLY for stateful runs. A non-stateful (transient-only) AI Agent's prompt is unchanged.

### Evidence is enforceable + robust

- **AC-SC-04 [BE]** The stateful output JSON schema marks `evidence` as expected on a mutating patch (description/`required` nudges the model), while `no_change`/`ambiguous` need no evidence.
- **AC-SC-05 [BE]** Reducer evidence FALLBACK: when a `set` patch's supplied `evidence` is missing or not found in the message BUT the patch `value` (a string) is itself an exact substring of `currentMessage`, the reducer derives the evidence from that occurrence and ACCEPTS the patch. This salvages real models that omit `evidence` when the value is quoted verbatim.
- **AC-SC-06 [BE]** The anti-fabrication guarantee is preserved: a `set` whose `value` and `evidence` are BOTH absent from the current message is still REJECTED (a model cannot carry a value forward from `acceptedState` alone). An enum `set` whose canonical token is not literally in the message still requires the model's `evidence` word (the contract instructs it) - no silent enum invention.

### Nothing regresses

- **AC-SC-07 [BE]** The dev stub still works end to end (it already emits the full contract shape); the seeded progress-update proof + `test_stateful_ai_runtime` + `test_stub_stateful_derivation` stay green (the fallback is additive; existing evidence-bearing patches are unaffected).
- **AC-SC-08 [BE]** A real-provider path (using the existing test double for the LLM client) that returns a `set` patch WITHOUT `evidence` but with a value quoted in the message now PERSISTS the field (was rejected before); one that returns a value absent from the message stays rejected.

### Verify

- **AC-SC-09 [T]** A test report (or the plan's verification section) records: stub green, the real-LLM-omits-evidence case now persists, the fabrication case stays rejected, and the seeded demo re-run with a real connection accumulates `task`/`status` across turns and renders a non-blank confirmation.

## Out of scope

- Changing the evidence RULE itself (it stays: value must be grounded in the current message). Prompt-tuning per provider. Transcript memory (still out per plan 19 D11). Any UI change.
