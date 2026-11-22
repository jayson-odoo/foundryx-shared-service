# App Review pack: 5 lead permissions on "Foundryx WA App" (owner submits)

Status 15/11/2026, from `S-META-result.md`:

- The use case "Capture & manage ad leads with Marketing API" is added. All five permissions read "Ready for
  testing" (Standard access).
- Business Verification: Verified 03/11/2025.
- Real API calls on all five were made during S-META on the Foundryx Page, which satisfies Meta's "at least one
  call" precondition (unconfirmed whether the counter has updated yet).
- The wait after submission is about 20 days; the owner accepts it.

## Before you press Submit (owner, about 10 minutes)

1. **Rename the app** (App settings > Basic > Display name). Recommended: "Foundryx" (plan 64 O-2). It shows on every
   customer's Facebook consent screen.
2. **App settings > Basic:** check the Privacy Policy URL and Data Deletion URL are set and public. Crew updates the
   policy text to mention lead data (what, why, 180 days, deletion) before submission.
3. App category: Business.

## Per-permission notes (paste into each "How will your app use this permission" box)

**`pages_show_list`**
> After a business signs in with Facebook inside our CRM, we list the Facebook Pages they manage so they can choose
> the Page whose lead ads should send leads to their CRM. We store only the chosen Page's id and name.

**`pages_manage_metadata`**
> We subscribe the chosen Page to our app's leadgen webhook so each new lead form submission notifies us. We add
> only the leadgen field and never change other Page settings. The business can disconnect at any time, which
> removes our subscription.

**`leads_retrieval`**
> When a leadgen webhook arrives, we read that lead's answers (name, phone, email and the form's custom questions)
> and deliver them to the same business's CRM as a new sales lead. Leads are stored encrypted and deleted after
> 180 days. Leads are never shared with any other business.

**`pages_read_engagement`**
> We read the chosen Page's lead forms and their questions so the business can map each question to a CRM field,
> and so leads from forms created later are picked up automatically.

**`pages_manage_ads`**
> Meta requires this permission together with leads_retrieval to read the full lead data from the Page's lead ad
> forms. We use it only to read leads and lead forms; we never create, edit or pay for ads.

## Screencast (one video for all five, 2-3 minutes; crew scripts, owner records)

Record after lane 5 or 6 so the real wizard shows. Until then the prototype API flow is not reviewable, so use the
real screens.

1. Sign in to the CRM test company (EcoHub). Go to Company Settings > Lead Capture > Connect a source > Facebook.
2. "Continue with Facebook". Show the consent screen listing all five permissions. Continue.
3. Pick the Foundryx Page (pages_show_list). Choose "All forms" and show the form list (pages_read_engagement).
4. Field mapping screen. Connect, which subscribes the Page (pages_manage_metadata).
5. Open Meta's Lead Ads Testing Tool in a new tab, pick the Page and form, and submit a test lead.
6. Back in the CRM, the lead appears in Leads with its answers (leads_retrieval, pages_manage_ads).
7. Disconnect the source.

English captions on each step. Test data only.

## Reviewer instructions (paste into "Testing instructions")

> 1. Sign in at <EcoHub test URL> with <reviewer test login> (a test company with fake data only).
> 2. Go to Company Settings > Lead Capture and click Connect a source, then Facebook.
> 3. Continue with Facebook using your own account and pick a Page you manage that has a lead form.
> 4. Choose All forms, keep the suggested field mapping and click Connect.
> 5. Submit a test lead with https://developers.facebook.com/tools/lead-ads-testing on that Page and form.
> 6. The lead appears under Leads within about a minute.

Crew creates the reviewer test login (fake data) and fills the placeholders. No Facebook password is ever shared.

## Not in this submission

- `business_management` and `ads_management`: S-META F3 left these open. Add them only if a later lane proves them
  necessary.
- WhatsApp is already approved (S-META F3: `whatsapp_business_management` and `whatsapp_business_messaging` are
  approved, so BL-017 is done for WhatsApp).
- Messenger needs `pages_messaging`, which the app does not have (F3), so Messenger cannot work on this app today.
  That is a separate backlog item, outside this pack.
