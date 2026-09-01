# Functional Specification: Event Day Operations

This document details the technical architecture for Sprint 7, focusing on Checkpoint validation logic, seamless hardware integrations for badge printing, and automated workflow triggers.

---

## 1. Checkpoint Validation & Configuration

To handle physical access control, we introduce two database tables:

**`Checkpoints` Table:**
* `id`
* `project_id`
* `name` (e.g., "VIP Lounge", "Main Entrance")
* `allowed_segments_json` (e.g., `["VIP", "Speaker"]`)
* `entry_type` (Enum: `SINGLE`, `MULTIPLE`)

**`Checkpoint_Logs` Table (Audit Trail):**
* `id`
* `checkpoint_id`
* `user_id`
* `status` (Enum: `SUCCESS`, `DENIED`)
* `denial_reason` (e.g., "ALREADY_SCANNED", "UNPAID", "WRONG_SEGMENT")
* `scanned_at`

### 1.1 The Scanning Technical Flow
1. The participant presents their QR ticket. The crew member scans it via tablet/phone camera.
2. The QR decodes into an encrypted `user_id` and `project_id`. The backend evaluates it against the specific Checkpoint rules:
   * **Segment Check:** Does the user's `segment_id` exist in the `allowed_segments_json`? (If no -> Deny: Wrong Segment).
   * **Financial Check:** Is the user's `User_Project_Roles.status_id` set to `Pending_Payment`? (If yes -> Deny: Unpaid).
   * **Entry Type Check:** If the Checkpoint is `SINGLE` entry, the system queries `Checkpoint_Logs`. If a `SUCCESS` log already exists for this user today, it denies access (Deny: Already Scanned).
3. If all checks pass, it logs `SUCCESS` and grants entry.

### 1.2 On-The-Spot Payment Resolution
If the scanner UI throws a **"DENIED: UNPAID"** error, the screen instantly renders a "Resolve Payment" button. 
Clicking this deep-links the crew member directly to the participant's invoice profile (`/admin/projects/{pid}/users/{uid}/invoices`). The crew member can immediately process a manual Cash/Credit card transaction, mark the invoice as PAID, and the user's QR code instantly becomes valid.

---

## 2. Hardware Integration (Silent Printer Connectivity)

Web browsers (Chrome/Safari) physically prevent websites from printing silently-they always force a "Print Dialog" popup, which slows down event registration. To achieve silent, universal printing compatible with ANY printer brand (Zebra, Brother, standard Laser), we use a **Local Print Spooler**.

### 2.1 The Architecture (QZ Tray or Custom Daemon)
1. The registration laptop runs a lightweight background daemon (like QZ Tray or a custom Node.js script) that listens on `http://localhost:8080`. This daemon has raw access to the OS drivers.
2. **Template Generation:** When a user checks in, the EMS backend generates their badge using the Template Engine (HTML to PDF) or ZPL (Zebra Printer Language).
3. **The Print Execution:** The web dashboard sends the PDF/ZPL directly to `http://localhost:8080/print`. The local daemon intercepts it and immediately fires it to the default USB/WiFi printer without a popup.

### 2.2 The "Test Connection" Feature
Before the event starts, the admin clicks "Test Printer" on the dashboard.
* The browser fires an empty ping to `http://localhost:8080/test`. 
* If the daemon is active and the printer is online, it returns `200 OK`. The UI displays a green "Printer Connected" status. If not, it warns the admin that the local spooler is offline.

---

## 3. Automated Event Triggers (Day-of Reminders)

We do not build a separate reminder engine; we leverage the core **Workflow & Template Engines** designed in Sprint 1.

### 3.1 The Configuration
1. **The Template:** Admin designs an email/SMS using the CMS Template builder (e.g., "Event Starts Tomorrow!").
2. **The Workflow Trigger:** Instead of an Action-based trigger (like "onPayment"), the admin selects a **Time-Based Trigger** via the Workflow UI. 
   * Example Rule: *Trigger = 24 Hours Before `Projects.start_date`*.
3. **The Workflow Action:** The Action is set to `SendEmail`, selecting the configured Template and targeting all users with `status_id = Eligible`.

### 3.2 The Execution
The Workflow Engine's `Scheduler` (a Cron background worker like Celery or BullMQ) constantly polls the database. When the clock hits exactly 24 hours before the event, the engine scoops up all eligible users, injects their variables into the Template, and blasts the reminders seamlessly.
