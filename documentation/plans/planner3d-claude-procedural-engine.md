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

## Phase 1 contract block (tester and coder build to exactly this)

Worker package `planner3d_worker/claude/` plus the engine file:

- `routing.py`: `Profile(model: str, approach: "primitives"|"sdf", max_versions: int, effort: str)` (frozen
  dataclass); `Routing.load(path) -> Routing` reads JSON
  `{"spendCapUsd": 700, "prices": {"<model>": {"input": 2.0, "output": 10.0, "cacheRead": 0.10}},
  "default": {"model","approach","maxVersions","effort"}, "categories": {"<code>": {...same keys...}}}`;
  `Routing.profile_for(category: dict | None) -> Profile` (by `category["code"]`, else `default`);
  `Routing.prices(model) -> dict`; `Routing.spend_cap_usd -> float`. `max_versions` is clamped to 2..3.
  Shipped file `planner3d_worker/claude/routing.default.json` (Sonnet 5.5 primitives default, no categories).
- `ledger.py`: `cost_usd(usage: dict, prices: dict) -> float` (usage keys `input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens` billed as input); `Ledger(path)` with
  `.total_usd() -> float` (sum of `usd` over JSONL lines, missing file = 0.0) and `.append(entry: dict)`
  (one JSON line, keys at least `at, jobRef, productCode, model, inputTokens, outputTokens,
  cacheReadTokens, usd`).
- `sandbox.py`: `ScriptRejected(Exception)`, `SandboxUnavailable(Exception)`; `check_script(src: str) -> None`
  raises `ScriptRejected` (imports outside `numpy, math, trimesh, manifold3d, scipy, json, itertools,
  functools, collections`; names `eval, exec, compile, __import__, open, globals, getattr` on dunder strings,
  any `os`, `sys`, `subprocess`, `socket`, `ctypes`, `importlib`, attribute access starting with `__`);
  `Limits(cpu_s=240, wall_s=300, mem_mb=3072, file_mb=200)`; `available() -> bool` (darwin and
  `/usr/bin/sandbox-exec` exists); `run_script(src, work_dir: Path, limits: Limits) -> RunResult(ok: bool,
  glb: Path | None, stderr_tail: str, seconds: float, reason: str | None)` - writes `gen.py` and
  `params.json` into `work_dir`, runs `python -I gen.py` with an EMPTY env, cwd `work_dir`, under the
  sandbox profile; the script reads `params.json` and must write `model.glb` in cwd. Raises
  `SandboxUnavailable` when `available()` is false. `reason` in `timeout|cpu|memory|exit|no_output`.
- `prompts.py`: `SYSTEM_PROMPT: str`, `first_turn(photos: list[Path], drawing: Path | None, dims_mm: dict,
  category: dict | None, profile: Profile) -> list[dict]` (Messages API content blocks: images base64
  then text), `refine_turn(renders: dict[str, bytes], measured_mm: dict, spec_mm: dict, error: str | None)
  -> list[dict]`, `extract_script(text: str) -> str` (last ```python fenced block; ValueError when none).
- `planner3d_worker/raster.py`: `render_views(mesh: trimesh.Trimesh, size: int = 512) -> dict[str, bytes]`
  keys `front, side, three_quarter`, PNG bytes, deterministic, numpy + Pillow only.
- `planner3d_worker/engines/claude_procedural.py`: `EngineFailure(Exception)` with `.code` in
  `spend_cap | generation_failed | no_api_key | sandbox_unavailable`, str = `"<code>: <message>"`;
  `ClaudeProceduralEngine(client=None, routing=None, ledger=None, run_script=None)`, `kinds = ["model"]`,
  `run(kind, inputs: dict[name, path], params, out_dir) -> list[(name, role)]`. Inputs: names starting
  `photo` are photos, a name starting `drawing` is the drawing. Params: `dimensionsMm {length,width,height}`,
  optional `category {code,name}`, optional `productCode`. Loop: check spend cap -> call -> ledger ->
  extract -> check_script -> run_script -> load GLB, measure bbox (Y up, metres; length = X, width = Z) ->
  render -> refine, until `max_versions` versions ran (at least 2). Candidates per D5 with roles
  `candidate` / `report`; `candidate-N.json` keys `engine:"claude-procedural", model, version, usage, usd,
  seconds, measuredMm, specMm, dimsErrorMm, script`. A version that fails gets the error fed to the next
  turn; fewer than 2 good versions = `generation_failed`. The client is the SDK `anthropic.Anthropic`
  (key from keychain `planner3d` / `anthropic-api-key` when `client` is None, else `no_api_key`); tests pass
  a fake with `.messages.stream(...)` returning a context manager whose `get_final_message()` gives an
  object with `.content` (text blocks) and `.usage`.
- `engines/__init__.py`: `build_engine("claude")`; `__main__.py --engine` accepts `claude`.
- `client.py`: an engine failure whose message starts with `EngineFailure: <code>:` finishes with that code
  when it is in `GENERIC_ERRORS` (add `spend_cap`, `generation_failed`, `no_api_key`, `sandbox_unavailable`).
- `planner3d_worker/claude_cli.py`: `python -m planner3d_worker.claude_cli --photo P [--photo P] [--drawing D]
  --dims L,W,H [--category CODE] [--model M] [--approach sdf|primitives] --out DIR --ledger PATH --ref CODE`
  runs the engine once outside SS (step 1 and the pilot).

Backend: `POST /planner3d/jobs/models` adds `drawing: UploadFile | None = File(None)` (sniff PNG/JPEG/WebP,
`PHOTO_CAP`, stored `drawing.<ext>` role `drawing`, 422 `drawing_type`), `categoryCode: str | None` and
`categoryName: str | None` (`Form`, max 64 / 128 chars) -> `params.category = {code, name}` only when a code
is given; `productCode: str | None` (max 64) -> `params.productCode`.
