# FEEDBACK-TEST-BOARD-LINK acceptance criteria (shared-service slice)

Owner ruling 17 Nov ~01:15: "let's do (a) la, actually i want the console filing to be like a real filing also".
Context: owner 17 Nov ~00:55 "it should be every filing, standardized": every feedback filing reply carries the
reporter's personal PUBLIC board link (CRM lane FEEDBACK-PUBLIC-LINK-CRM). Until this slice a Chatbot Console test
filing (`is_test`) never minted one (`feedback_links.mint_board_link` returned `None`), so the Console reply fell back
to the per-item track link.

Amends AC-FB-20 / AC-FB-25 / AC-FB-32 of `acceptance-criteria.md` for TEST items only. Real items are unchanged.
Tags: [BE] backend pytest.

## A. Link minting
- **AC-TB-01 [BE]** Given a test idea whose submitter contact is in the idea's tenant, `mint_board_link(idea)`
  returns that contact's personal board link opening the idea (same shape as a real filing:
  `{base}/public/feedback/board/{linkToken}/{ideaNumber}`), and the one-shot API with `reply_to_submitter: true`
  returns it as `board_url`.
- **AC-TB-02 [BE]** A test idea with no same-tenant contact still gets `None` (unchanged).

## B. The reporter's own board shows their test items
- **AC-TB-10 [BE]** On a contact link, the reporter's own test items (submitter = the link's contact or a same-phone
  sibling) are in All, My requests, the Roadmap and detail (opened by number), like their real items.
- **AC-TB-11 [BE]** On another contact's link, the test item is absent from All, My requests, Roadmap (cards and
  column counts) and detail (404), and cannot be upvoted or commented on.
- **AC-TB-12 [BE]** Staff and CRM-embed portal sessions still never see test items (unchanged).
- **AC-TB-13 [BE]** A test item never appears in the public changelog of any viewer, including its reporter.

## C. Nothing goes to customers for test items (unchanged, guarded)
- **AC-TB-20 [BE]** A status change on a test item still never pokes the CRM (no WhatsApp/status message pushed);
  the status event stays flagged `is_test` (default-excluded from the CRM pull). The event's `board_url` is now the
  reporter's link, like a real event.
