# Plan 38 gap 6: guide corrections for voice, interactive replies and endpoint re-enable

UAC: `38-gap6-guide-acceptance-criteria.md`. Size S, guide only. Branch `crew/ss-fuji-gap6`.

Re-checked against main 78e15118: self-serve re-enable of an `AUTO_DISABLED` endpoint already works with the API key and is documented (`POST /webhooks/{id}/enable`); what is missing is the reset rule, the no-replay rule and the endpoint fields. Webm voice input and the `INTERACTIVE_REPLY` payload are not documented, and the send table promises a `422 transcode_failed` that the send call never returns.

Order: tester writes guide tests (red) for AC-38-110..115 beside the existing guide tests; guide-writer edits the guide until green, checking each sentence against the code; reviewer checks every sentence against the code it cites.

Publishing to Outline: the repo has no Outline tooling; publishing is a crew or owner step after merge.

The guide changelog also gets a row from gap 4 (#175); whichever merges second keeps both rows.
