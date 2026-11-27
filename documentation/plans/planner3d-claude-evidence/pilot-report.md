# Pilot: claude-procedural engine on 23 catalogue products (27/11/2026)

Run engine-direct on the Mac (`planner3d_worker.claude_cli`, real Anthropic API, ledger every call), as crew
ruled (option a). Inputs read read-only from the CRM catalogue connector: product data only. Owner review page
(photo vs model, Pass / Fail per product): https://claude.ai/artifact/NxHRgLBjeuGoFTuxv7NeNr (private).

## Results per kind

| Kind | Products | Model made | Model | Avg US$ / product | Avg time | Max faces | Max size error |
|---|---|---|---|---|---|---|---|
| Basin | 5 | 5 | Sonnet 5.5 | 0.12 | 57 s | 16,896 | 1.5 mm |
| Accessory (grab bar, towel rail) | 5 | 5 | Sonnet 5.5 | 0.14 | 67 s | 49,910 | 0 mm |
| WC | 5 | 5 | Opus 5.5, distance fields | 0.42 | 3 min 18 s | 56,192 | 0 mm |
| Tap | 3 | 3 | Opus 5.5 | 0.31 | 1 min 32 s | 12,700 | 0 mm |
| Shower set | 5 | 5 | Sonnet 5.5 | 0.15 | 1 min 25 s | 41,464 | 0 mm |
| Vanity | 0 | - | - | - | - | - | - |

- 23 of 23 products produced a model (2 needed a rerun after fix round 6: one product had only 1 good version
  of 3, one drawing was 56 MP, over the old 40 MP input limit).
- Pass rate per kind comes from the owner's marks on the review page (not filled in yet).
- My own first look: 21 of 23 read as the product; MWB7631 (wall-hung basin) came out as a flat frame with no
  bowl; taps are right in size and layout but still more angular than the photos.
- Spend: pilot US$5.12 (including the failed first attempts), step 1 US$1.20, all calls US$6.33 of the US$700 cap.
- Machine time: 38.5 minutes summed over the 23 products (run 2 to 3 in parallel). At that rate the
  ~1,804-product catalogue is about 50 hours of single-lane time, or about 5 hours at 10 in parallel.

## Findings for the owner

1. Dimensions gap (blocks C5 and the full catalogue): only 121 of 3,578 active products carry
   length / width / height in the CRM fields, and almost none of those have a photo. The products with photos
   and drawings are colour variants whose dims fields are empty; the size sits in the description text
   ("L500 x W400 x H145MM") or only on the drawing. C5 (`fit_model_to_box`) needs the three numbers.
   Proposed fix: (a) a reviewed backfill that fills the CRM dims fields from the description text, and from the
   drawing where the text has none (Claude reads the drawing, a person approves each value in a review list),
   then C5 runs unchanged; or (b) C5 reads the description / drawing itself at job time. Recommendation (a):
   one reviewed source of truth, also useful for quotations and the planner.
2. Routing: CRM categories are too coarse to pick the model (WC, basin and urinal share M-CERAMIC). Route by the
   planner product type (C1 catalogue `product type`), not the category code: WC to Opus + distance fields,
   taps to Opus, others to Sonnet.
3. Vanity: no vanity / basin cabinet has a drawing, and the furniture sets state only a width; none could be
   modelled at the right size. Needs drawings or dims first.
4. Taps: only 3 of about 70 had a drawing with unambiguous overall size; shower sets needed height segments
   summed. Same fix as 1.

## Next

Owner marks the 23 products. Then: approved GLBs go through C5 once ss#364 is live; step 4 (full catalogue,
US$700 cap, batches with a ledger, stop on a falling pass rate) only after the dims fix in finding 1.

## Round 2: all kinds on Opus, colour renders (27/11/2026, owner ruling ~22:35)

Round 1 owner marks: 0 of 23 passed, all for colour (the review renders were flat grey; the GLBs carried the
right finishes) and 2 basins also for shape. Fixes: renders show glTF base colour and metal finish; the prompt
requires named PBR materials; every kind runs on Opus (WC and basin with distance fields).

| Kind | Products | Model made | Avg US$ / product | Avg time | Max faces | Max size error |
|---|---|---|---|---|---|---|
| Basin | 5 | 5 | 0.33 | 2 min 20 s | 58,384 | 0 mm |
| Accessory | 5 | 5 | 0.25 | 1 min 25 s | 44,708 | 0 mm |
| WC | 5 | 5 | 0.42 | 3 min 33 s | 55,204 | 0 mm |
| Tap | 3 | 3 | 0.31 | 1 min 37 s | 11,194 | 0 mm |
| Shower set | 5 | 5 | 0.38 | 2 min 10 s | 49,706 | 0 mm |

Opus round: US$7.77 for 23 products (US$0.34 average). At that rate the ~1,804-product catalogue is about
US$610, inside the US$700 envelope only if the CRM-DIMS-BACKFILL lane stays small; crew holds the total.
Owner re-review: same page, fresh marks (`verdicts_opus`); round 1 marks kept as a record.

## Round 3: owner round 2 marks and the reruns (27/11/2026 ~23:20)

Owner round 2: 19 of 23 passed (basin 2/5, accessory 5/5, WC 5/5, tap 2/3, shower 5/5). Fails: MAB7041 and
MAB7023 (no drain hole visible), MWB248 (not the closest), M4731SS-GD (gold colour). Generator fixes
(a8c16a5c, 19ab5d2b): every visible functional feature listed and built (drain with pop-up cap, tap holes,
overflow), colours written as linear glTF values from a finish table checked against the photo's dominant
colours, renders in sRGB with brighter metal, and a 4th top view so bowl interiors are visible. The drains were
in the round-2 models already; the old cameras could not see into the bowls. Only the 4 failed products were
rerun on Opus; the page is republished for a quick re-tick.
