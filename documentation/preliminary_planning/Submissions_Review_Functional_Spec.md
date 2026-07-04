# Functional Specification: Submissions & Review Workflows

This document details the technical architecture for Sprint 4 (Dynamic Submissions & Review Management), defining how forms are dynamically generated and how the Rules Engine automatically distributes submissions to eligible reviewers.

---

## 1. Dynamic Form Configuration (Submissions)

### 1.1 The Technical Implementation (React JSON Schema)
Instead of hardcoding database columns for every question, the EMS uses a **JSON-Schema Driven UI** (using libraries like `react-jsonschema-form` or `Form.io`).

When an admin configures a Submission Form, they use a drag-and-drop UI to build the form. The output of this UI is a massive JSON object saved into the `Submission_Forms.fields_schema_json` column.

**Schema Example:**
```json
{
  "sections": [
    {
      "title": "Project Details",
      "rows": [
        {
          "fields": [
            {
              "name": "project_category",
              "type": "dropdown",
              "options": ["Healthcare", "Finance", "Tech"],
              "required": true
            },
            {
              "name": "budget",
              "type": "number",
              "validation": { "min": 1000, "max": 50000 },
              "required": false
            }
          ]
        }
      ]
    }
  ]
}
```

### 1.2 Drafts, Validation, & States
* **Drafts:** When a user types into the form, it saves their answers as a JSON payload into `Submission_Entries.entry_data_json`. It remains in the `Draft` state. They can leave and return anytime.
* **Validation:** When they click "Final Submit", the React frontend AND the FastAPI backend run the user's answers against the `fields_schema_json` validation rules. 
* **State Machine Trigger:** If it passes validation, the Status Engine updates the submission from `Draft` to `Pending_Review`. This state change fires a Workflow Trigger to begin the Review Allocation.

---

## 2. Reviewer Configuration & Rules Engine Allocation

To automatically route submissions to the correct reviewers based on what the user answered (e.g., routing a "Healthcare" submission to a "Healthcare Reviewer"), we rely entirely on the **Rule Engine** defined in Sprint 1.

### 2.1 Database Additions
We must add a specific table to store these routing rules:

**`Review_Assignment_Rules` Table:**
* `id`
* `review_form_id` (Which review form they will use to grade it)
* `reviewer_user_id` (The judge/reviewer)
* `conditions_json` (The logical rule the submission must pass to be assigned to this reviewer)

**`Review_Configurations` Table:** (Linked to the Project)
* `id`
* `project_id`
* `required_review_count` (e.g., Every submission must be reviewed by exactly 3 people).
* `window_start_date`
* `window_end_date`

### 2.2 The Allocation Execution (How it works technically)
1. **The Trigger:** A submission transitions to `Pending_Review`.
2. **Rule Evaluation:** A background worker (BullMQ/Celery) fetches all `Review_Assignment_Rules` for that project. It takes the user's `entry_data_json` (The Facts) and runs it through the `json-rules-engine`.
3. **The Condition Match:** The engine evaluates the `conditions_json`:
   ```json
   {
     "all": [
       { "fact": "entry_data", "path": "$.project_category", "operator": "equal", "value": "Healthcare" }
     ]
   }
   ```
4. **The Assignment:** If the rule passes, the system creates a new row in the `Review_Entries` table. It links the `submission_entry_id` to the `reviewer_user_id` with a status of `Pending_Action`.
5. **Enforcing Counts:** The worker repeats this process for other eligible reviewers until it hits the `required_review_count` (e.g., 3 reviewers).

### 2.3 Review Execution
* The Reviewer logs in. They see a list of submissions assigned to them in the `Review_Entries` table.
* When they click "Grade", the system loads the `Review_Forms.fields_schema_json` (which configures what the reviewer sees: e.g., a 1-10 slider for Innovation, a text box for Feedback).
* The reviewer can also see the original Submission Data strictly as Read-Only.
* If they don't complete the review before the `window_end_date`, a scheduled Workflow Action automatically escalates it by re-running the Rules Engine to find an alternate eligible reviewer.
