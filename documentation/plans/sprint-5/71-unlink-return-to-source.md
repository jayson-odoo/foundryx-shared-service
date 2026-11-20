# 71 - Unlink returns the quantity to its source PO row (returnToDtlKey)

Lane UNLINK-RETURN-TO-SOURCE-SS (SS half of the CRM lane UNLINK-RETURN-TO-SOURCE).

Status: Plan (stub - the CRM lane's contract is being read; this file is replaced by the full plan).

## Ask

`po-links/unlink` accepts an optional `returnToDtlKey`. When given and that row is on the same PO,
open, the same item and not tied to another SO, the unlinked quantity merges back into it
(qty += n) and the tied row is removed in ONE AutoCount PO edit. Otherwise the unlink falls back to
today's pool behaviour (plan 66) and returns a warning code saying why.
