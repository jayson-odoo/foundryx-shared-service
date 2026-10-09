# 22 - Stateful AI state contract for real LLMs

Contract: `22-stateful-ai-state-contract-acceptance-criteria.md`. Backlog: BL-SS-035. Fixes a plan-19 S1 correctness bug.

## 1. Why

Diagnosed live (workflow "Demo: progress update agent", real Gemini connection). The model returned:
```json
"statePatches": { "task": { "operation": "set", "value": "complete workflow in shared service" } }
```
No `evidence`. `app/workflow_engine/agent_state.py reduce_agent_state` requires `_evidence_slice(message, patch["evidence"])` to be a non-null exact substring; with no evidence the `set` is rejected -> `stateRejectedFields: ["task"]`, nothing saved, the Send Message renders `task: , status:`.

Root causes:
1. `app/workflow_engine/actions/ai_agent_actions.py ai_agent_run` sends the model a raw JSON user blob (built for the stub) and a system prompt = only `_build_system` (skills + node instructions). The "platform-generated state contract" plan 19 §4 specified was never implemented, so a real model never learns the evidence/operation rules.
2. `_stateful_schema_from_params` marks the patch `required: ["operation"]` - `evidence` optional.

The dev stub hardcodes `evidence`, so it always passed - masking the bug.

## 2. Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Add a platform STATE CONTRACT to the system prompt, only when the run is stateful. | Teaches a real model the input/output shape, operations, the evidence rule, enum mapping, and the readiness/clarification rule. This is what plan 19 §4 intended. |
| D2 | Reducer evidence FALLBACK: if a `set`'s `evidence` is missing/unfound but the string `value` is itself an exact substring of `currentMessage`, derive evidence from that occurrence and accept. | Salvages models that omit `evidence` when the value is quoted verbatim, WITHOUT weakening the guarantee (the value must still appear in the current message - no carry-over from `acceptedState`). |
| D3 | Keep the evidence RULE unchanged; a `set` with neither value nor evidence in the message stays rejected. | Anti-fabrication (D9) is the point of the feature; don't relax it. Enum canonical tokens absent from the message still need the model's evidence word (D1's contract instructs it). |
| D4 | Additive only - stub + existing tests untouched in behavior. | The stub ignores the system prompt and already supplies evidence; the fallback only fires when evidence was missing. |

## 3. Changes

- `app/workflow_engine/actions/ai_agent_actions.py`:
  - New `_state_contract(output_params)` -> a concise instruction block: input keys, output shape (`outputs` + `statePatches` per stateful key), operations (`set`/`clear`/`no_change`/`ambiguous`), the evidence rule (verbatim substring of `currentMessage`, enum = the exact indicating word(s), dropped otherwise, never reuse `acceptedState`), enum-value mapping, and "only signal the readiness value when every required stateful field is known; else set the clarification output + name the pending field."
  - In `ai_agent_run`, when `is_stateful`, prepend the contract to `system` (clearly delimited), so `AiClient.complete` sends it. Keep the JSON user message.
  - `_stateful_schema_from_params`: add `description` hints to `operation`/`value`/`evidence` (evidence: "exact substring of the current message; required for set/clear") to nudge providers; keep `no_change`/`ambiguous` valid without evidence.
- `app/workflow_engine/agent_state.py reduce_agent_state` (the `set` branch): if `_evidence_slice(message, patch.get("evidence"))` is None, and `value` is a str, try `_evidence_slice(message, value)`; if that returns a slice, use it as the provenance evidence and accept. Otherwise reject as today. `clear` unchanged (needs real evidence).

## 4. Tests

- `[BE]` `tests/test_stateful_ai_runtime.py` (or a new `test_stateful_state_contract.py`):
  - `reduce_agent_state` fallback: a `set` with no `evidence` but `value` quoted in the message -> accepted, provenance evidence = the matched slice; a `set` with value+evidence both absent -> rejected; an enum `set` whose token isn't in the message and no evidence -> rejected; existing explicit-evidence patches -> unchanged.
  - `_state_contract` present + non-empty; `ai_agent_run` includes it in the system prompt for a stateful run and NOT for a transient-only run (assert via the injected client double capturing `system`/messages).
  - A real-provider double returning an evidence-less-but-quoted `set` -> the field persists into `workflow_agent_states` and flattens to `nodes.<id>.<field>` (end-to-end through `ai_agent_run`).
- `[BE]` Regression: `test_stateful_ai_runtime`, `test_stub_stateful_derivation`, `test_progress_update_proof` stay green.

## 5. Verification (manual, real LLM)

Re-run the seeded demo with the agent bound to a real connection: turn 1 "my task is X" -> `task` persists + asks status; turn 2 "it's blocked" -> `status=blocked`, `task` retained; confirmation renders both. Record in `22-...-test-report.md` (or the plan) - the stub path, the fallback unit cases, and the real-LLM manual run.

## 6. Out of scope

Relaxing the evidence rule; per-provider prompt tuning; transcript memory (plan 19 D11); UI.
