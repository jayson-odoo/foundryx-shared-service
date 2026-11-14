# S-META: owner steps (about 15 minutes)

What crew already read with the app's own key (no owner click, 14/11/2026 ~23:30):

- The app has **no Page webhook at all** today. Its only webhook is WhatsApp (`whatsapp_business_account`: messages,
  phone_number_name_update, message_template_status_update). Adding a Page webhook for the test touches nothing that
  runs today.
- The app's approved permissions are only `email`, `public_profile`, `whatsapp_business_management`,
  `whatsapp_business_messaging`. None of the Page or lead permissions is on the app yet, so step 1 adds them.

Never paste a token into a chat, PR, comment or screenshot. Steps 3 and 4 put it straight into a private file.

## 1. Add the lead permissions to the app (2 min)

1. Open developers.facebook.com/apps and click **Foundryx WA App**.
2. Left menu: **Use cases** > **Add use case**.
3. Pick the use case whose list shows `leads_retrieval` (Meta names it like "Capture and manage ad leads"). Add it.
4. In that use case click **Customize** and press **Add** next to each of: `leads_retrieval`, `pages_manage_ads`,
   `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`. Standard access is enough; do not submit
   anything for review.
5. Tell crew the exact use case name you picked.

## 2. A test Page inside the "Foundryx" portfolio (3 min)

The portfolio that owns Foundryx WA App is **"Foundryx"** (not "Foundryx Jayson"). It has the WhatsApp numbers, the
app, the WhatsApp dataset and the ad account "Foundryx Ads Test", but **no Facebook Page**. The system user in step 3
can only be given a Page that sits in this same portfolio, so the test Page goes there.

1. Open business.facebook.com/settings. Top left, switch the portfolio to **Foundryx** (not "Foundryx Jayson").
2. **Accounts** > **Pages** > **Add** > **Create a new Page**.
3. Page name **Foundryx Leads Test**, category **Software** (any business category works) > **Create Page**.
   (If you would rather use an existing Foundryx Page: **Add** > **Add a Page** and pick it instead.)
4. Click the new Page in the list. Tell crew the **ID** shown under its name (a number; it is public).

No form needed: crew creates the test forms through the API once step 3 is done. If that is refused, crew sends you
4 clicks to create one in Meta Business Suite.

## 3. System-user key for the Page (5 min) - this answers decision 2

1. Stay in business.facebook.com/settings with the **Foundryx** portfolio selected.
2. **Users** > **System users**. Pick an existing system user, or **Add**: name `leads-test`, role **Admin**.
3. **Assign assets** > **Pages** > **Foundryx Leads Test** > switch on **Full control** (or at least Content,
   Leads and Ads) > **Save**.
4. **Assign assets** > **Apps** > **Foundryx WA App** > **Manage app** > **Save**.
5. **Generate new token** > App **Foundryx WA App** > expiry **Never** > tick `leads_retrieval`,
   `pages_manage_ads`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement` (leave
   `business_management` unticked; crew tests whether it is needed) > **Generate token** > **Copy**.
6. On the Mac terminal run exactly:
   `pbpaste > ~/.config/crew/meta-sysuser-token && chmod 600 ~/.config/crew/meta-sysuser-token && pbcopy </dev/null`

## 4. One Facebook sign-in (3 min) - the person-based key, to compare

1. Open developers.facebook.com/tools/explorer.
2. **Meta App**: Foundryx WA App. **User or Page**: User Token.
3. **Add a permission**: the same five as step 3.5. Click **Generate Access Token**.
4. In the Facebook window: pick **Foundryx Leads Test** (and the Foundryx business if it asks) > **Continue** >
   **Save**.
5. Click the copy icon next to the token, then on the Mac terminal run exactly:
   `pbpaste > ~/.config/crew/meta-user-token && chmod 600 ~/.config/crew/meta-user-token && pbcopy </dev/null`

## 5. Your yes for the test webhook (0 min, a reply)

Crew adds a **Page** webhook with the one field `leadgen` to Foundryx WA App by API, pointed at a temporary test
address on this Mac, for the test only. Afterwards crew removes it again, so the app is back to today's state (no
Page webhook). WhatsApp is not touched.

## 6. Lead Ads Testing Tool (3 min, after crew says "ready")

1. Open developers.facebook.com/tools/lead-ads-testing.
2. Page: **Foundryx Leads Test**. Form: **S-META test 1** (crew creates it).
3. If a lead is listed, click **Delete lead**. Then **Create lead**.
4. Click **Track status** and tell crew what the row for Foundryx WA App says (for example "success").
