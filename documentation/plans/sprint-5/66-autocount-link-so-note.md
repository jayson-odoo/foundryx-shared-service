# Plan 66: Link PO writes the S/O note like hand-made lines (lane LINK-SO-NOTE)

Status: INVESTIGATION (17 Nov 2026). Size S. Base origin/main 8cc79df5. Public repo: no names, prices or keys.

## 1. Ask

Owner 17 Nov ~14:55: every Link PO from the CRM writes the S/O note (AutoCount `FurtherDescription`) on the
linked PO row, in the same RTF shape and text as hand-made lines. Unlink's replacement plain row carries no note.

Live evidence (17 Nov ~14:50): a CRM Link PO of an SO row to a PO row landed (new row has FromSODtlKey,
FromSODocList, DeliveryDate = 02/11/2026) but `FurtherDescription` is NULL in AutoCount.
Hand-made lines on the same PO: `{\rtf1 ... \f0\fs18 **<customer>/<project> S/O: <no> DD: <dd/mm/yyyy>\par ...}`.

## 2. Code facts (8cc79df5)

The note builder already exists (plan 65 D4, #247):
- text: `payloads.so_link_note` (`service_backend/modules/autocount/write_back/payloads.py:347-359`), from the
  SO header `DebtorName` + `Ref` and the SO row date. SS already knows the customer/project text from the SO
  read: the CRM does not need to send it (brief rule 2: no CRM change).
- RTF: `payloads.autocount_rtf` (`payloads.py:390-394`), wrapper `\fs20` (`payloads.py:362-363`).
- restore values: `payloads.transfer_restore` (`payloads.py:294-321`), note always re-sent by
  `transfer_row_drift` (`payloads.py:331-342`, `UNREADABLE_ROW_KEYS`).

Every link path already routes the note into the restore PUT:
- whole row `link_row` -> `_replace_run` -> `_link_move` (`operations.py:996-1020`, `:1045-1055`), snapshot
  `soLink` (`operations.py:884-907`);
- `relink_row` same snapshot (target SO);
- `link_batch` -> `_batch_done` -> `_restore_rows` (`operations.py:1481-1510`);
- split / plan-55 flow -> `_finish_split` (`service.py:796-880`, whole row too: the new row has DtlKey 0).

So the code sends the note; the open question is why the live row has none. Hypotheses:
- H1: the SS build serving the CRM at 14:50 predated #247 (merged 16 Nov 23:29 JST).
- H2: the restore PUT was not sent (deadline skip, `RESTORE_NOT_LANDED`, op `needs_attention`).
- H3: hapi answers 200 to an edit PUT carrying `FurtherDescription` but does not store it (plan 65 P3 never
  confirmed landing; the db3 screen check is still open, plan 65 section 6).

The call log (`ac_api_call_log.request_json`) of that link tells H1/H2/H3 apart (crew data request).
