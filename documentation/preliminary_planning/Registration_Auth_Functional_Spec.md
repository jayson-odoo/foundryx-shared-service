# Functional Specification: Registration & Authentication

This document details the technical architecture, database schema additions, and step-by-step logic required to execute Sprint 3 (Authentication & Registration Flow).

---

## 1. E-Commerce Configuration (Tickets & Add-ons)

To handle dynamic pricing and add-ons, we must introduce a specific table to the schema to track products and their validity periods (e.g., "Early Bird Ticket").

**New Schema: `Products` Table**
* `id` (UUID)
* `project_id` (FK to Projects)
* `name` (e.g., "Early Bird Registration", "Gala Dinner Add-on")
* `type` (Enum: `TICKET`, `ADD_ON`)
* `price` (Decimal)
* `valid_from` (Timestamp)
* `valid_until` (Timestamp) - *Controls when this product disappears from the web builder UI.*
* `stock_limit` (Integer, nullable for unlimited)

**Information Collected During Registration:**
Instead of hardcoding fields, we link a dynamic form. We use the **`Submission_Forms`** engine from Sprint 1, creating a form of type `REGISTRATION` for the specific project. 
*Standard Fields Collected:* First Name, Last Name, Email, Phone.
*Dynamic Fields (JSON):* Dietary Requirements, Company Name, Job Title, T-Shirt Size (if add-on purchased).

---

## 2. Ala Carte (Self-Serve) Registration Flow

When a single user visits the event subdomain to register themselves:

1. **Cart Selection:** User selects a `TICKET` and optional `ADD_ON` products. The UI only displays products where `Current_Time` is between `valid_from` and `valid_until`.
2. **Form Submission:** User fills out the standard and dynamic fields.
3. **Account Check:** Backend checks if the `Email` exists in the `Users` table.
   * *If NEW user:* Creates `Users` record. Status: `Pending_Activation`. Generates Activation Token.
   * *If EXISTING user:* Skips account creation.
4. **Project Linking:** Saves the registration record to `User_Project_Roles`.
5. **Email Triggers (via Workflow Engine):**
   * *If NEW user:* Sends **Activation Email** ("Click here to activate your account and set a password").
   * *Always:* Sends **Registration Success Email** ("You are registered for [Event Name]! Here is your invoice/receipt").

---

## 3. Bulk Registration Flow (Excel Upload)

For corporate sponsors or admins registering groups at once.

1. **The Excel Format:** The system provides a downloadable `.csv` or `.xlsx` template. 
   * *Columns:* `first_name`, `last_name`, `email`, `phone`, `ticket_product_name`.
2. **Upload & Parse:** Admin uploads the file. FastAPI parses it via `pandas` or `openpyxl`.
3. **Processing Loop:** For each row:
   * System checks if `email` exists.
   * If not, it creates the User profile (Status: `Pending_Activation`) and generates an Activation Token.
   * It maps them to the event in `User_Project_Roles`.
4. **Email Triggers for Bulk:**
   * They do **NOT** receive standard activation emails.
   * Instead, the system sends an **"Invitation Email"**. ("You have been registered for [Event Name] by your administrator. Click here to set your password and access your tickets").
   * This handles both activation and password creation in one click.

---

## 4. Authentication Workflows

### 4.1 Activation Flow (New Users)
1. User clicks the secure link in their email: `https://[event].foundryx.com.my/activate?token=ABC123XYZ`.
2. The UI validates the token with the FastAPI backend.
3. If valid, the UI displays a "Set Your Password" screen.
4. User submits the password. Backend hashes it (bcrypt), updates the `Users` table password field, sets `status_id` to `Active`, and invalidates the token.

### 4.2 Forget Password Flow
1. User clicks "Forgot Password" on the login screen and submits their email.
2. Backend checks if the email exists. (For security, if it doesn't exist, it still returns "If an account exists, a link has been sent" to prevent email scraping).
3. Backend generates a 1-hour expiration token and saves it to a new `Password_Resets` table (`id`, `user_id`, `token`, `expires_at`).
4. System sends the "Password Reset" email.
5. User clicks link: `https://[event].foundryx.com.my/reset-password?token=DEF456`.
6. UI displays the "New Password" form.
7. Backend hashes the new password, updates the user, and deletes the token from `Password_Resets`.
