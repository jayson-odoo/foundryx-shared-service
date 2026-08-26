# Workflow test-trigger data

**Contract:** `18-workflow-test-trigger-data-acceptance-criteria.md`  
**Depends on:** sprint-4/17 omnichannel trigger/actions/AI Agent

## Outcome

The workflow editor can test an Incoming omnichannel message draft without a
real webhook. The operator selects a real dev-sandbox channel/contact and
enters a synthetic message. Only that workflow's draft executes; downstream
AI and outbound actions run normally and are auditable as a test.

## Decisions

1. Extend `POST /workflows/{id}/run`; do not create a second execution engine.
   `WorkflowRunRequest` gains an optional discriminated `testTrigger` value.
2. Keep test construction module-owned. `TriggerDef` gains optional test-option
   and test-payload callbacks; core workflow code does not import omnichannel.
3. Discover safe choices through the existing workflow metadata response,
   filtered server-side to dev-sandbox pairs. The run endpoint revalidates the
   IDs and never trusts client-supplied names, phone, workspace, or tenant.
4. Do not route through `InboundService`. The synthetic inbound exists only in
   the run payload/snapshot, so it cannot contaminate the inbox or fan out.
5. A real contact is mandatory because Get Contact and Send Message actions
   operate on database records. Only `credentials.dev=true` channels are
   eligible, making outbound transport deterministic and local.
6. Trigger tests execute the current draft and record `versionId=null`,
   `versionNumber=0`, `isTest=true`. Existing manual-run behavior remains.
7. Reuse the existing Run dialog. For omnichannel it becomes a small,
   responsive test-data form built with `SearchSelect`; it never guesses an
   all-channel choice and it shows concise real-side-effect warnings.

## Backend design

- Add the typed test-trigger schema and camelCase wire contract.
- Extend the workflow trigger registry with optional module callbacks.
- Add omnichannel repository/service helpers that:
  - resolve tenant-scoped active dev channels;
  - expose only valid contact/channel pairs compatible with the draft trigger;
  - validate contact/channel/workspace membership and message bounds;
  - derive the canonical omnichannel event envelope and synthetic message ID.
- Build the same executor context used for production events, but invoke the
  executor directly on the selected draft snapshot.
- Include canonical event fields in the trigger node's recorded output.
- Reject invalid test data before creating a run.

## Frontend design

- Extend workflow metadata/request types with the sandbox source and typed
  omnichannel test-trigger contract.
- Make `RunDialog` trigger-aware while retaining its manual-input branch.
- Omnichannel branch: Channel `SearchSelect`, Contact `SearchSelect`, Message
  textarea, prerequisite/side-effect alerts, disabled submit until valid.
- Preselect a configured fixed channel; never auto-select a channel for “All
  channels” or a contact. Reset contact when channel changes and clear all
  transient test values when the dialog closes.
- Send `{inputs:{}, isTest:true, testTrigger:{...}}` through the existing hook,
  service, and API-client layering.

## TDD slices

1. RED backend API tracer for test payload → draft trigger → stub AI → sandbox
   outbound reply; GREEN with registry/module payload construction.
2. RED backend adversarial tests for cross-tenant, forged, non-sandbox,
   mismatched, blank, and stale data plus no-run/no-inbound assertions; GREEN
   with repository-scoped validation.
3. RED frontend dialog tests for trigger-specific fields, filtering, reset,
   warnings, exact request, and manual regression; GREEN through existing
   component/hook/service boundaries.
4. Add real-click Playwright coverage at desktop and mobile, then run focused
   suites, full affected suites, lint, and a fresh production build.

## Definition of done

All AC-OA-24..34 evidence is recorded in
`18-workflow-test-trigger-data-test-report.md`; backend/frontend tests, lint,
build, desktop/mobile real-browser verification, and final diff review pass.

