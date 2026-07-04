# Functional Specification: E-Commerce & Payment Integration

This document details the technical architecture for Sprint 5, focusing on how the system dynamically handles payment gateways, webhook logging, and invoice generation.

---

## 1. Configurable Payment Gateway Architecture

To ensure the system can support multiple payment vendors (e.g., Stripe, PayPal, RazerMerchant) and allow each Event/Project to configure its own credentials, we implement the **Strategy Pattern** backed by database configuration tables.

### 1.1 Database Configuration Tables
**`Payment_Gateway_Configs` Table:**
* `id`
* `project_id`
* `vendor_name` (e.g., 'STRIPE', 'SENANGPAY')
* `credentials_json` (Encrypted JSON containing `api_key`, `secret_key`, `merchant_id`)
* `is_active` (Boolean)
* `is_test_mode` (Boolean)

### 1.2 The "Test Connection" Feature
In the admin UI, after entering the credentials (e.g., Stripe API keys), the admin can click "Test Connection".
* **Backend Action:** The FastAPI backend reads the `credentials_json`, decrypts it, and fires a lightweight API call to the vendor's authentication/ping endpoint (e.g., `GET https://api.stripe.com/v1/balance`).
* **Result:** If it returns a `200 OK`, the UI displays a green "Connection Successful" badge, giving the admin confidence before going live.

### 1.3 The Strategy Pattern Implementation
The backend codebase will have a folder `/services/payment_gateways/` containing separate adapter classes for each vendor (`StripeAdapter`, `SenangPayAdapter`). 
When a user clicks "Pay", the system reads the active `Payment_Gateway_Configs` for that event, dynamically loads the correct Adapter, passes the encrypted credentials to it, and generates the payment checkout link.

---

## 2. Integration Logging (Mandatory Auditing)

Payment integrations are notorious for failing silently. To combat this, **every single HTTP request** sent to a payment gateway, and **every Webhook** received from them, MUST be logged.

**`Integration_Logs` Table:**
* `id`
* `project_id`
* `integration_type` (e.g., 'PAYMENT_STRIPE', 'DNS_CHECKER')
* `direction` (Enum: `OUTBOUND_REQUEST`, `INBOUND_WEBHOOK`)
* `endpoint_url` 
* `request_payload_json` (Sanitized: API keys and passwords masked)
* `response_payload_json`
* `http_status_code`
* `created_at`

*Developer Agent Constraint:* The AI Developer must be instructed to wrap all external `httpx` or `requests` calls in a custom `IntegrationLogger` dependency that automatically writes to this table. If a webhook fails to process a payment, the admin can look at the `Integration_Logs` table to see the exact JSON error returned by Stripe.

---

## 3. Invoicing & Printouts

### 3.1 Invoice Generation
When an Ala Carte registration or Bulk Upload is finalized, the system generates an `Invoices` record. 
It does *not* rely on a Sales Order (SO). The invoice is directly tied to the `Event_Tickets` or `Products` purchased.

### 3.2 PDF Printouts (The Template Engine)
To support downloadable PDF invoices, we leverage the **Template Engine** built in Sprint 1.
1. The admin configures an "Invoice Template" using HTML and CSS in the CMS builder.
2. It includes Handlebars variables like `{{client.name}}`, `{{invoice.amount}}`, and `{{invoice.items}}`.
3. When a user clicks "Download Invoice", the FastAPI backend:
   - Fetches the invoice data from the DB.
   - Injects the data into the HTML template.
   - Uses a headless browser library (like `Puppeteer` or `WeasyPrint` in Python) to convert the HTML into a highly-styled PDF on the fly.
4. The PDF is returned to the user's browser for download or print.

---

## 4. Post-Payment Workflow (Webhooks)

When a participant completes payment on the vendor's checkout page:
1. The vendor sends a POST request to our webhook endpoint (`/api/webhooks/stripe`).
2. The `IntegrationLogger` immediately saves the raw payload to `Integration_Logs`.
3. The system verifies the webhook signature using the `credentials_json`.
4. It updates the `Payments` table status to `SUCCESS`.
5. It updates the `Invoices` table status to `PAID`.
6. **Rule/Workflow Engine Trigger:** The payment success triggers an action that updates the user's `User_Project_Roles.status_id` from `Pending_Payment` to `Eligible`, granting them their physical ticket/QR code.
