# AI Agent Orchestration & TDD Guide

This guide details how to technically set up your local multi-agent "virtual development team" using Claude, CrewAI/LangGraph, and Playwright for the FoundryX EMS project.

---

## 1. What is E2E Testing?
**E2E (End-to-End)** testing means testing your application exactly as a real user would experience it. Instead of just testing a backend function, an E2E test opens a real headless browser (like Chrome), navigates to your local React frontend, clicks the "Create Lead" button, types into the input fields, submits the form, and verifies the success message appears. **Playwright** is the industry standard for writing these tests.

---

## 2. Technical Architecture of the AI Team

### You don't use "Extensions" — You use the API
The 5-hour message limit applies to the **Claude Web UI (Claude Pro)**. You cannot build a continuous, autonomous multi-agent loop using the chat interface.

Instead, you use the **Anthropic API** combined with a Python framework like **CrewAI** or **LangGraph**. You run a Python script locally on your Mac, which acts as the orchestrator. This script talks directly to the Claude API. 

### Spawning the Agents (The Setup)
To spawn this team, you will write a single Python application:
1. **Install Dependencies:** `pip install crewai langchain-anthropic playwright pytest`
2. **Setup API Key:** Export your `ANTHROPIC_API_KEY` to your local environment.
3. **Define Agents:** You define Python objects for each agent, assigning them a specific system prompt (their "Role") and their Tools (their "Skills").

```python
# Pseudo-code example of spawning an agent
from crewai import Agent
from langchain_anthropic import ChatAnthropic

# Claude 3.5 Sonnet is the recommended model for coding
llm = ChatAnthropic(model="claude-3-5-sonnet-20240620")

qa_agent = Agent(
    role='Lead QA Automation Engineer',
    goal='Write robust Playwright E2E test scripts based strictly on functional specs.',
    backstory='You are an expert in TypeScript, React, and Playwright testing.',
    tools=[read_file_tool, write_file_tool, run_bash_tool],
    llm=llm
)
```

---

## 3. Handling API Rate Limits (The "5-Hour" Issue)

Because you are using the API, you are bound by API Rate Limits (Tokens-Per-Minute / Requests-Per-Minute), not a 5-hour web UI block. 

To ensure your virtual team runs continuously without crashing when they hit a rate limit, you implement an **Exponential Backoff Automation**.

**How it works:**
Whenever an agent makes an API call, it is wrapped in a retry function (using Python's `tenacity` library). If Anthropic returns an `HTTP 429 Too Many Requests` error, the script intercepts it:
1. It detects the limit was reached.
2. It puts the Python thread to sleep (e.g., `time.sleep(60)`).
3. It wakes up and tries again. 
This allows you to go to sleep while the agents code overnight, automatically pausing and resuming as limits reset.

---

## 4. Writing Playwright Scripts with Claude

Claude is exceptionally good at writing Playwright scripts. The workflow works like this:
1. The **Spec Agent** saves `lead_creation_spec.md`.
2. The **QA Agent** reads that file.
3. The QA Agent uses its `write_file_tool` to generate `tests/e2e/lead_creation.spec.ts`.
4. The QA Agent uses the `run_bash_tool` to execute `npx playwright test`.
5. It reads the terminal output. If the test fails because the Developer Agent hasn't written the UI yet, it waits. If it fails due to a syntax error in the test, it rewrites the test and tries again.

---

## 5. Required Agent "Skills" (Tools)

To make this workflow autonomous, you must equip your CrewAI/LangGraph agents with the following local functions (Skills). Without these, they are just chatbots; with these, they are local developers.

### File System Skills
* **`read_file`**: Allows agents to read existing specs, React components, and FastAPI routes.
* **`write_file`**: Allows agents to create new files (e.g., generating a new `ProjectController.py`).
* **`multi_replace_file_content` / `edit_file`**: Critical for modifying existing code without rewriting the entire file (saves massive amounts of tokens).

### Execution & Testing Skills
* **`run_bash_command`**: The most important skill. Allows the Developer Agent to run `npm run dev` or the QA Agent to run `pytest` and `npx playwright test`. It must return the terminal output (STDOUT/STDERR) back to the agent so it knows if it succeeded or failed.
* **`get_command_status`**: Allows the agent to check on a background command (like a running dev server).

### Architectural Skills
* **`read_database_schema`**: A tool that inspects your PostgreSQL/FastAPI database to let the agent know exactly what columns exist in the `Statuses` or `Projects` tables before writing queries.
* **`git_commit`**: After the Reviewer Agent approves a feature and all tests pass green, a tool to automatically commit the code (`git commit -m "feat: implemented Lead creation wizard"`).

---

## 6. Automated Test Execution Reporting (Documentation)

To ensure you can verify the agent's work without reading raw code, the QA Agent is strictly instructed to generate a **Test Execution Report** in Markdown format after running its Playwright/Pytest scripts. 

You can easily export this Markdown into an Excel/CSV file if needed later. The QA Agent will generate a file (e.g., `docs/tests/US-01_Lead_Creation_Report.md`) structured exactly like a manual testing sheet:

| User Story | Scenario | Precondition | Steps | Expected Result | Actual Result | QA Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **US-01** | Create Client via Wizard | Admin is logged in. No client exists named "Acme". | 1. Go to `/leads/new`<br>2. Click 'Select Customer'<br>3. Click 'Quick Create Client'<br>4. Type 'Acme' | Client 'Acme' is created and auto-selected in the wizard. | Client 'Acme' created. Wizard retained state. | **PASS**. Playwright trace attached. No console errors detected. |
| **US-01** | Wizard Validation | Admin is logged in. | 1. Go to `/leads/new`<br>2. Leave 'Source' blank<br>3. Click 'Next' | UI blocks progression and shows red validation error. | Form blocked, but error message was not visible. | **FAIL**. *Remark:* Developer Agent needs to fix z-index of the toast notification. Sent back to Dev. |

**How the Agent creates this:**
1. The QA Agent reads the Playwright terminal STDOUT (using `run_bash_command`).
2. It parses the pass/fail results.
3. It uses the `write_file` tool to append the test results to the Markdown report table, strictly filling out the `Actual Result` and `QA Remarks` based on the terminal output.
4. As the Orchestrator, you simply review this Markdown table (or copy it to Excel) to verify the system's integrity without ever having to look at the code yourself.

---

## 7. Modular Development Methodology & Agent Coding Guidelines

To ensure the system scales efficiently across tenants, you must program the **Developer Agent** and **Reviewer Agent** with strict architectural constraints in their system prompts. If they do not follow these rules, the Reviewer Agent must reject the code.

### 7.1 Frontend Guidelines (React / TypeScript / Metronic)
* **Atomic Component Design:** Agents must strictly build isolated, reusable UI components. A generic `DataTable.tsx` component should not contain hardcoded logic for fetching "Leads".
* **Separation of Concerns (Custom Hooks):** Business logic and API calls (e.g., Axios/Fetch) must be abstracted into custom hooks (e.g., `useLeads()`). The UI component only receives data via props.
* **Strict TypeScript Interfaces:** Every component must export an explicit interface (e.g., `interface LeadCardProps { name: string; onClick: () => void; }`). The Reviewer Agent will fail any code containing `any` types.
* **Metronic CSS Utility Overrides:** Agents are prohibited from writing raw CSS or injecting `<style>` tags. They must strictly utilize Metronic's predefined utility classes.

### 7.2 Backend Guidelines (FastAPI / Python)
* **Service-Repository Pattern:** Agents must never write raw SQL or DB logic inside the FastAPI router. The architecture is strictly separated:
  1. **Router Layer (`/routers`):** Only handles HTTP request validation (Pydantic models) and HTTP responses.
  2. **Service Layer (`/services`):** Handles core business logic, workflow triggers, and rule engine evaluations.
  3. **Repository Layer (`/repositories`):** Handles pure SQLAlchemy database queries.
* **Dependency Injection:** Agents must heavily utilize FastAPI's `Depends()` method to inject database sessions and services. This is critical for the QA Agent, as it allows them to inject "Mock" databases during Unit Testing.

**How to Enforce This Technically:**
In your Python orchestrator, you add this explicitly to the Reviewer Agent's prompt:
> *"You are a strict Software Architect. You must fail the code review if the Developer mixes DB queries into the router, or if a React component contains Axios calls instead of a custom hook."*

### 7.3 Modular Database Migration Strategy (Alembic)
To truly achieve a "Plug-and-Play" modular architecture, you must handle database migrations carefully.

**Approach A: Module-Specific Version Tables (Recommended for App Stores)**
Instead of one global `alembic` folder, every module maintains its own migration history:
1. **Directory Structure:** Each module has its own `/alembic/versions` folder.
2. **Migration Tracking:** You configure `env.py` so that the Finance module tracks its migrations in a table called `alembic_version_finance`.
*Why it's recommended:* If an operator clicks "Uninstall Finance Module", the system can easily drop the finance tables and the `alembic_version_finance` table, leaving the core system 100% clean.

**Approach B: Single Table using Alembic Branching (The 1-Table Alternative)**
If you strictly want to maintain only **1 single `alembic_version` table** in the database, Alembic supports this natively using **Branching**, rather than adding an `app` column.
1. All modules share the same `alembic_version` table.
2. When creating a migration for a module, you create a new "branch" (e.g., `alembic revision --branch-label=finance`).
3. The single `alembic_version` table will simply hold multiple rows simultaneously (one row representing the "head" version of the Core, one row for Finance, one row for CMS).
*Drawback:* It makes uninstalling a module slightly messier, as the system has to manually splice the Alembic history tree to remove the branch.

This exact constraint must be added to the Developer Agent's prompt: *"When modifying database schemas, you must strictly follow the defined Alembic modular tracking approach so core migrations are never intertwined with modular app migrations."*
