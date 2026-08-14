# Sprint 1 · Plan 06 - Omnichannel BSP: Core-Engine Integration (DEFERRED - paper contract only)

**Sprint:** 1 (design now, **execution deferred to backlog**)
**Status:** 🅿️ **Parked.** No code in this plan. It documents the integration contract so that when the EMS's base **Template / Workflow / Rule / Status-Machine engines** are built, they are **BSP-compatible by construction**.
**Source spec:** `documentation/high_level_plan_from_gemini/Whatsapp_BSP_Omnichannel_Functional_Spec.md` (§6)
**Depends on:** Plan 04 + Plan 05 (the omnichannel module must exist and process messages first) **and** the future core engines (not yet built).

---

## 1. Why deferred

The omnichannel automation in spec §6 (auto-replies, smart routing, lifecycle-triggered surveys) needs **generic platform engines** that don't exist yet:
- **Template engine** (merge-block rendering) - beyond the read-only WhatsApp-template *sync* in Plan 05.
- **Workflow engine** (trigger → action automation).
- **Rule engine** (condition evaluation → side effects).
- **Status & State-Machine engine** (configurable transitions over the static `statuses` table from Plan 04).

These are **EMS-wide foundations**, not BSP-specific. Building them now, only for WhatsApp, would produce throwaway, channel-coupled logic. Instead: build the omnichannel MVP (Plans 01-02) **without** them, build the engines generically when the EMS needs them, then connect via this contract. **Plan 05 deliberately emits no event bus yet** (grill decision 17) - the engines add their own emit-points at integration time, documented here.

---

## 2. Integration contract (what the engines must support so BSP plugs in cleanly)

### 2.1 Triggers the omnichannel module will raise
At integration time, these emit-points are added inside Plan 05's worker/services (no rework to message-processing logic - just publish calls):

| Trigger | Fired when | Payload (workspace+tenant scoped) |
|---|---|---|
| `onNewMessageReceived` | inbound message persisted (worker step 5/7) | `contact_id, channel_id, message_id, body, message_type` |
| `onCSWExpired` | a contact's `csw_expires_at` passes | `contact_id, channel_id` |
| `onThreadClosed` | thread status → CLOSED | `contact_id, previous_status, actor_id` |
| `onThreadOpened` / `onThreadSnoozed` | status transitions | `contact_id, status` |

### 2.2 Actions the engines will invoke back into omnichannel
Exposed as a stable service API the Workflow/Rule engines call:

| Action | Maps to | Notes |
|---|---|---|
| `SendChannelMessage(contact_id, template/body)` | Plan 05 outbound send | Respects **CSW enforcement** - off-hours/closed-window sends must use an approved template (off-hours reply, satisfaction survey). |
| `AssignContact(contact_id, user_id/pool)` | `PATCH contacts.assigned_user_id` | Replaces MVP manual-only assignment with rule-driven routing. |
| `SetPriority(contact_id, priority)` | `PATCH contacts.priority` | e.g. body contains "pricing"/"payment" → HIGH + route to Sales/Finance pool. |
| `TransitionThread(contact_id, status)` | status-machine over `statuses` | Close → triggers survey workflow, etc. |

### 2.3 Governance constraints (from EMS module rules)
- Engines hook via **predefined Event Listeners / the event bus** - **no** injection into core `main.py` or omnichannel internals (no global pollution).
- The event bus + listener registration is **core** infra (engines are platform foundations), the omnichannel module is a **publisher + action-provider**, not the bus owner.
- All triggers/actions stay **tenant + workspace scoped**; rule/workflow definitions are tenant-scoped config.

---

## 3. Example flows (from spec §6, realized via the contract)
- **Off-hours auto-reply:** `onNewMessageReceived` + a time-condition rule → `SendChannelMessage(off-hours template)` (template because window may be closed).
- **Smart routing:** `onNewMessageReceived` + content rule ("pricing"/"payment") → `AssignContact(finance/sales pool)` + `SetPriority(HIGH)`.
- **Satisfaction survey:** `onThreadClosed` → workflow → `SendChannelMessage(survey template)` on the active channel.

---

## 4. What to do now
- **Nothing executable.** Keep this as the reference when the engines are scoped.
- When the **Workflow/Rule/Status engines** sprint starts, the executor reads §2 here so the engines ship with these triggers/actions as first-class, and adds the emit-points into Plan 05's code.

## 5. Backlog entries (add to `backlog.md`)
- **Core Template engine** (merge-block rendering) - EMS-wide; BSP consumes for auto-replies/surveys.
- **Core Workflow engine** (trigger→action) - must support §2.1 triggers + §2.2 actions.
- **Core Rule engine** (condition→effect) - content/time conditions; routing + priority side effects.
- **Core Status & State-Machine engine** - configurable transitions over the `statuses` table (Plan 04 ships it static).
- **Omnichannel ↔ engine wiring** - add §2.1 emit-points + register §2.2 actions once the engines exist.
