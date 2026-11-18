# Plan 68 - Google sign-in in the hosted wizard: acceptance criteria

Plan: `68-lead-capture-google-signin.md`. Tags: [BE] pytest, [FE] vitest, [E2E] browser real clicks, [T] owner hand
test. Every Google call is an httpx MockTransport in tests; simulated mode (no `GOOGLE_ADS_CLIENT_ID`) makes no
network call. Depends on L5-GOOGLE (AC-64-40/41/44) for the receiver.

## A. Channel and sign-in
- AC-68-01 [BE][FE] The Channel step offers Google only when the server has a Google OAuth client (or is simulated);
  otherwise Google is not listed.
- AC-68-02 [FE] Choosing Google renames the steps to Channel, Sign in, Account, Forms, Fields, Test, and the Sign in
  question reads "Sign in to Google".
- AC-68-03 [FE] "Continue with Google" opens Google's sign-in in a popup with a fresh random `state`, the `adwords`
  scope, offline access and consent prompt; a code relayed with another `state` is ignored (same popup function
  as Facebook).
- AC-68-04 [BE] The code is exchanged server-side; the refresh token is stored Fernet on the session row and never
  returned; the response holds only account ids + names.
- AC-68-05 [BE][FE] Declining the Google Ads permission shows E1 in Google wording, with "Try again".
- AC-68-06 [BE] A Google login older than 30 minutes, or an undecryptable one, answers `LOGIN_REQUIRED` and the
  wizard returns to Sign in.

## B. Account and forms
- AC-68-10 [BE][FE] The Account step lists only Google Ads accounts the person can reach; one account is chosen
  automatically and folded as "(the only account you can reach)".
- AC-68-11 [BE] An account id that is not in the signed-in person's list answers 404 and does nothing.
- AC-68-12 [BE][FE] The Forms step lists the account's lead forms by name. None = warning + guide + "Check again".
  Continue is blocked until one form is ticked. "All forms, including new ones" is not offered for Google.
- AC-68-13 [BE] Connect creates one Google source through the same source function the guided path uses and writes
  our inbound URL + the source key into every ticked form.
- AC-68-14 [BE][FE] A form Google refuses is named with a plain reason and "Try again"; the other forms connect.
- AC-68-15 [BE] A second wizard on the same account + form never takes over an existing source (409, as Facebook).

## C. Fields, test, done
- AC-68-20 [BE][FE] The Fields step lists each ticked form's questions with a searchable target, standard
  questions matched automatically (full name, email, phone), as AC-64-24.
- AC-68-21 [FE] The Test step for Google shows the guide for Google's "Send test data" and passes when the test
  lead arrives (AC-64-41 `is_test`).
- AC-68-22 [FE] The done screen names the Google Ads account, the forms, who signed in and when (dd/mm/yyyy, h:mm
  am/pm), and posts `lead-capture:done` to the return origin only.

## D. Own-wizard API, isolation, docs
- AC-68-30 [BE] The gateway offers the Google login door with a `loginId`, scoped to the key's tenant; another
  tenant's `loginId` is 404.
- AC-68-31 [BE] The wizard token reaches only this session's Google login and source; every other route is 401/403.
- AC-68-32 [BE] The consumer guide section 7 names every new route (AC-64-66 test).

## E. Quality gate
- AC-68-40 [E2E] The simulated Google path end to end by real clicks at 375 px and 1280 px, light and dark, no
  horizontal scroll, tenant branding, the word "Foundryx" nowhere.
- AC-68-41 [E2E] Every step ends in content, empty, or an error with "Try again"; nothing hangs.
- AC-68-42 [T] Owner hand test from the test-consumer page on the crew test copy (simulated).
- AC-68-43 [T] Live check against a real Google Ads test account after S-GOOGLE (DEFERRED until owner Google setup).
