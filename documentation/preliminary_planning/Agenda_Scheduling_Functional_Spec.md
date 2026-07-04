# Functional Specification: Agenda Builder & Real-time Scheduling

This document details the technical architecture for Sprint 6, outlining the database schemas, dependency engines, and real-time website reflections for the Interactive Scheduler.

---

## 1. Database Schema Design (Slots & Dependencies)

To support Drag-and-Drop scheduling, nested sub-slots, and Finish-to-Start relationships, the following tables are introduced:

**`Venues` Table:**
* `id`
* `project_id`
* `name` (e.g., "Main Hall", "Breakout Room A")
* `capacity`

**`Agenda_Sessions` Table (The core slot/sub-slot):**
* `id`
* `project_id`
* `venue_id`
* `parent_session_id` (Self-referencing Foreign Key. If NULL, it is a master slot. If populated, it is a nested sub-slot).
* `title`
* `start_time` (Timestamp)
* `end_time` (Timestamp)
* `submission_entry_id` (Optional. If this session is based on an approved submission/paper).
* `presenter_user_id` (FK to `Users`. The person presenting).

**`Session_Dependencies` Table:**
* `id`
* `predecessor_session_id` (The session that must finish first)
* `successor_session_id` (The session that follows)
* `dependency_type` (Enum: `FINISH_TO_START` - currently the primary logic)

---

## 2. Configuring Dependencies & The Delay Engine

**The UI Configuration:**
In the admin dashboard, the Interactive Scheduler uses a Calendar/Gantt chart interface (e.g., FullCalendar.io or a custom drag-and-drop React component). 
To create a dependency, the admin drags a connector line from the end of Session A to the start of Session B. This saves a row in the `Session_Dependencies` table.

**The Auto-Recalculation Engine:**
If the event is running late, the admin drags Session A's `end_time` to be 30 minutes later. 
1. The FastAPI backend updates Session A.
2. The backend queries `Session_Dependencies` where `predecessor_session_id` = Session A.
3. It finds Session B. It automatically adds +30 minutes to Session B's `start_time` and `end_time`.
4. It recursively checks if Session B is a predecessor to Session C, rippling the delay down the entire chain automatically.

---

## 3. Real-Time Website Subdomain Reflection

The public-facing Agenda on the subdomain cannot be static; it must act like a live airport departure board.

1. **The CMS Block:** During Sprint 2 (CMS Web Builder), the admin drops an "Agenda Block" onto the website.
2. **Dynamic Rendering:** When a visitor opens the subdomain, the Agenda Block queries the FastAPI backend (`GET /api/projects/{id}/agenda`) and groups the `Agenda_Sessions` by `venue_id` and `start_time`.
3. **Live Syncing (WebSockets):** The React frontend establishes a WebSocket connection with the FastAPI backend. When the Auto-Recalculation Engine shifts Session B by 30 minutes, FastAPI emits a WebSocket broadcast. The visitor's website instantly updates the timeslot on their screen without requiring a page refresh.

---

## 4. Template-Driven Delay Notifications

When a delay occurs, presenters and attendees must be notified immediately. We leverage the core **Template Engine** and **Workflow Engine** from Sprint 1.

### 4.1 Designing the Template
The admin uses the CMS to design a specific email template (e.g., "Session Delay Alert"). Because it uses Handlebars syntax, they can write:
> *"Hello {{presenter.first_name}}, due to unforeseen circumstances, your session **{{session.title}}** has been delayed. Your new start time is **{{session.start_time}}** at **{{venue.name}}**. Please be on standby."*

### 4.2 Triggering the Notification
1. When the Auto-Recalculation Engine updates Session B, it triggers an event in the Workflow Engine (`Event: onSessionDelayed`).
2. The Workflow Action is configured to `SendEmail`.
3. The engine grabs the "Session Delay Alert" from the `Templates` table.
4. It injects the new `start_time` and `presenter` details into the template variables.
5. It dispatches the styled HTML email via SMTP immediately to the `presenter_user_id`.
