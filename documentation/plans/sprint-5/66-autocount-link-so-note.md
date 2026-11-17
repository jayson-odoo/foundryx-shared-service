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

## 3. Live finding (owner prod read, 17 Nov)

- Prod served 8cc79df5 (#247 and #248 included). Ops on the PO: link_batch 14:39:22 -> unlink_row 14:39:37 ->
  link_batch 14:40:43. The row checked is the last link_batch's new row.
- That op ran the whole #247 path: GET PO, GET SO, GET PO, PUT 200 (link), GET PO, PUT 200 (restore), GET PO;
  status done. The restore PUT always carries the note (`transfer_row_drift`, `payloads.py:341`) and is the only
  write that can set the new row's DeliveryDate (the link PUT leaves it empty, plan 65 probe P2). The date
  stuck, the note did not: AutoCount accepts `FurtherDescription` on an edit of an EXISTING row without storing
  it. CONFIRMED 17 Nov: owner3.sql shows the restore PUT carried the note (200), and the owner's AutoCount screen
  shows the row with its location and date set and the note empty (case c).

## 4. Fix (c537b971; held from release until the db3 probe shows shape (i) stores the note)

Expected winner: the note also goes on the NEW row inside the PUT that creates it (a DtlKey-0 row; AutoCount
documents FurtherDescription on added rows), and stays in the restore PUT. Same text and RTF builder
(`so_link_note`, `autocount_rtf`). Only the new linked row ever carries it; unlink's plain row never does; the
public add/edit doors still never take it. The link read-back verify never judges it (reads never return it).

UAC (red tests `service_backend/tests/test_autocount_link_so_note.py`):
- AC-66-01 whole-row `link_row`: the link PUT's new row carries the RTF note (no DD when the SO row has no date).
- AC-66-02 `relink_row`: the replace PUT's new row carries the new SO row's note.
- AC-66-03 `link_batch` (part and whole): each new row in the link PUT carries its note.
- AC-66-04 single part-row link (`split_link`): the split PUT's new row carries the note.
- AC-66-05 no other row of any PUT carries a note (kept / deleted rows keep theirs).
- AC-66-06 control: unlink's plain row carries none.
- AC-66-07 control: the public add-line door never sends a caller's FurtherDescription.

## 5. D2: the restore PUT resends the note (never omits it)

The restore PUT (`_restore_rows`, operations.py, via `transfer_row_drift` payloads.py:341) is an edit of the row
the link PUT just created. Two ways AutoCount's edit could treat FurtherDescription, neither proven:
(a) ignore it (the live 17 Nov evidence: sent, 200, not stored) or (b) a full-row edit that clears a field the
body leaves out. Resending the identical note is safe under both: (a) leaves the note the link PUT stored,
(b) writes the same text. Omitting the key would blank it under (b). The note is never sent empty
(`if sent.get(k)`, payloads.py:341), so the restore can never write a blank note. Pinned by AC-66-08.

AC-66-08 the restore PUT on the new row carries the identical note the link PUT carried (never omitted, never empty).
AC-66-09 a partly received link_row (cut + add) carries the note on the added remainder row.
AC-66-10 the recover row of a failed relink (old link) never takes the new SO row's note.
AC-66-11 a primitive line from outside an operation cannot carry the link-only note key.

## 6. Proof after release

No db3 screen or SQL access exists (owner, 17 Nov). Proof = the owner's next real Link PO on the live book plus
the SELECT-only check `66-evidence/note-landing-check.sql` (presence / length / marker only).
