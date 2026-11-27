# PLANNER-3D: `claude-procedural` engine (lane CLAUDE-3D-ENGINE-BUILD)

Size L. Branch `crew/claude-3d-engine-build`. Owner 27 Nov: model approved, spend up to US$700 total.
Scout: sorento-crm PR #2828 (`REPORT-claude-3d-engine-scout-27nov.md`): Claude writes a Python script
(trimesh + manifold3d, SDF for one-piece ceramics) that builds the product and exports GLB; three renders
are compared with the photo; at most 2 refines (3 script versions).

No user-visible screen changes (no behaviour card): the engine is a new worker engine behind the existing
`model` job; the staff submit route gains two optional inputs.

## Decisions

- D1 The engine lives in the Mac pull worker: `planner3d_worker/engines/claude_procedural.py`, selected by
  `build_engine("claude")` (`planner3d_worker/engines/__init__.py`). Runs LOCAL on the Mac (CDN + key).
- D2 API key: login keychain, account `planner3d`, service `anthropic-api-key`, read at runtime by
  `keychain.py` like the HF token (S3 D6). Never printed, logged, written, or passed to the sandbox.
- D3 Anthropic Messages API through the official `anthropic` Python SDK (worker-only dependency in
  `requirements-model.txt`), streaming + `get_final_message()`, adaptive thinking, `output_config.effort`
  per profile; photo and drawing as image blocks, dims + category as text. Usage tokens from every response go
  to the ledger. Prices (Anthropic first-party, checked 27/11/2026): Sonnet 5.5 $2 in / $10 out / $0.10 cache
  read per MTok; Opus 5.5 $4 / $20 / $0.20. The client is injected so tests use a fake.
- D4 Routing by category DATA, never by product words in code: `claude_routing.json` (operator file) maps a
  category code to a profile `{model, approach: primitives|sdf, maxVersions}`; unknown category = default
  profile (Sonnet, primitives). The pilot fills the file from the CRM category list.
- D5 Candidates: the backend needs at least 2 (`job_service._success_problem`). The engine always runs v1 plus
  at least one refine; candidate-1 = last version, candidate-2 = the one before (candidate-3 = v1 when 3 ran).
  `candidate-N.json` carries model, tokens, US$, seconds, dims error, renders summary and the script text
  (provenance; JSON cap 1 MB). No new output names, so the backend output rules stay as they are.
- D6 Sandbox for model-written code (mandatory security review):
  - child `python -I` with an EMPTY environment, cwd = fresh temp dir, inputs copied in as plain numbers;
  - macOS `sandbox-exec` deny-default profile: no network, file writes only inside the temp dir, file reads
    only the Python prefix / site-packages / system libs / the temp dir; no keychain or mach services beyond
    what Python needs;
  - `resource.setrlimit` CPU seconds, file size, open files, no core; wall-clock timeout + RSS cap through
    the existing `runner.run_capped` style monitor; process group killed on breach;
  - AST pre-check (defence in depth only): imports limited to numpy, math, trimesh, manifold3d, scipy
    sub-modules used for meshing; no `open` outside the output name, no `exec/eval/__import__/subprocess/os.system`;
  - no sandbox available (e.g. Linux CI) = the engine refuses to run model code (fail closed); tests inject
    a fake executor or run the real one on darwin only.
- D7 Render-compare: a numpy software rasteriser (`planner3d_worker/raster.py`), front / side / three-quarter
  PNGs at 512 px, flat-shaded, headless and deterministic. Sent back to Claude with the photo and the
  measured bbox vs spec for the refine turn.
- D8 Spend guard: `~/planner3d/claude-ledger.jsonl`, one line per API call (time, job id, product code, model,
  input/output/cache tokens, US$ from the price table in `claude_routing.json`). Before each call the engine
  sums the ledger; at or over `spendCapUsd` (700) it stops with `spend_cap`. Every step report quotes it.
- D9 Backend: `POST /planner3d/jobs/models` accepts optional `drawing` (PNG/JPEG/WebP, sniff-first, 20 MB,
  stored role `drawing`) and optional `categoryCode` / `categoryName` (params `category`). Same optional fields
  on the S1 gateway `/models` are a `crew-note:` to ss#364 (not merged; not edited here).
- D10 Fit: the CRM keeps `model_fit.fit_model_to_box` and the C5 review/export as is; the engine already
  produces exact-mm bboxes, the fit is a no-op safety net.

## Steps

1. API confirmation x1 (CLI `python -m planner3d_worker.claude_cli`): SRTWC286-SH on Opus (sdf),
   SRTWT5903 on Sonnet then one Opus try. Ledger real tokens + US$. Blocked on the key (crew ask filed).
2. Adapter (red tests first: tester, then coder; Sonnet): engine, client, raster, sandbox, ledger, routing,
   CLI, backend optional inputs. Reviewer + security-reviewer in parallel.
3. Pilot: 30 products / 6 categories on dev; pass rate per category, cost, time; photo vs render page;
   filed as crew ask.
4. Full catalogue only after the pilot report, batches with ledger, stop on degrading pass rate or US$700.
   Any write to production storage or DB = crew asks the owner first.

## Test list (tester, red first)

Engine: v1 + refine produce 2 candidates with reports; 3 versions -> 3 candidates; script with syntax error
-> refine turn carries the traceback; all versions fail -> job error `generation_failed`; routing picks
model/approach from the category code and falls back to default; spend cap reached -> `spend_cap`, no
API call made; ledger line per call with tokens + US$; key never in the sandbox env, never in any output
or log (assert by scanning outputs for a canary key).
Sandbox (darwin): script opening a socket fails; writing outside temp fails; reading `~` fails; CPU loop
killed by the limit; memory hog killed; fork bomb contained; env is empty; AST check rejects
`import subprocess`, `__import__`, `eval`. Non-darwin: executor refuses (fail closed).
Raster: deterministic PNG for a unit box; three views differ; empty mesh handled.
Backend: submit with drawing + category stores role `drawing` and params `category`; fake drawing -> 422;
oversize -> 413; without them behaves exactly as before.
