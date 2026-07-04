# EMS 10-Week Execution Timeline & Architectural Verdict

## 1. Architectural Verdict: Metronic (Next.js) + FastAPI
**Recommendation: HIGHLY RECOMMENDED.** 
This stack is the absolute gold standard for an AI-accelerated SaaS project.
* **Why Next.js + Metronic?** Metronic provides 80% of the enterprise UI boilerplate (data tables, wizards, advanced forms) out of the box. Next.js provides the powerful App Router, which is mandatory for our CMS Subdomain functionality (rendering `event.foundryx.com.my` seamlessly).
* **Why FastAPI?** Python/FastAPI relies heavily on `Pydantic` models. AI coding agents (like Claude) are exceptionally good at writing Python and generating JSON schemas for Pydantic. It also naturally supports the modular "Service-Repository" and Alembic architecture we designed.

## 2. Feasibility Assessment (2.5 Months / 10 Weeks)
**Is it achievable?** Yes, but **only** because you are utilizing the Claude Code Max Multi-Agent TDD workflow. 
For a single human developer, building a Rule Engine, CMS Builder, and WebSockets is a 6 to 9-month endeavor. By having Claude generate the Playwright tests, Pytest suites, and frontend components in parallel, you are essentially deploying a team of 4 senior engineers. 

To achieve this, you must stick rigorously to the timeline below. Do not allow "feature creep" during the 10 weeks.

---

## 3. The 10-Week Execution Timeline (50 Working Days)

### Week 1 & 2: The Core Foundation (Sprint 1)
*The most critical phase. If the base engines fail, the modular apps will fail.*
* **1.1 Infrastructure & DB Schema (2 Days):** Alembic setups, core modular table creation.
* **1.2.1 Workflow Engine (3 Days):** BullMQ/Celery setup, Node chaining logic.
* **1.2.2 Rule Engine (2 Days):** `json-rules-engine` integration for logic trees.
* **1.2.3 Status Machine (1 Day):** Entity lifecycle and transitions.
* **1.2.4 Template Engine (2 Days):** HTML/Handlebars to PDF rendering pipeline.

### Week 3: Core CRM & App Store (Sprint 2a)
* **2.1 CRM Fundamentals (1 Day):** User profiles, Lead/Client Wizard.
* **2.2 Project Management (1 Day):** Event creation, Kanban boards.
* **2.3 Document Management (1 Day):** "Google Drive-ish" folders, file sharing.
* **2.5 Internal App Store (2 Days):** UI for module activation, dynamic router toggling.

### Week 4 & 5: The CMS Engine (Sprint 2b)
*The most frontend-heavy module requiring heavy AI UI generation.*
* **2.4a Base Architecture (5 Days):** Integrating Craft.js/GrapesJS drag-and-drop into Metronic.
* **2.4b Subdomain Routing (5 Days):** Wildcard DNS setup, backend JSON-to-HTML rendering logic for event landing pages.

### Week 6: Registration & Auth (Sprint 3)
* **3.1 Authentication & Profile (2 Days):** Secure email verification, Token-based password resets.
* **3.2 Event Registration (2 Days):** Ala Carte logic, Excel Bulk Upload parsing, E-Commerce validity periods.
* **3.3 Transfer & Nomination (1 Day):** `Event_Tickets` owner vs. attendee separation logic.

### Week 7: Submissions & Reviews (Sprint 4)
* **4.1 Dynamic Submissions (2 Days):** JSON-schema dynamic form builder, Draft states.
* **4.2 Reviewer Workflow (3 Days):** Wiring the Rule Engine to automatically assign submissions to reviewers based on `Review_Configurations`.

### Week 8: E-Commerce & Finance (Sprint 5)
* **5.1 Financial Management (2 Days):** Independent invoicing generation, PDF printouts.
* **5.2 Payment Integration (3 Days):** Strategy pattern for Stripe/PayPal, Test Connection UI, and the mandatory `Integration_Logs` webhook tracking.

### Week 9: Real-Time Scheduling (Sprint 6)
* **6.1 Interactive Scheduler (3 Days):** Drag-and-drop Gantt chart UI, nested sub-slots mapping.
* **6.2 Dependency Management (2 Days):** Finish-To-Start auto-recalculation logic, WebSocket live sync for the CMS, automated delay emails.

### Week 10: Event Day & Launch (Sprint 7 & QA)
* **7.1 Checkpoint System (1 Day):** QR generation, scanner validation engine, On-the-spot payment deep-linking.
* **7.2 Hardware Integration (2 Days):** QZ Tray local daemon setup for silent badge printing.
* **7.3 Automated Triggers (1 Day):** Cron-scheduled reminders via the Workflow engine.
* **Final QA & Security Audit (1 Day):** E2E Playwright suite final execution, penetration testing fixes, staging deployment.
