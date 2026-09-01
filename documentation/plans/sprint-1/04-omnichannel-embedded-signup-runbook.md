# Embedded Signup - Go-Live Runbook (Route A: Foundryx = Meta Tech Provider)

The code path is built (frontend SDK + backend exchange). It runs in **simulated**
mode until the Meta app env vars are set, then flips to the **real** Meta Embedded
Signup popup automatically - no code change.

## 1. One-time Meta setup (you/CEO - outside code)
1. **Create a Meta app** at developers.facebook.com (Business type). Can be under the CEO's Meta account.
2. Add products: **WhatsApp** and **Facebook Login for Business**.
3. Under WhatsApp → ensure the CEO's number's **WABA** is in a **Business Manager** you control.
4. Create an **Embedded Signup configuration** (WhatsApp → Embedded Signup / Configurations) → note the **config_id**.
5. From App Settings → Basic: note **App ID** + **App Secret**.
6. **Dev Mode (test now, no review):** add the people who will test as **app Admin/Tester** (App Roles). The CEO (who owns the number's Business) logs into the popup.
7. **Public rollout (later):** Business Verification + App Review for Advanced Access on `whatsapp_business_management` + `whatsapp_business_messaging` (BL-017). Not needed for your own number in Dev Mode.

## 2. Env vars to flip it live
**Backend** (`service_backend/.env`):
```
META_APP_ID=<app id>
META_APP_SECRET=<app secret>
META_ES_CONFIG_ID=<embedded signup config id>
META_GRAPH_VERSION=v19.0
OMNICHANNEL_FERNET_KEY=<run: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
```
**Frontend** (`service_frontend/.env.local`):
```
NEXT_PUBLIC_META_APP_ID=<app id>
NEXT_PUBLIC_META_ES_CONFIG_ID=<embedded signup config id>
NEXT_PUBLIC_META_GRAPH_VERSION=v19.0
```
Restart backend; rebuild + restart frontend (`npm run build && npm start`). The wizard now opens the **real** Facebook popup.

## 3. What happens live
1. Tenant clicks **Connect with Facebook** → Meta JS SDK popup (`FB.login`, your `config_id`).
2. Tenant logs into Facebook, picks/registers their WhatsApp number → Meta returns an **auth code** + `waba_id` + `phone_number_id`.
3. Frontend POSTs to `POST /omnichannel/onboarding/oauth-callback`.
4. Backend `WhatsAppCloudAdapter.exchange_code` swaps the code for a **permanent token** (real Graph call), `fetch_phone_details` resolves the display number + verified name, the channel is created (token Fernet-encrypted), webhook subscribe is attempted.
5. **Test connection** then pings `graph.facebook.com/{phone_number_id}` for real.

## 4. Gotchas
- The number must be a **Cloud API** number on a WABA your Business controls; an already-in-use personal/another-platform number may need migration in Meta first.
- Dev Mode restricts Embedded Signup to users with an **App Role** - add the tester.
- Sending/receiving actual messages (beyond connect + test) is **Plan 05**.
