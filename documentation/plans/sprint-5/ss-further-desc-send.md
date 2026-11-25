# SS-FURTHER-DESC-SEND - raw FurtherDescription on SO + PO lines, re-send path

Lane: SS-FURTHER-DESC-SEND (pairs with the CRM lane RTF-FURTHER-DESC-RENDER).

## Goal
1. Canonical SO lines AND PO lines carry the RAW AutoCount `FurtherDescription`
   (RTF, embedded images included) byte-for-byte, under a size cap sized for the
   largest seen value (~1.2 MB on db3). Additive wire field, contract-gated.
2. A re-send/backfill path re-emits existing SO/PO documents (all, or by date
   range) so the CRM re-ingests them: batched, rate-limited, resumable.
3. No change to Link PO writes (PR #354 rules stay).

Status: in progress. Details filled in as the slice lands.
