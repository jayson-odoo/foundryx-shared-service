# 71 - Link PO: truthful read-back and resume after a stuck write (PO-LINK-STUCK-RECONCILE-B)

Shared Service half of the CRM lane PO-LINK-STUCK-RECONCILE. Work in progress; sections fill in as each slice lands.

1. split_link read-back comparator accepts what AutoCount derives (s5).
2. split_link new tied row DeliveryDate = the SO line's date, never `docDate` (s5).
3. Resume / same-key resend of a parked split_link re-verifies; operator "close as superseded" (s2).
4. AutoCount SQL timeout = unknown, then a read-back decides (s3/s4).
5. A link to an SO line already tied from the same PO row is refused `ROW_ALREADY_LINKED` (s2).
