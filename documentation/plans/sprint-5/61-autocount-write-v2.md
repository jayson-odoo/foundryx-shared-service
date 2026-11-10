# Plan 61: AutoCount write API v2 (vendor update 10 Nov 2026)

Lane SS-AC-WRITE-V2, branch `crew/ss-ac-write-v2`, size M, backend only. UAC: `61-autocount-write-v2-acceptance-criteria.md`.
Builds on plan 55 (`55-autocount-write-link*.md`) and plan 57 (`57-autocount-write-qtso*.md`).

## 1. Why

The AutoCount vendor changed the hapi write API on 10 Nov 2026 (condensed spec, PII-free:
`crew/state/inbox/autocount-api-10nov.md`, outside the repo):

- One PUT can delete a row (`FullTransferOption "D"` on its DtlKey) and add a new row (DtlKey 0) with or without
  `FromDocType / FromDocNo / FromDocDtlKey`. A row's link can never change in place, so unlink, link of a whole row,
  relink / move and delete line all become ONE PUT.
- Cancel is `DELETE /Cancel<Doc>bydocno?DocNo=<no>` (no body).
- One document is read with `GET /<Doc>bydocno?DocNo=<no>`.
- Owner answers 10 Nov: a PUT that omits existing rows KEEPS them; "D" on a transferred row returns the qty to the
  source document. Every other API question is answered by db3 probes in this lane (section 3), never the owner.

## 2. Gap map (origin/main ba13b207, wb = `service_backend/modules/autocount/write_back/`)

- Paths: `wb/doc_kinds.py:37-51`, `wb/constants.py:5-11`. Delete line / delete doc use placeholder DELETE paths marked
  UNVERIFIED AQ23 (`wb/doc_kinds.py:4-5,33-34`). No bydocno GET. No RQ kind.
- Unlink PUTs the row with link fields blanked (`wb/payloads.py:153-156,302-312`); db3 ignored it, refused at
  `wb/service.py:455-460`, `wb/capabilities.py:16-19`. Whole-row link refused VENDOR_UNSUPPORTED (`wb/service.py:541-543,610-611`).
  Relink = delete_line + add_line + location move (`wb/operations.py:594-708`), refused (`:375-377`).
- Cancel = PUT header `Cancelled "T"` (`wb/payloads.py:573-581`), ignored by db3, switched off; gateway answers
  VENDOR_UNSUPPORTED (`write_v1.py:411`). `wb/client.py:37` rejects a `?` in the path; `wb/client.py:85` always sends a JSON body.
- Every write is wrapped by a by-date day-list read filtered on DocKey (`wb/operations.py:422-432`,
  `wb/primitives.py:428-448,549-565`).
- Edits send only changed rows (`wb/payloads.py:517-555`); QT rows never set `FullTransferOption` (`wb/payloads.py:425-435`).

## 3. db3 probes (before any code; results drive section 4 and the capability table)

Run tag `FXT-1110a-`, own documents only, db3 only. Exact requests and responses go to
`crew/state/files/autocount-api/db3-requests-10nov.json` (outside the repo); the sanitised summary to
`documentation/integrations/autocount/test-report-2026-11-10.md`. Result table: section 3a (filled after the run).

## 4. Design (filled after the probes)

## 5. Slices

## 6. CRM follow-ups (separate lanes)
