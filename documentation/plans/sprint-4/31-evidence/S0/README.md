# Plan 31 - S0 (FE catalog + mock) - agent-browser evidence run

Run date: 2026-09-06. Session `s31` (backend `:8010` / DB `foundryx_service_s31`, frontend `:3009`,
prod build `rm -rf .next && npm run build && npx next start -p 3009`). Signed in as
`demo@example.com` on the default tenant. Real clicks from `/`, no typed URLs (record-nav via the
sidebar and breadcrumbs as a real user would).

## What this proves (AC-WFP-01..06)

1. **01-04, 03** - Sidebar `Workflows` -> `New workflow`. Palette shows `TRIGGERS(18)` / `LOGIC(3)` /
   `ACTIONS(24)` (9 pre-existing + 9 new triggers incl. `broadcast_completed`; IF + Wait + Business
   hours in Logic; 13 pre-existing + 11 new in Actions - Wait/Business hours counted in Logic, not
   Actions). `03-manual-click.png` proves click-to-add works at all (baseline sanity check) before
   trying the new entries.
2. **04-conversation-closed-added.png** - `Conversation closed` trigger added via the search box (the
   palette collapses long lists - scrolling to an off-screen item needs the search box; click-to-add
   on an out-of-viewport button is a known agent-browser/dnd-kit limitation, not a product bug -
   `02-retry-click.png` documents the miss before switching to search). Renders Workspace picker,
   Close reason (disabled "Choose a workspace first" until a workspace is chosen - AC-WFP-03) and the
   "Trigger once per contact" checkbox (AC-WFP-02: boolean flags are a checkbox, not a bare `<Select>`).
3. Choosing workspace "General" unlocks Close reason -> options are `Resolved`/`Spam` only, **`Legacy`
   (inactive) is excluded** (AC-WFP-03 workspace + active-only scoping).
4. **05-07** - `Assign conversation` step added. `User` picker is disabled ("Choose a workspace
   first") until a workspace is chosen, then scoped to that workspace's members. Switching
   `Assign mode` from "Specific user" to "Round robin" **removes the User field from the drawer
   entirely** (AC-WFP-04 show_when + hidden-field clearing - `onConfigChange` was called with
   `{mode:'round_robin', userId:''}`, confirmed by the issue count dropping from 4 to 2 as the
   now-hidden `userId` requirement disappears).
5. **08** - `Update contact field` step: Field picker disabled until a workspace is chosen, then lists
   ONLY that workspace's registered fields (`Company`, `Order count`), plus a "Clear the field"
   checkbox (boolean, not select).
6. **09-10** - `Close conversation` step: Contact / Workspace / Close reason (active-only, same
   scoping as the trigger) / Note (mergeable textarea).
7. **11-20** - Wired Trigger -> Assign -> Update field -> Close conversation via real
   `mouse move/down/up` sequences onto the source/target handles (React Flow drags need real pointer
   events, not synthetic clicks - confirmed working the same way for the new node types as for
   existing ones). Filled the merge-rendered Contact field on each action
   (`{{ trigger.contact.id }}`). Issue banner shrank from "6 issues" to zero as each requirement was
   met - proves the catalog's `required`/`showWhen` fields drive the SAME `validateDefinition` gate as
   every pre-existing node type.
8. **21-23 - Save + Publish.** Named the workflow, saved the draft (`Save workflow` also runs
   `validateDefinition` - a structurally invalid draft is rejected with a toast, e.g.
   `30-save-check.png` from the second workflow), then clicked **Publish**.
   **Finding worth flagging (see "Plan/UAC issues" below): Publish SUCCEEDED** ("Published - the
   trigger can now fire this workflow"), not a backend 422. The coder brief's "DoD" step assumed the
   backend would 422 an unregistered node type at publish; the live backend instead accepts the graph
   permissively (structural checks only - one trigger, acyclic, connected, required-fields-per-catalog
   - none of which reference a server-side type registry). The trigger simply cannot fire yet (no
   `omnichannel.conversation_closed` TriggerDef exists server-side until S1), so the workflow is inert
   but harmlessly "Published - inactive-effectively" until S1/S2 land the real registry entries.
9. **24, 34 - 375px.** Both the published workflow's editor tab and the Ask-a-question drawer reflow
   cleanly at 375px (toolbar wraps, panels stack, canvas + drawer scroll independently, no clipping).
10. **25-29 - Ask a question (AC-WFP-05, AC-WFP-06).** Built a second workflow: `Incoming omnichannel
    message` -> `Ask a question`. `26`: switching Answer type to "Choice" reveals the Choices editor
    (show_when). `27` (zoomed): **the node renders two distinct labelled source handles** (blue
    "answer", amber "timeout") in the same bottom-of-card position as the IF node's true/false
    handles - confirms the generic multi-port rendering (D-A5-14) works for a real catalog entry, not
    just the built-in IF node. `25`/`28`: the publish-blocking banner reads **"Ask a question requires
    serialized execution and a Correlation key."** while execution is Parallel, and **disappears**
    once Execution mode is set to "Serialized by key" with a Correlation key
    (`{{ trigger.contact.id }}`) - proves the frontend `validateDefinition` parity rule (AC-WFP-06).
11. **32-33** - Wired the Ask node to the trigger with real pointer drags (answer/timeout ports are
    independently connectable exactly like IF's true/false), filled the required Contact field, saved
    the draft cleanly (no toast, url changed to `/workflows/<id>`).
12. Backend `console` log stayed clean throughout (no 500s); `agent-browser console` on the frontend
    showed zero warnings/errors after each interaction.

## Two scratch workflows left in the `default` tenant on this lane's DB (`foundryx_service_s31`)

- `S0 smoke: conversation closed parity` - **Published** (inert - no backend TriggerDef yet).
- `S0 smoke: ask a question ports` - **Draft, not published**.

Both are named `S0 smoke: ...` for easy identification/cleanup by a later slice; harmless on this
lane-dedicated DB (never touches `foundryx_service` or any other lane's DB).

## Plan/UAC issues flagged (not silently redesigned)

- **The DoD's "publish attempt shows the backend 422 cleanly" did not hold.** Publish succeeded
  permissively for a graph built entirely from S0-only (frontend-catalog, no backend registry)
  trigger/action types. This is not a bug in this slice - the backend's `definition_issues`/publish
  gate does not (and per the registry design, cannot) reject an unrecognized node `type` string; it
  only enforces structural rules (one trigger, acyclic, connected, required-fields-per-KNOWN-catalog).
  An unregistered type is invisible to it. Net effect: a tenant COULD build and publish one of these
  workflows today; it just never fires until S1/S2 register the real `TriggerDef`/`ActionDef`s. Worth
  a line in the S1 plan/report: either accept this (harmless - inert until registered) or add an
  explicit "not yet available" gate. Flagging per the brief's instruction to surface plan deviations
  rather than silently re-describe the observed behavior as the expected one.
- **`omnichannel.assign_conversation`'s `userId` field type.** Plan §5.3 types it `text` (mergeable);
  UAC AC-WFP-03 lists "members" among the workspace-scoped pickers a picker must offer. Resolved this
  in favor of the UAC: `userId` is an `omnichannelMember` `SearchSelect` scoped by a (added)
  `workspaceId` field, at the cost of losing free-form merge input for that field. See the "Deviations
  from §5.3" note in the handoff/report to the planner - flagged, not silently designed around.
