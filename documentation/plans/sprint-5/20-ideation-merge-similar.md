# 20 - Ideation: canny-style fields, field-level merge, Similar ideas

Lane IDEA-CORE, PR #124. Contract: `20-ideation-merge-similar-acceptance-criteria.md`. Mocks: `20-evidence/mock-v1.html`, `20-evidence/mock-v2.html`.

## Decisions (owner / crew, 13 Oct)

- **D1 Fields.** "Problem statement" is relabelled "Business problem", on the same `problem` column. The new columns are `desired_outcome`, `use_cases` (JSON list of str) and `current_workaround`. Proposed solution / Impact / Department are hidden from every UI surface; their columns and data are kept. The intake key names are locked with IDEA-CAPTURE (sorento-crm #1625): `desired_outcome`, `use_cases`, `current_workaround`. `OneShotIdeaIn` keeps ignoring unknown keys.
- **D2 Similar = AI ranking** (card Q1a). One `AiClient.complete` call per request, using the tenant's `ideation-grill` agent (the same seam as `clustering.py`), over up to 60 live candidates. **No pg_trgm fallback**: on failure the endpoint returns `available:false` and the UI shows a Retry. Cost is about 4k input tokens per open, roughly $0.001 on a mini model, with 2-4s latency.
- **D3 Kept idea** (Q3a) = the idea the merge was started from, changeable with a per-column radio.
- **D4 Comments and attachments** (Q4a) stay on the absorbed idea and are read through onto the survivor, labelled `fromIdea`. Unmerge needs no data move.
- **D5 Unmerge restores fields** (Q5a). The merge writes `merge_snapshot_json` on each absorbed child: `{field: {"before": survivor value before, "after": value written}}`. Unmerge restores a field only while `survivor.field == after`. With several children, the snapshot sits on the FIRST absorbed member (by the given order). Restoring is done when that child is unmerged or the group is dissolved. Unmerging any other child does not touch survivor fields.
- **D6 N-way merge** (Lavish note 2). `fields: {key: [ideaId...]}`. Ticking several cells combines them: text joined with `--- from IDEA-xxxx ---`, use cases concatenated with duplicates dropped.
- **D7 Similar list** (Lavish note 1). A standard `ResourceList` with row and bulk Merge.

## Backend

1. `models.py`: `Idea.desired_outcome`, `use_cases`, `current_workaround`, `merge_snapshot_json`. Migration `0017_ideation_canny_fields` with idempotent `ADD COLUMN IF NOT EXISTS` (Postgres only, same pattern as 0016).
2. `schemas.py`: `IdeaOut` / `IdeaCreateIn` / `IdeaUpdateIn` (+`title`) / embed create/update / `OneShotIdeaIn` / `MergeIn.fields`. `IdeaCommentOut.fromIdea` and `IdeaAttachmentOut.fromIdea`.
3. `intake_definitions.py`: three optional schema fields (not in `OPTIONAL_ASK_ORDER`). `sinks.sync_idea_columns_from_captured` mirrors them, with `use_cases` normalised from a list or a newline string. `IntakeService.create_one_shot` gets the three params.
4. `merge.py`: `_apply_fields` (after validation, before writes), the snapshot, and restore in `unmerge`.
5. `comments.py` / `ideas.py`: survivor reads union the children's rows.
6. `services/similar.py` `SimilarIdeasService.rank(tenant, idea)`, plus routes in `ideas.py` and `embed.py`.

## Frontend

`types/ideation.ts`, the service (real + mock parity), `idea-schema.ts`, `idea-form-fields.tsx` (field set), `merge-ideas-dialog.tsx` (N columns, per-cell checkbox), `components/idea-similar-tab.tsx` (clone of `idea-merged-tab.tsx`), `use-idea-form.tsx` tab wiring, and the Ideas list bulk Merge going through the new dialog.

## Out of scope

Chatbot capture of the new fields (sorento-crm IDEA-CAPTURE). Public status page fields (unchanged). AI tools for similarity.
