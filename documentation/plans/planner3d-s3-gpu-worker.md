# PLANNER-3D-S3 plan: 3D generation worker on the Mac mini

UAC: `planner3d-s3-gpu-worker-acceptance-criteria.md`. Size L. Branch `crew/planner-3d-s3`.

## Decisions (crew, 26 Nov, all four recommendations approved)

- D1 Transport is PULL: the Mac worker calls SS over the tailnet; SS never calls the worker. Jobs queue while
  the Mac is off. Contract section 6.2 is amended in this PR (the push table becomes the pull table).
- D2 Scope is the module skeleton only: `p3_job` + `p3_job_file`, the worker pull API with a hashed worker
  token, staff-only (session JWT + permission) submit / list / detail / approve / cancel / download. The
  tenant gateway (`fx3_live_` keys, `/uploads`, `/models`, `/renders`, webhooks, usage, caps) stays with S1.
- D3 Paste-back: the worker composites and returns `render.png` + `diff.json`; SS re-runs `product_diff` on
  the stored PNG against the scene + mask it sent and fails `product_changed` on any non-zero product diff.
- D4 Candidates: a model job finishes with `candidate-1..3.glb`; approve picks one and queues a `convert` job
  that returns `model.glb`, `model.gltf`, `model.obj`, `model.mtl`, `model.fbx`, `model.stl`. Contract
  sections 3.3 and 5.7 are amended; a `crew-note:` goes to the C5 lane PR.
- D5 Worker token: SS stores only `PLANNER3D_WORKER_TOKEN_SHA256` (operator config, CI secret, like
  `GPU_WORKER_URL`); the Mac keeps the plaintext in the login keychain (`security find-generic-password`).
- D6 Model: TripoSR (`stabilityai/TripoSR`, MIT, weights downloaded once). HF read token: login keychain,
  account `planner3d`, service `huggingface-read-token`, read at runtime by `keychain.py` and passed as
  `HF_TOKEN` to the model child process only; never printed, logged or written to a file. MPS when `torch.backends.mps.is_available()`, else CPU. 2-3 candidates = different
  foreground ratio / marching-cubes resolution per candidate.
- D7 FBX via the `assimp` CLI (`brew install assimp`, `apt install assimp-utils` in CI); glTF / OBJ+MTL / STL
  via trimesh.

## Backend: `service_backend/modules/planner3d/` (template: `modules/lead_capture/`)

- `manifest.json` (schema `app_planner3d`, version table `alembic_version_planner3d`, routers `staff`
  `/planner3d` and `worker` `/planner3d/worker` public, `storage_locations` for `p3_job_file.storage_key`).
- `db.py`, `models.py` (`P3Job`: id, tenant_id, kind model|render|convert, status
  queued|running|succeeded|failed|cancelled, engine, params_json, error_code, error_message, progress,
  gpu_seconds, peak_rss_mb, attempts, worker_name, claimed_at, heartbeat_at, approved_candidate,
  source_job_id, created_by_user_id, created/started/finished_at; `P3JobFile`: id, tenant_id, job_id,
  direction in|out, role, name, mime, size, sha256, storage_key).
- `permissions/permissions.csv`: `planner3d.jobs.view`, `planner3d.jobs.manage`; grant sweep to Admin in
  `bootstrap.install_tenant` + the migration backfill for tenants that already have the module.
- `repositories/job_repository.py` (claim = select oldest queued `FOR UPDATE SKIP LOCKED` + guarded UPDATE;
  stale-lease requeue), `services/job_service.py`, `services/worker_auth.py`, `services/sniff.py`
  (GLB/PNG/JPEG/WebP/OBJ/MTL/glTF/STL/FBX/JSON), `services/paste_back.py` (shared `product_diff`).
- `routers/staff.py`, `routers/worker.py`, `schemas.py` (camelCase wire, `ApiModel`).
- `alembic/versions/0001_planner3d_baseline.py`; conftest wiring in the four places (contract section 10).
- `app/config.py`: `planner3d_worker_token_sha256`, `planner3d_lease_minutes=10`.

## Worker: `planner3d_worker/` (repo root, own requirements)

- `requirements.txt` (httpx, numpy, pillow, trimesh, psutil) and `requirements-model.txt` (torch, rembg,
  TripoSR deps per proof pins).
- `client.py` loop: health gate (swap / free RAM) -> claim -> download inputs -> run engine in a child
  process with RSS cap -> upload outputs -> finish. One job at a time. Heartbeat every 15 s.
- `engines/stub.py`, `engines/triposr.py`, `image_to_3d.py` (port of the proof, 349 lines), `render_only.py`
  (port, 221 lines) + `tests/test_render_only.py` (28 cases), `convert.py`, `health.py`, `keychain.py`.
- `launchd/com.foundryx.planner3d-worker.plist` template + `README.md` (setup, keychain, measure).
- CI: new job in `.github/workflows/deploy.yml` running `pytest planner3d_worker/tests` with the stub engine.

## Slices (red test first, then code, commit each)

- S0 plan + UAC + contract amendments (6.2, 3.3, 5.7).
- S1 worker-side pure code: render_only port + 28 tests; convert + tests; stub engine + tests.
- S2 backend module: tester red tests (AC-S3-01..13), then coder.
- S3 worker client against SS (end-to-end test with the stub engine against the FastAPI test app).
- S4 TripoSR engine on this Mac: one measured run (time, peak RSS) when swap allows; evidence file.
- S5 review (reviewer + security-reviewer in parallel), CI green, PR, guide note to C5.

## Test list (tester writes these red first)

Backend: submit happy/422 (4 photos, fake PNG, missing dims)/403; tenant isolation on list/detail/download/
approve; worker 401 (none, wrong, unset); claim order + 204 + concurrent claim; input download only when held;
output sniff mismatch 422 + sha256 stored; finish needs 2-3 candidates; stale lease requeue + `worker_lost`
after 3; approve -> convert job queued, double approve 409; render product_changed; cancel -> heartbeat 409.
Worker: 28 render_only cases; convert round-trip per format; stub determinism + dimensions; health gate refuses
on high swap; memory cap kills child.
