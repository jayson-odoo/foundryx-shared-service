# 20 - Ideation: canny-style fields, field-level merge, Similar ideas - Acceptance Criteria

Lane IDEA-CORE (PR #124). Settled by the owner's 13 Oct field ruling, the behaviour card answers (Q1-Q5) and the Lavish notes on mock v1 (see `20-evidence/mock-v2.html`). Tags: `[BE]` backend, `[FE]` frontend, `[E2E]` browser pass, `[T]` automated test.

## S1 - Fields

- **AC-20-01 [BE][T]** Given the ideation schema, when migration `0017_ideation_canny_fields` runs on Postgres, then `app_ideation.ideas` gains nullable `desired_outcome TEXT`, `use_cases JSON`, `current_workaround TEXT` via `ADD COLUMN IF NOT EXISTS`, and no existing column is dropped or altered (`proposed_solution`, `impact`, `department` and their data stay). Revision id is 32 chars or fewer.
- **AC-20-02 [BE][T]** Given an operator, when they GET an idea, then the body carries `desiredOutcome` (string or null), `useCases` (list of strings, `[]` when unset) and `currentWorkaround` (string or null).
- **AC-20-03 [BE][T]** Given a workspace key, when the host POSTs `/ideation/intake/ideas` with `desired_outcome` (str), `use_cases` (list of str) and `current_workaround` (str), then those values are stored on the idea. Blank strings are stored as null, and blank or whitespace-only use cases are dropped. A body without these keys still succeeds (fields stay empty). Unknown extra keys are still ignored, not 422.
- **AC-20-04 [BE][T]** Given the conversational intake (`/ideation/intake/create-idea`), when a turn's `fields` carry `desired_outcome` / `use_cases` / `current_workaround`, then they are captured and mirrored onto the columns. The bot's asking order (`OPTIONAL_ASK_ORDER`) is unchanged.
- **AC-20-05 [BE][T]** Given an operator with edit rights, when they PATCH `/ideation/ideas/{id}` (or the embed equivalent) with `title`, `desiredOutcome`, `useCases`, `currentWorkaround`, then the values persist. Create (`POST /ideation/ideas`) accepts the same three new fields.
- **AC-20-06 [FE][T]** Given the idea Details tab, then the rows are, in order: Title, Business problem (the `problem` column, relabelled from "Problem statement"), Desired outcome, Use cases (a bullet list), Current workaround, followed by the existing meta rows. "Original message" is the relabelled raw notes row. Proposed solution, Impact and Department are not rendered in view, edit or create. An empty field shows "-".
- **AC-20-07 [FE][T]** Given edit mode, then Title is an Input, Business problem / Desired outcome / Current workaround are Textareas, and Use cases is a list of Inputs with add and remove. Save sends only the new field set.
- **AC-20-08 [E2E]** The same Details tab renders inside the CRM embed (`/embed/ideas/<id>`), at 375px and 1280px.
- **AC-20-09 [BE][T]** Given an embed token (the JSON surface Sorento's native Ideas pages consume through its gateway), then `POST /embed/ideas`, `GET /embed/ideas/{id}` and `PATCH /embed/ideas/{id}` carry `title`, `desiredOutcome`, `useCases` and `currentWorkaround` exactly like the operator routes.

## S2 - Field-level merge (N ideas)

- **AC-20-10 [BE][T]** Given `POST /ideation/ideas/merge` with `survivorId`, `ideaIds` and an optional `fields` map `{fieldKey: [ideaId, ...]}` for keys in {title, problem, desiredOutcome, useCases, currentWorkaround, rawText}, then for each key present the survivor's value becomes: one id = that idea's value verbatim. Several ids = text values joined in the given order, where each value after the first is preceded by a `--- from IDEA-xxxx ---` line (the idea number, or the title when there is no number). Use cases are concatenated in order with exact duplicates dropped. Empty values are skipped.
- **AC-20-11 [BE][T]** A `fields` entry naming an id outside `ideaIds`, an unknown field key, or an empty id list is a 422, and nothing is written. Omitting `fields` keeps today's behaviour (the survivor's fields unchanged), so existing clients keep working.
- **AC-20-12 [BE][T]** Votes still move or shadow exactly as before (AC-94-06), merge still flattens, and the survivor still gets an idea number.
- **AC-20-13 [BE][T]** Given a merge that changed survivor fields, when the absorbed idea is unmerged (or the whole group is dissolved), then each survivor field that still equals the value the merge wrote is restored to its pre-merge value. A field edited after the merge is left as it is. The absorbed idea's own fields are never changed by merge or unmerge.
- **AC-20-14 [BE][T]** Given a survivor with merged children, then its comment list includes the children's comments, each labelled with its source (`fromIdea: {id, ideaNumber}`), and its `attachments` include the children's attachments, also labelled with `fromIdea`. The child's own reads are unchanged. After unmerge, they no longer appear on the survivor.
- **AC-20-15 [BE][T]** The embed merge route accepts the same `fields` map, with the same scope checks (any id outside the connection's product returns 404 and nothing is written).
- **AC-20-16 [FE][T]** The merge dialog shows one column per selected idea and one row per field (Title, Business problem, Desired outcome, Use cases, Current workaround, Original message), with a checkbox in each non-empty cell. Default tick = the kept idea's cell, or the first non-empty column when that cell is empty. A row where every cell is empty has no checkbox. Merge is disabled while a row that has any content has no tick. A radio in each column header picks the kept idea (default = the idea the dialog was opened from, else the first). Rows with two or more ticks show a Result preview. A "Carried over" row lists votes, comments and attachments.
- **AC-20-17 [FE][T]** The Ideas list bulk Merge opens the same dialog for any N of 2 or more.
- **AC-20-18 [E2E]** The dialog is usable at 375px: the grid scrolls sideways inside the dialog, the page has no horizontal scroll, and the field label column stays visible.
- **AC-20-19 [BE][T]** Given an embed token, the whole merge lifecycle works over JSON: `POST /embed/ideas/merge` with `fields`, `GET /embed/ideas/{id}/merged`, the survivor's `GET /embed/ideas/{id}/comments` with `fromIdea`, and `POST /embed/ideas/{id}/unmerge` restoring the survivor's fields.

## S3 - Similar ideas

- **AC-20-20 [BE][T]** `GET /ideation/ideas/{id}/similar` (gated `ideation.ideas.view`) returns `{available: true, ideas: IdeaOut[]}`, ranked most similar first by ONE `AiClient.complete` call using the tenant's `ideation-grill` agent. Candidates are the same tenant and product, the same test/real lane, live survivors (the dedup candidacy predicate), excluding the idea itself and its merged children, capped at 60 newest. The model can only return ids from the candidate set; any other id is dropped. The idea texts are sent as message data, never as prompt template.
- **AC-20-21 [BE][T]** When the AI call fails, or no agent or connection resolves, the endpoint returns `200 {available: false, ideas: []}`, with no text-match fallback and no 5xx. When there are no candidates, it returns `{available: true, ideas: []}` and makes no AI call.
- **AC-20-22 [BE][T]** The embed has an equivalent route scoped to the connection's product.
- **AC-20-23 [FE][T]** The Similar ideas tab is a `ResourceList` (a clone of the Merged-from tab) with checkboxes, a row "..." menu with Merge, and bulk Actions > Merge. Rows open the idea. Merge opens the S2 dialog with the current idea plus the chosen row(s), with the current idea kept. When unavailable, the tab shows "Similar ideas unavailable" with a Retry button. Loading never shows a spinner that cannot end.
- **AC-20-24 [E2E]** Similar tab -> Merge -> dialog -> Merge works by real clicks, at 375px and 1280px.

## DoD

- No mock left serving data. No new permission (the merge route reuses `ideation.triage.manage`). The migration is additive with no backfill needed (the new fields are empty on old ideas by design, per the owner's ruling).
