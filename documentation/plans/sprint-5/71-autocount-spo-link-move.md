# 71 - AutoCount: move / split an SPO line onto another PO line (SPO-LINK-PO-SS)

Status: Plan (draft). Partner lane: CRM SPO-LINK-PO.

## Contract (from the CRM plan, agreed shape)

`POST /api/v1/autocount/spo-links/move` - same envelope as `/po-links`
(Idempotency-Key, `X-Request-ID`, `outcome` answer).

```
{ companyCode, spoDocKey, spoDtlKey, toPoDocKey, toPoDtlKey, qty }
-> { outcome: "done"|"refused"|"unknown",
     moved: { spoDtlKey, fromPoDtlKey, toPoDtlKey, qty },
     remainder: { spoDtlKey, poDtlKey, qty } | null,
     code?, message? }
```

- qty < open qty of the SPO line -> split; the rest stays on the old PO line.
- qty >= open qty -> whole line moves, `remainder: null`.
- A refusal changes nothing. No SPO line is ever left without a PO line.
- Target PO line: same product, any supplier, not fully received. A PO line linked
  to another SO may be the source (old PO keeps its SO link).

Design details follow in the next commits.
