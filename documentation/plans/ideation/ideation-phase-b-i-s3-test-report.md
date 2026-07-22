# Ideation Phase B-i · Slice 3 (Generic Grill Engine) — Test Execution Report

**Scope:** AC-BI-20..29 + AC-BI-20b + AC-BI-24b (+ the AC-BI-37 live DoD gate).
**Branch / worktree:** `feat/ideation-phase-b-idea-to-br` @ `/Users/tehjayson/Documents/foundryx/foundryx-shared-service/.claude/worktrees/ideation-phase-b` (uncommitted S3 slice).
**Tester:** independent QA. Application code was NOT modified — only tests were added.
**Date:** 2026-07-22.

---

## 1. Headline verdict

| Layer | Result |
|---|---|
| Backend grill suite (`test_ideation_grill.py` + new `test_ideation_grill_http.py`) | **19 passed** |
| Full backend suite (`python -m pytest -q`) | **1558 passed, 1 failed, 18 deselected** — the 1 failure is the **known pre-existing** migration-id test (out of scope; see §3) |
| Frontend unit (`npm test`) | **943 passed (122 files)**; grill-specific = **12** (`grill-chat` 6 + `use-grill` 6) |
| **LIVE grill (AC-BI-37, real Gemini) — the DoD gate** | **FAIL** — turns work, but **Generate never produces a usable BR** (502, reproduced 3×). See §4. |

The plumbing (turn + coverage + termination model + trace-on-error + never-promote) is correct and well-tested. **The DoD gate fails**: against the seeded real model `gemini-2.5-flash`, the extraction/Generate step reliably 502s on a realistic grill transcript, so the resulting BR is empty and unusable by a human. Root-caused, reproduced, and a confirmed one-line fix direction is handed to the coder (§4.3). This is a code defect in the S1 Gemini adapter surfaced by S3's extraction usage — kicked back to the coder.

---

## 2. Test command output (actual)

### Backend — targeted
```
tests/test_ideation_grill.py ..............         [14 passed]
tests/test_ideation_grill_http.py .....             [ 5 passed]  (QA addition)
combined: 19 passed in 14.68s
```

### Backend — full suite
```
1 failed, 1558 passed, 18 deselected, 186 warnings in 958.46s
FAILED tests/test_cluster_d_slice3_migration.py::test_module_migration_revision_ids_fit_alembic_column
```
(This full-suite run predates the new `test_ideation_grill_http.py`; those 5 are counted in the targeted run above.)

### Frontend
```
Test Files  122 passed (122)
Tests  943 passed (943)
# grill-specific:
grill-chat.test.tsx (6) + use-grill.test.ts (6) = 12 passed
```

---

## 3. The 1 backend failure is PRE-EXISTING, not an S3 regression

`test_module_migration_revision_ids_fit_alembic_column` fails because two **Phase-A** ideation migration revision ids exceed Alembic's `VARCHAR(32)`:

| file | revision id | length |
|---|---|---|
| `0003_ideation_idea_submitter_name.py` | `0003_ideation_idea_submitter_name` | **33** |
| `0004_ideation_idea_segregated_fields.py` | `0004_ideation_idea_segregated_fields` | **36** |

**S3 added NO migration** — the grill reuses S1's core `ai_*` tables and S2's `business_requirements`. The most recent ideation migration, `0008_ideation_business_reqs` (S2), is **27 chars** and fits. Confirmed S3 introduced no new offending id. This failure is out of scope per the brief; it should be fixed separately (rename the two Phase-A ids ≤32 chars — they break real Postgres deploy, invisible to pytest's `create_all`).

---

## 4. LIVE grill pass (AC-BI-37) — the DoD gate — **FAIL**

### 4.1 Stack
- Backend `:8002` freshly started on DB `foundryx_ideation_verify` (no `--reload`). Verified prepped: platform **Google Gemini** LLM connection (real key, `UNVERIFIED`), auto-seeded **"Ideation grill"** agent (`gemini-2.5-flash`, bound to that connection, enabled), seeded **`grill-me-business`** skill (active version). Confirmed `/health` 200 and requests hit `:8002`.
- Ideas were 0 in the verify DB → created 2 realistic ideas + a product + a draft BR linked to both, via the real API.
- **Frontend browser pass BLOCKED (environment, not code):** the worktree's `node_modules` is a *symlink* to the main checkout, which breaks Next's dev server on both webpack (`Cannot find module 'next/dist/pages/_app'`) and turbopack (`Next.js package not found`). Booting the FE here needs a real `npm install` in the worktree. Screenshots at 375px/1280px could not be captured. The grill was therefore driven **end-to-end against real Gemini via the real API** (real turns, real coverage, real extraction), which exercises the full server stack — only the click-through UI layer is unverified.

### 4.2 What the live grill actually did

**Turns — PASS (real Gemini, genuine prose, real coverage progression).** Three turns against `gemini-2.5-flash`:

- Turn 1 (user states the problem) → Gemini: *"It sounds like the core problem is that customer service representatives currently have to manually copy order history data into Excel… Is that an accurate problem statement? And what is the main business goal…?"* · `coveredFields: []`
- Turn 2 (user gives goal + stakeholders) → *"Great, we have the problem, goal, and stakeholders. For a success metric, **the linked idea mentions saving ~1 hour per rep daily**. Would a good success metric be…?"* · `coveredFields: [problem_statement, business_goal, stakeholders]` — **grounded in the linked idea (AC-BI-28)**.
- Turn 3 (user gives metric + scope + constraints) → *"Excellent, we now have specific answers for all target fields… **You can now generate the requirement.**"* · `coveredFields: [all 6]` — coverage complete, Gemini **offers** to generate; the human fires it (D23-A / AC-BI-22).

Coverage advanced **0 → 3 → 6 of 6**. The termination model works exactly as specified.

**Generate — FAIL (reproduced 3×).** Every real extraction call returned:
```
HTTP 502  {"detail": "The model returned a malformed structured result."}
```
The BR's `answers_json` was left `{}` (empty). The only populated BR in the verify DB (`Order export for CS 090654`) has **no `ai_conversation` and no extraction trace** — it was seeded out-of-band by the earlier setup, **not** grill-produced. **No successful Generate exists anywhere in the verify DB.**

### 4.3 Root cause (reproduced directly against Gemini) + fix direction

Replaying the exact failing extraction request (full system prompt + 6-message transcript + the 6-field responseSchema):

```
finishReason: MAX_TOKENS
usage: promptTokenCount=744, candidatesTokenCount=4086 (hit the 4096 cap)
content: 21038 chars of TRUNCATED JSON
HEAD: {"problem_statement": "Customer service representatives cannot export…
TAIL: …The problem statement is that customer service representatives currently have to  <-- runaway, cut off mid-string
```

`gemini-2.5-flash` with **no `thinkingConfig` set** (the adapter never sets one) *runs away* on the extraction: it begins valid JSON, then degenerates into restating the transcript prose inside a field value until it exhausts `maxOutputTokens=4096` (`finishReason=MAX_TOKENS`), truncating the JSON. `GeminiProvider.complete` then blindly `json.loads(content)` the truncated string → raises the opaque *"malformed structured result."* A short prompt succeeds (`finishReason=STOP`, valid JSON), which is why the happy-path exists — **but the more thorough the grill conversation (exactly what the feature encourages), the more reliably Generate breaks.**

**Confirmed fix** (same request, one change):
```
generationConfig.thinkingConfig.thinkingBudget = 0
→ finishReason: STOP, candidatesTokenCount=111, VALID JSON (517 chars)
```
Handed to the coder (`app/integrations/gemini_provider.py`): set `thinkingConfig.thinkingBudget=0` (or a small bounded budget) for structured-output calls; and surface `finishReason==MAX_TOKENS`/truncation as a clear, distinct error instead of the opaque "malformed structured result." Optionally raise `maxOutputTokens` and/or tighten the extraction directive against restating the transcript in field values.

### 4.4 Positives confirmed live
- **AC-BI-24b trace-on-error:** the two failed Generates each left a committed `error` trace (`provider=gemini`, `model=gemini-2.5-flash`, `error="The model returned a malformed structured result."`) — a failed run is observable, exactly as specified.
- **AC-BI-27 never-promote:** the BR stayed `draft` throughout (Generate never even reached persistence).
- **AC-BI-11 readiness:** `GET …/grill` returned `ready:true` (platform-connection fallback resolves for the tenant). The no-connection prerequisite warning path is covered by passing backend tests (`test_grill_state_warns_when_no_connection`, new `test_http_generate_warns_when_no_connection`) but was not exercised live (would require disabling the shared platform connection).

---

## 5. Coverage-gap assessment + tests added

**The thread-local stub gap is real.** `app/ai/stub.py` keeps its fixture queue in `threading.local()`; Starlette's `TestClient` runs the endpoint on a *different* thread, so `stub_fixtures(...)` set on the test thread is invisible to the request. The routine suite therefore drives scripted turn/generate/error paths against the **service** on a same-thread factory session, and only no-stub paths (readiness / scoping / perms) through HTTP. **This left the real request lifecycle — routing → `require_permission` → service → `get_db` teardown — untested for the scripted paths**, including the load-bearing AC-BI-24b claim that the error trace survives `get_db`'s exception-teardown rollback (the service/engine tests use direct sessions with no `get_db` teardown, so they never exercise it).

**Closed by monkeypatching the process-global `stub_provider.complete` singleton** (shared across threads, unlike the thread-local queue), driving the REAL HTTP endpoints. New file — `service_backend/tests/test_ideation_grill_http.py` (5 tests, all pass):

| Test | AC | Closes |
|---|---|---|
| `test_http_turn_provider_error_writes_error_trace_and_502` | AC-BI-24b / 09 | error trace survives `get_db` teardown on a REAL request (the genuine gap) |
| `test_http_turn_error_writes_no_transcript` | AC-BI-23 | no half-written turn after a provider failure, via HTTP |
| `test_http_turn_is_synchronous_no_background_job` | AC-BI-23 | a turn creates **no `background_jobs` row** (previously untested anywhere) |
| `test_http_generate_partial_persists_and_br_stays_draft` | AC-BI-26 / 27 | full-stack Generate: partial persists, blank left, BR stays `draft` |
| `test_http_generate_warns_when_no_connection` | AC-BI-11 | `/generate` 409s with the prerequisite warning when no connection |

**One gap NOT closable at HTTP level (documented, not a defect):** the one-retry-then-surface path (AC-BI-25) needs a *validation failure*, which requires a constrainable field (e.g. a `select` with a fixed option set). The real BR template is all `textarea` fields, so no HTTP request against it can force a validation error. AC-BI-25 is covered at the engine level with a synthetic doc (`test_validation_failure_triggers_one_retry_then_succeeds`, `…_twice_surfaces_field_errors`), and the retry logic is doc-agnostic — adequate.

---

## 6. Per-AC results (PASS / FAIL / DEFERRED)

| AC | Title | Result | Evidence |
|---|---|---|---|
| **AC-BI-20** | `GrillDefinition` is generic | **PASS** | Engine binds source/target/skill/agent/persist; synthetic def + real `idea_to_br` both drive it (`test_turn_*`, `test_generate_*`). |
| **AC-BI-20b** | default grill agent auto-seeded per tenant | **PASS** | `engine_fixture` asserts `install_tenant` seeds "Ideation grill"; verify DB shows it bound to the platform Gemini connection @ `gemini-2.5-flash`; live readiness `ready:true`. |
| **AC-BI-21** | transcript store | **PASS** | `ai_conversations` binds `(tenant, source_type, source_ids, target_type, target_id)` + stamps `(prompt_version, template_version)`; messages persisted (`test_turn_returns_reply_and_covered_fields`); live conversation row present + resumable. |
| **AC-BI-22** | turn contract: prose + coverage | **PASS** | `{replyText, coveredFields}`; invalid key filtered; live coverage 0→6 + Gemini offered to generate (never self-generated). |
| **AC-BI-23** | turn transport synchronous | **PASS** | New HTTP tests: no `background_jobs` row + no half-written transcript on error. |
| **AC-BI-24** | Generate = separate extraction call | **PASS (plumbing)** | Separate call over the whole transcript + form_engine validation; unit/engine tests green. NB: the model-output handling for this call fails live — see AC-BI-37. |
| **AC-BI-24b** | extraction ignores `required`; one structured turn; trace on error | **PASS** | `validate_submission(enforce_required=False)` strips required-only errors; turn schema is one structured call; error-trace-committed confirmed by engine + service + new HTTP (get_db teardown) tests **and live** (2 error traces persisted). |
| **AC-BI-25** | validation failure → one retry, then human | **PASS** | Engine tests: retry-then-succeed (validate+retry spans) and retry-twice-surface. HTTP-level not addable against the all-textarea BR template (documented, §5). |
| **AC-BI-26** | partial emit is success, invention is not | **PASS** | Engine + service + new HTTP test: grounded fields persist, ungrounded left blank, no 422; live turns never fabricated. |
| **AC-BI-27** | extraction never promotes | **PASS** | Service + HTTP re-fetch show `draft`; new HTTP test asserts draft; live BR stayed draft. |
| **AC-BI-28** | `grill-me-business` skill authored | **PASS** | Skill seeded (verify DB: `grill-me-business` "Business grill", active version), insert-if-missing; live system prompt is the business-register interviewer, grounding in the linked idea. |
| **AC-BI-29** | Grill tab UI + responsive | **DEFERRED** | FE unit tests pass (`grill-chat` 6 + `use-grill` 6): message list + input + coverage indicator + Generate + states. **375px/1280px browser verification NOT done** — the worktree's symlinked `node_modules` breaks the Next dev server (env/tooling, not S3 code). Needs a real `npm install` in the worktree to verify responsiveness in-browser. |
| **AC-BI-37** | live verification (DoD gate) | **FAIL** | Turns work against real Gemini; **Generate reliably 502s** (`gemini-2.5-flash` runaway → `MAX_TOKENS` → truncated JSON), the BR is never populated, so the result is not usable by a human. Root-caused + fix confirmed (§4.3). Kicked back to coder. |

---

## 7. Handoff to the coder (defects to fix — I did not modify app code)

1. **[BLOCKER, DoD gate] `app/integrations/gemini_provider.py` — structured output on `gemini-2.5-flash` runs away → `MAX_TOKENS` → truncated JSON → opaque 502.** Set `generationConfig.thinkingConfig.thinkingBudget=0` (confirmed fix: `STOP`, valid JSON, 111 tokens) for structured calls; surface `finishReason==MAX_TOKENS`/truncation as a clear distinct error rather than "malformed structured result"; consider raising `maxOutputTokens` and tightening the extraction directive against restating the transcript in field values. Without this, the seeded default model cannot generate a usable BR — the whole S3 payoff.
2. **[out of scope, pre-existing] Phase-A migration ids `0003`/`0004` exceed Alembic's `VARCHAR(32)`** (33 / 36 chars) — rename ≤32 chars; breaks real Postgres deploy, invisible to pytest.
3. **[verification debt] AC-BI-29 responsiveness (375/1280) not browser-verified** — the worktree can't boot the FE (symlinked `node_modules`). Run a real `npm install` in the worktree (or verify from the main checkout once merged) and screenshot both widths before calling AC-BI-29 done.

## 8. Files added by QA (tests only)
- `/Users/tehjayson/Documents/foundryx/foundryx-shared-service/.claude/worktrees/ideation-phase-b/service_backend/tests/test_ideation_grill_http.py`

## 9. Environment left running
- Verify backend `uvicorn` on **:8002** (DB `foundryx_ideation_verify`) — left up for the launching agent.
- **:3001 is now free** — the main-checkout Next dev server was stopped to attempt the (blocked) FE verify; restart it from the main checkout if needed.
