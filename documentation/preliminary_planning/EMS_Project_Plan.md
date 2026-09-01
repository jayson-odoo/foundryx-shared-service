# Event Management System (EMS) Project Plan

## 1. Work Breakdown Structure (WBS)

### Sprint 1: Core System & Infrastructure

- **1.1 Infrastructure Setup (Database Schema)**
  - *Architectural Note:* Development must follow a strictly modular, decoupled architecture to ensure maximum scalability across tenants and features.
  - **`System_Settings` Table:** `id`, `setting_key` (e.g., 'SMTP_HOST', 'SMTP_USER', 'SMTP_PASS'), `setting_value`, `is_encrypted`, `updated_at`. (Stores global configs like SMTP dynamically).
  - **`Statuses` Table (Master Data):** `id`, `entity_type` (e.g., 'Lead', 'Task', 'Submission'), `name`, `color_code`, `is_default`.
  - **`Status_Transitions` Table:** `id`, `entity_type`, `from_status_id`, `to_status_id`, `conditions_json`, `workflow_trigger_id` (hooks into Workflow Engine).
  - **`Users` Table:** `id`, `email`, `password_hash`, `first_name`, `last_name`, `phone`, `status_id`, `system_validity_end`, `created_at`, `updated_at`.
  - **`Clients` Table:** `id`, `name`, `registration_no`, `contact_person`, `created_at`.
  - **`Leads` Table:** `id`, `client_id`, `source`, `status_id`, `notes`, `created_at`.
  - **`Project_Types` Table (Master Data):** `id`, `type_name`, `config_json`, `status_id`.
  - **`Projects` (Events) Table:** `id`, `client_id`, `project_type_id`, `title`, `brief`, `notes`, `domain_name`, `start_date`, `end_date`, `event_validity_end`, `status_id`.
  - **`Venues` Table:** `id`, `project_id`, `name`, `capacity`.
  - **`Agenda_Sessions` Table:** `id`, `project_id`, `venue_id`, `parent_session_id` (nested sub-slots), `title`, `start_time`, `end_time`, `submission_entry_id`, `presenter_user_id`.
  - **`Session_Dependencies` Table:** `id`, `predecessor_session_id`, `successor_session_id`, `dependency_type` (e.g., FINISH_TO_START).
  - **`Checkpoints` Table:** `id`, `project_id`, `name`, `allowed_segments_json`, `entry_type` (SINGLE/MULTIPLE).
  - **`Checkpoint_Logs` Table:** `id`, `checkpoint_id`, `user_id`, `status` (SUCCESS/DENIED), `denial_reason`, `scanned_at`.
  - **`Task_Templates` Table:** `id`, `project_type_id`, `name`, `default_tasks_json`.
  - **`Tasks` Table:** `id`, `project_id`, `title`, `description`, `assignee_id`, `status_id` (Kanban state), `due_date`.
  - **`User_Project_Roles` Table:** `id`, `user_id`, `project_id`, `role_name`, `segment_id`, `status_id` (eligibility). (Note: This table maps 1 User Profile account to multiple events).
  - **`Submission_Forms` Table:** `id`, `project_id`, `form_name`, `fields_schema_json`. (Defines the dynamic fields for submissions).
  - **`Submission_Entries` Table:** `id`, `submission_form_id`, `project_id`, `participant_user_id`, `status_id`, `current_revision_id`, `entry_data_json`. (Stores participant's actual submission).
  - **`Review_Forms` Table:** `id`, `submission_form_id`, `form_name`, `fields_schema_json`. (Defines the dynamic fields for reviews).
  - **`Review_Configurations` Table:** `id`, `project_id`, `required_review_count`, `window_start_date`, `window_end_date`.
  - **`Review_Assignment_Rules` Table:** `id`, `review_form_id`, `reviewer_user_id`, `conditions_json`. (Maps the Rules Engine criteria).
  - **`Review_Entries` Table:** `id`, `review_form_id`, `submission_entry_id`, `reviewer_user_id`, `status_id`, `entry_data_json`. (Stores actual review data).
  - **`Quotations` Table:** `id`, `project_id`, `lead_id`, `client_id`, `amount`, `status_id`, `revision_number`, `parent_quotation_id`, `created_at`.
  - **`Products` Table:** `id`, `project_id`, `name`, `type` (TICKET/ADD_ON), `price`, `valid_from`, `valid_until` (controls UI visibility), `stock_limit`.
  - **`Event_Tickets` Table:** `id`, `project_id`, `product_id`, `purchaser_user_id` (original payee), `attendee_user_id` (nominated participant), `invoice_id`, `status_id`.
  - **`Password_Resets` Table:** `id`, `user_id`, `token`, `expires_at`.
  - **`Invoices` Table:** `id`, `user_id`, `project_id`, `quotation_id` (optional), `amount`, `currency`, `status_id`, `created_at`.
  - **`Payments` Table:** `id`, `invoice_id`, `amount`, `payment_gateway_id`, `gateway_ref_id`, `status_id`, `created_at`.
  - **`Payment_Gateway_Configs` Table:** `id`, `project_id`, `vendor_name`, `credentials_json` (encrypted), `is_test_mode`, `is_active`.
  - **`Integration_Logs` Table:** `id`, `project_id`, `integration_type`, `direction`, `endpoint_url`, `request_payload_json`, `response_payload_json`, `http_status_code`, `created_at`.
  - **`Workflows` Table:** `id`, `project_id`, `name`, `status_id`, `created_at`.
  - **`Workflow_Nodes` Table:** `id`, `workflow_id`, `node_type` (trigger/action), `config_json`, `next_node_id`.
  - **`Templates` Table:** `id`, `project_id`, `type` (email/badge/qr/invoice), `content` (stores HTML/JSON with inject variables), `status_id`.
  - **`Folders` Table:** `id`, `project_id`, `parent_folder_id`, `name`, `created_at`.
  - **`Files` Table:** `id`, `folder_id`, `project_id`, `quotation_id` (optional mapping), `name`, `storage_url`, `size`, `created_at`.
  - **`File_Shares` Table:** `id`, `file_id`, `folder_id`, `shared_with_email`, `access_level` (view/edit), `share_link_token`, `expires_at`.
  - **`Installed_Modules` Table:** `id`, `module_name` (e.g., 'Finance', 'CMS'), `version`, `status` (installed, active, inactive), `config_json`, `installed_at`.

- **1.2 Base Engines Development (Detailed Design)**
  - **1.2.1 Workflow Engine:**
    - *Architecture:* Table-driven publisher/subscriber model executed via a task queue (e.g., BullMQ).
    - *Components:* 
      - `Workflows Table`: Maps to the overarching process flow.
      - `Workflow_Nodes Table`: Defines the `Triggers` (e.g., `onPaymentSuccess`) and `Actions` (e.g., `SendEmail`, `UpdateStatus`) in a linked-list or graph format via `next_node_id`.
      - `Execution Engine`: Reads the nodes, evaluates trigger conditions, and executes action configurations sequentially.
      - `Scheduler`: A cron-processor evaluating time-based triggers mapped in the nodes (e.g., sending an email 3 days before an event).
  - **1.2.2 Rule Engine:**
    - *Architecture:* JSON-based logical tree evaluation (using libraries like `json-rules-engine`).
    - *Components:* 
      - `Facts`: Runtime context variables (e.g., `user.segment`, `submission.category`, `unreviewed_count`).
      - `Operators`: Logic operators (AND, OR, ==, >, <, IN, NOT IN).
      - `Rules`: Condition chains that return boolean outcomes. Used extensively for determining checkpoint eligibility, dynamic submission windows (escalations), and mapping reviewers to submissions based on category fields.
  - **1.2.3 Status & State Machine Engine:**
    - *Architecture:* Configurable master data evaluator driving entity lifecycles and Kanban boards.
    - *Components:*
      - `Statuses Table`: Defines the available statuses (e.g., Draft, Pending, Approved) universally across entities (Leads, Tasks, Submissions, etc.).
      - `Status_Transitions Table`: Maps the allowed flow (`from_status_id` -> `to_status_id`).
      - `Transition Hooks`: Evaluates `conditions_json` via the Rule Engine before allowing a transition. If successful, it triggers a `workflow_trigger_id` to execute an automated workflow (e.g., sending an email when a Lead status changes to 'Won').
  - **1.2.4 Template Engine:**
    - *Architecture:* Multi-format rendering pipeline (HTML for emails/web, PDF/Image for badges and tickets) using Handlebars or Mustache syntax.
    - *Components:*
      - `Templates Table`: Stores everything-template structure, style, and inject variables-in a single row per template.
      - `Variable Injector`: Populates placeholders like `{{user.name}}`, `{{qr_code_url}}`, or `{{invoice.amount}}` based on the triggered context.
      - `Template Nesting`: Supports including partials (e.g., rendering an `{{> event_header}}` inside a ticket template).

### Sprint 2: CRM, Project & CMS Web Builder
- **2.1 CRM Fundamentals (UX Flow)**
  - **User Profiles:** Creating a User Profile generates a master user account. When the user registers for different events, the system saves the relationship in `User_Project_Roles`, providing a unified login experience across the platform.
  - **Lead & Client Management:** Admin uses a step-by-step **Wizard UI** to create a lead section by section. The wizard includes a "Select Customer" step. If the customer isn't found, an inline **"Quick Create Client"** button allows instant creation without losing wizard progress.
- **2.2 Project (Event) Management**
  - **Project Creation:** Admin fills out the event fields (Type, Title, Brief, Dates, etc.).
  - **Onboarding Checklists:** Automatically generated against the specific project context based on the Project Type.
  - **Task Management:** Admin selects a "Task Template" which auto-populates all necessary tasks under the project. Tasks feature a **Kanban Board** view allowing drag-and-drop state transitions.
  - **Domain Integration (DNS Checker):**
    - *Endpoint:* External API (e.g., RapidAPI DNS Checker: `GET https://dns-checker.p.rapidapi.com/dns/{domain}`).
    - *Auth/Cost:* Requires an API Key. Depending on the service chosen, it may fall within a free tier or require a small monthly subscription.
    - *Payload:* The requested domain string and DNS record type (e.g., `A` or `CNAME`).
    - *Expected Result:* Returns a JSON array of resolving IPs or a boolean indicating if the domain is available. The UI instantly reflects this availability.
- **2.3 Quotation & Document Management**
  - **Quotation Management:** Quotations are explicitly generated against a Project. The system supports a revision history; when a quotation is modified, a new revision is cloned (`parent_quotation_id` tracks lineage) preserving the old record.
  - **Resource / Document Management System:** A built-in "Google Drive-ish" file repository tied to the project.
    - *Folder Structure:* Users can create folders and nested subfolders.
    - *File Operations:* Upload files (like certificates or POs), attach files directly to specific quotations, and edit filenames.
    - *Access & Sharing:* Generate secure share links with tokens. Control access levels (View/Edit) by sharing directly with emails or adjusting link visibility.
- **2.4 Web Content Builder (CMS)**
  - **Base Architecture:** Built using an open-source library like **Craft.js** (for React/TypeScript Metronic) or **GrapesJS** as the core drag-and-drop engine. It integrates seamlessly with the **Metronic** UI component library on the frontend and syncs serialized JSON schema data to the **FastAPI** backend.
  - **Required CMS Elements:**
    - *Layouts:* Sections, Containers, Columns, Grids.
    - *Basics:* Typography (Headings, Text), Images, Buttons, Dividers.
    - *Event-Specific Blocks:* Registration Forms (data-bound to EMS), Real-time Agenda block (syncs with Scheduler), Speaker Rosters, Pricing/Ticket Tiers, and Countdown Timers.
  - **Custom Component Capabilities:** Users can extend the CMS through three tiers:
    - *No-Code Composition:* Users can group standard blocks, style them, and save them to a "Custom Blocks Library" to be reused across any project.
    - *Low-Code HTML/CSS Injection:* Users can use an "Embed Code" block to paste raw HTML/CSS/JS (e.g., a third-party widget iframe) which the system sanitizes before rendering.
    - *Pro-Code Component Uploads:* Developers can upload raw React (`.tsx`) or Web Components. The architecture dynamically imports these modules (e.g., via Webpack Module Federation or dynamic `import()`), registers them in the Craft.js/GrapesJS toolbox, and renders them.
  - **AI Generation:** Scaffolds a preliminary JSON page layout based on the "Project Brief" before the user begins manual customization.
  - **Subdomain Publishing Methodology:**
    - *Data Persistence:* The CMS serializes the final page design into a JSON tree (and compiled HTML/CSS) and stores it in the FastAPI database, linked to the `Project`.
    - *Infrastructure Routing:* A wildcard DNS record (`*.foundryx.com.my`) routes all subdomain traffic to a central reverse proxy (e.g., Nginx, Traefik, or an edge network like Cloudflare).
    - *Resolution & Rendering:* When a visitor hits `eventname.foundryx.com.my`, the frontend middleware reads the `Host` header (`eventname`), queries the FastAPI backend for the matching Project's CMS data, and dynamically renders the Metronic-styled components on the fly without needing a static build step.
- **2.5 Internal App Store (Module Manager)**
  - **Operator Dashboard:** A frontend UI listing all natively available and custom modules in the EMS ecosystem.
  - **Lifecycle Controls:** Operators can easily Import, Export, Install, Uninstall, Upgrade, Activate, or Deactivate modules.
  - **Dynamic Resolution:** Activating/Deactivating a module instantly toggles its UI routes in the Metronic sidebar and its FastAPI router endpoints, requiring zero system downtime.

### Sprint 3: Registration & User Portal
- **3.1 Authentication & Profile**
  - **Account Creation (Ala Carte Registration):**
    - User fills out self-serve registration form.
    - System creates `Users` record (`status_id: Pending_Activation`) and generates a secure token.
    - Using SMTP from `System_Settings`, it sends an **Activation Email** ("Set your password") AND a **Registration Success Email** (Invoice/Ticket).
    - User clicks link, sets password -> status becomes 'Active'.
  - **Forget Password Flow:**
    - User requests reset -> Backend generates 1-hour token in `Password_Resets` table.
    - Email sent -> User clicks link -> UI displays "New Password" -> Backend hashes password and deletes token.
  - **Change Email Workflow:**
    - User initiates email change -> Verification email sent strictly to the *old* email address to prevent hijacking.
- **3.2 Event Registration Flow**
  - **Dynamic Data Collection:** Uses `Submission_Forms` to link dynamic fields (Dietary Restrictions, Company Name) to the registration step.
  - **E-Commerce Validity:** The frontend UI only displays `Products` (Tickets & Add-ons) if the current time is between the `valid_from` and `valid_until` timestamps.
  - **Bulk Registration (Excel Upload):**
    - Admin uploads CSV/Excel (`first_name`, `last_name`, `email`, `phone`, `ticket_product`).
    - System parses rows (e.g., via pandas/openpyxl). If email is new, creates `Pending_Activation` user.
    - **Bulk Email Logic:** They do *not* receive standard Ala Carte emails. They receive a single **"Invitation Email"** ("You were registered by your admin. Click here to claim your ticket and set your password").
- **3.3 Transfer & Nomination (Ticket Ownership)**
  - **The Concept:** When a ticket is purchased via Excel bulk upload or Ala Carte, it creates a record in the `Event_Tickets` table. 
  - **Database Tracking:** The `Event_Tickets` table explicitly separates the financial buyer (`purchaser_user_id` tied to the `invoice_id`) from the actual participant (`attendee_user_id`).
  - **Nomination Workflow:** 
    - Initially, `purchaser_user_id` and `attendee_user_id` may be the same person (or blank if bought in bulk).
    - If the Purchaser wants to nominate Person A, they open their portal and assign the `attendee_user_id` to Person A. Person A receives an Invitation Email.
    - **Original Payee Control:** Because the ticket is fundamentally linked to the `purchaser_user_id`, Person A *cannot* transfer the ticket to someone else. The control remains solely with the Purchaser.
    - If the Purchaser decides to revoke the ticket and give it to Person B instead, they simply update the `attendee_user_id` to Person B. The system revokes Person A's access and issues a new Invitation to Person B. The original financial records (`Invoices` / `Payments`) remain entirely untouched.

### Sprint 4: Submissions & Review Management
- **4.1 Dynamic Submissions (Form Builder)**
  - **JSON-Schema Configuration:** Admins use a drag-and-drop form builder (e.g., `react-jsonschema-form`) to configure fields, sections, and exact validation rules (regex, min/max, requiredness). This structure is saved into `Submission_Forms.fields_schema_json`.
  - **Drafts & States:** Users fill out the form, which saves directly to `entry_data_json` as a Draft. Upon clicking 'Final Submit', the backend validates the data against the JSON schema. If successful, the Status Engine transitions it to 'Pending_Review'.
- **4.2 Reviewer Workflow (Rules Engine Allocation)**
  - **Configuration:** Admins set global `Review_Configurations` (e.g., required 3 reviews per submission, defining the review time window).
  - **Rule-Based Allocation:** Using the core **Rules Engine**, admins create `Review_Assignment_Rules`. When a submission enters 'Pending_Review', a background task runs the participant's JSON data through the engine. If the `conditions_json` matches (e.g., `category = Healthcare`), it automatically assigns the submission to the eligible reviewer.
  - **Review Execution:** Reviewers grade using their own dynamic form defined in `Review_Forms.fields_schema_json`. Failing to grade within the review window triggers the Workflow Engine to automatically re-allocate the submission.

### Sprint 5: E-Commerce & Invoicing
- **5.1 Financial Management & Invoicing**
  - **Independent Invoicing:** Generates invoices linked directly to Tickets/Products without needing a rigid Sales Order (SO).
  - **PDF Printouts:** Uses the Template Engine to merge invoice data into an HTML template, converting it to a downloadable PDF via a backend library (like WeasyPrint or Puppeteer).
- **5.2 Payment Gateway Integrations**
  - **Configurable Connections:** Admins store encrypted credentials (e.g., Stripe, RazerMerchant) in `Payment_Gateway_Configs`.
  - **Test Connection Feature:** A UI button pings the vendor's authentication endpoint to verify credentials before going live.
  - **Integration Logging (Mandatory):** Every outbound request to a gateway and every inbound webhook is recorded in the `Integration_Logs` table. This provides a critical audit trail for failed payments.
  - **Webhook Automation:** Successful payment webhooks automatically mark invoices as PAID and trigger the Rules Engine to update the user's status to 'Eligible'.

### Sprint 6: Agenda Builder & Real-time Scheduling
- **6.1 Interactive Scheduler (Database & UI)**
  - **Database Mapping:** Uses `Agenda_Sessions` (with a self-referencing `parent_session_id` for nested sub-slots) and `Venues` tables to store timeslots and presenter links.
  - **Drag-and-Drop UI:** Admins visually allocate approved submissions into timeslots on a Calendar/Gantt interface.
  - **Live Subdomain Reflection:** The Agenda Block on the CMS subdomain connects via WebSockets to the backend. It acts like a live airport departure board, reflecting changes instantly to visitors without a page refresh.
- **6.2 Dependency Management & Notifications**
  - **Finish-to-Start Configuration:** In the UI, admins drag a connecting line between Session A and Session B, saving a relationship in the `Session_Dependencies` table.
  - **Auto-Recalculation Engine:** If an admin delays Session A by 30 minutes, the backend recursively queries the dependencies table and auto-shifts Session B (and C, etc.) by +30 minutes.
  - **Template-Driven Notifications:** The recalculation engine triggers a Workflow Event. It loads a custom HTML email from the `Templates` table, injects dynamic variables (e.g., `{{presenter.name}}`, `{{session.start_time}}`), and instantly emails the affected presenters.

### Sprint 7: Event Day Operations
- **7.1 Checkpoint System (QR & Access)**
  - **Configuration:** Admins define Checkpoints (e.g., "VIP Lounge") and configure JSON rules for `allowed_segments` and `entry_type` (Single vs Multiple).
  - **Validation Engine:** When a QR is scanned, the backend validates against User Segment, Payment Status, and Previous Scans.
  - **On-the-spot Resolution:** If a scan is DENIED due to an unpaid status, the scanner UI presents a "Resolve Payment" button deep-linking directly to the user's invoice to collect cash/card instantly.
- **7.2 Hardware Integration (Silent Printing)**
  - **Local Daemon Spooler:** To bypass the browser's "Print Dialog" popup, the registration laptop runs a lightweight local daemon (e.g., QZ Tray). The EMS dashboard sends the PDF/ZPL badge directly to `localhost:8080`, triggering silent, instant printing compatible with any generic printer.
  - **Test Connection:** A UI button pings the local daemon to verify the printer is online before the event starts.
- **7.3 Automated Event Triggers (Cron)**
  - **Time-Based Workflows:** Uses the `Scheduler` engine from Sprint 1. Admins configure a trigger (e.g., "24 hours before start date") to fire an Action.
  - **Template Injection:** The Action loads an email template from the database, injects attendee/presenter details, and dispatches the HTML email automatically.

---

## 2. User Stories

### Core & CRM
- **US-01:** As a Foundryx admin, I want to create a new Event/Project from a template so I can quickly set up checklists and tasks.
- **US-02:** As a Foundryx admin, I want to use a web content builder to drag-and-drop elements and publish a registration website to a subdomain.
- **US-03:** As an admin, I want to check domain availability via a DNS checker within the system.
- **US-04:** As an admin, I want to generate a quotation and share it with the customer to finalize the event requirements.
- **US-21:** As an admin operator, I want an App Store interface to install, upgrade, activate, or deactivate modular features (like the CMS or Finance modules) dynamically.

### Registration & Profile
- **US-05:** As a participant, I want to create one profile that lets me register for multiple events without managing multiple accounts.
- **US-06:** As a participant, I want to securely change my email address with verification sent to my old email.
- **US-07:** As a participant, I want to purchase event tickets and add-ons during their respective validity periods.
- **US-08:** As a participant, I want to transfer my paid registration to another user if I cannot attend.

### Submissions & Reviews
- **US-09:** As an event admin, I want to configure dynamic fields for a submission so I can collect customized data for different events.
- **US-10:** As a submitter, I want to save my submission as a draft and revise it before the submission window closes.
- **US-11:** As an admin, I want to invite reviewers via email so they can automatically get an account and access the assigned submissions.
- **US-12:** As a reviewer, I want to receive automated reminders and escalate submissions if I cannot review them in time.

### E-Commerce & Workflows
- **US-13:** As a participant, I want to view, download, and pay my invoice online using configured payment methods.
- **US-14:** As an admin, I want to set up an automated workflow so that when payment is received, the participant's status is marked as 'Eligible'.
- **US-15:** As an admin, I want to use a template engine to design badges, emails, and QR tickets with dynamic variables.

### Scheduling & Event Day
- **US-16:** As an event coordinator, I want a drag-and-drop Google Calendar-like interface to schedule submissions into time sub-slots and venues.
- **US-17:** As an event coordinator, if a session is delayed, I want the system to push back dependent slots and notify presenters automatically.
- **US-18:** As an event crew member, I want to scan a QR code at a checkpoint and instantly see if the participant is eligible or why they aren't.
- **US-19:** As an event crew member, I want the system to print a physical badge upon successful check-in.
- **US-20:** As a participant lacking payment, I want to be redirected to a payment screen when checked in so I can pay on the spot.

---

## 3. Timeline & Hyper-Accelerated TDD Workflow

**Resource Context:** Single Full-Stack Developer utilizing **Claude Code Max** as the core development orchestrator.
**Aggressive Timeline:** Compressed from 3.5 Months to **8 Weeks (2 Months)** using automated parallelization.

### 3.1 AI-Driven Multi-Agent TDD Workflow
To achieve the 8-week target, you will act as the Product Manager/Orchestrator, using Claude Code Max configured with a multi-agent framework (e.g., CrewAI, LangGraph, or structured Claude prompting) to create a virtual development team.

**The Pipeline Loop:**
1. **Design (Functional Specs):** 
   - *Action:* You provide the user story. A **Spec Agent** generates a strict Markdown Functional Spec detailing API endpoints, DB operations, edge cases, and UI requirements.
2. **Development (Against Specs):**
   - *Action:* A **Developer Agent** (Claude Code Max) reads the Functional Spec and writes the core logic (Metronic UI + FastAPI backend). *Crucially, it builds interfaces and mock data first to unblock parallel testing.*
3. **Code Review:**
   - *Action:* A separate **Reviewer Agent** reads the diffs against the Functional Spec. It strictly checks for architectural compliance, SOLID principles, and security flaws, bouncing it back to the Developer Agent if it fails.
4. **Unit Testing (TDD):**
   - *Action:* A **QA Agent** generates PyTest (FastAPI) and Jest/React Testing Library scripts based *only* on the Functional Spec (preventing biased tests that just mirror the code logic). The Developer Agent must fix code until tests pass green.
5. **Functional / E2E Testing:**
   - *Action:* Playwright or Cypress scripts are generated to test the full User Journey (e.g., creating a lead, paying an invoice) against the deployed local environment.
6. **Build & Deploy:**
   - Automated CI/CD pipelines trigger on passing tests, deploying via Docker to the staging environment.

### 3.2 Compressed 8-Week Timeline
* **Weeks 1-2 (Core, DB & CRM):** Automated setup of DB, Auth, Workflow/Rule/Template engines, and Lead/Project CRM modules.
* **Weeks 3-4 (Registration & Submissions):** User portals, Submission dynamic forms, and Reviewer assignment logic.
* **Weeks 5-6 (CMS Builder & Commerce):** Craft.js/GrapesJS UI integration, Invoicing, and Payment Gateways.
* **Weeks 7-8 (Scheduling, Event Day & QA):** Agenda builder UI, Checkpoint scanners, E2E functional testing fixes, and Launch.
