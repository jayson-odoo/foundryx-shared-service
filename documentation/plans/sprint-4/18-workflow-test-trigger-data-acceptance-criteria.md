# Workflow test-trigger data — acceptance criteria

Contract for `18-workflow-test-trigger-data.md`. This slice extends the
workflow editor's existing Run action with safe, n8n-style test data for the
`omnichannel.message_received` trigger.

IDs continue plan 17's omnichannel workflow series: `AC-OA-24` onward. Tags:
`[BE]` `[FE]` `[E2E]` `[T]`.

## Test execution contract

- **AC-OA-24 [FE]** Given a draft whose trigger is Incoming omnichannel
  message, Run opens a trigger-aware `Test workflow` dialog instead of
  immediately posting empty inputs. The dialog uses searchable Channel and
  Contact controls plus a required Message textarea.
- **AC-OA-25 [BE]** The client submits only the trigger type, sandbox channel
  ID, contact ID, and message text. The backend derives tenant, workspace,
  contact name/phone, conversation ID, message type, and a synthetic message
  ID from tenant-scoped records.
- **AC-OA-26 [BE][FE]** Only active, untrashed `credentials.dev=true` channels
  and their usable contacts are offered. A fixed channel in the trigger is
  preselected/locked; an all-channel trigger requires an explicit channel.
  Changing channel clears contact. The server revalidates every selection.
- **AC-OA-27 [BE][FE]** A trigger test is always persisted with `is_test=true`,
  is visibly marked as a test in workflow logs, and records draft provenance
  (`versionId=null`, `versionNumber=0`).
- **AC-OA-28 [BE]** The selected workflow's current DRAFT snapshot executes
  once with the same `trigger.message.*`, `trigger.contact.*`,
  `trigger.channel.*`, and `trigger.conversationId` context shape as a real
  inbound event. The trigger node output exposes the captured test event.
- **AC-OA-29 [BE]** Test execution does not call the public webhook or inbound
  service, persist an inbound message, publish inbound realtime/consumer
  events, or start another published workflow.
- **AC-OA-30 [BE][FE]** Workflow actions retain real semantics. The dialog
  warns when an AI Agent or outbound Send Message action will execute. Safe
  sandbox selection guarantees Send Message uses the dev transport; the test
  may create one outbound reply and an AI trace.
- **AC-OA-31 [BE]** Blank/oversized messages, forged or cross-tenant IDs,
  inactive/trashed/non-sandbox channels, contact/channel mismatches, stale
  trigger types, and test data sent without test mode are rejected before a
  WorkflowRun or outbound message is created.
- **AC-OA-32 [FE]** No eligible sandbox source renders a concise prerequisite
  warning and disables Test workflow. Test values are not saved into the
  workflow draft or browser storage. Existing manual-trigger inputs continue
  to run unchanged.

## Verification

- **AC-OA-33 [T]** Backend pytest and frontend Vitest cover the happy-path
  vertical slice, canonical context, draft/test provenance, tenant and
  sandbox validation, no-inbound side effects, exact request contract,
  manual-run regression, required/empty states, and dialog state reset.
- **AC-OA-34 [E2E]** A real-click browser journey signs in, opens the seeded
  workflow, enters sandbox trigger data, runs the draft through the stub AI
  Agent and Send Message, verifies a successful Test run and one outbound
  reply, then repeats layout/overflow checks at 1280px and 375px. A fresh
  frontend production build passes.
