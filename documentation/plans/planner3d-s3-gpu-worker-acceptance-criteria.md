# PLANNER-3D-S3 acceptance criteria: 3D generation worker on the Mac mini

Lane PLANNER-3D-S3, branch `crew/planner-3d-s3`. Plan: `planner3d-s3-gpu-worker.md`.
Contract: `documentation/planner3d/module-contract.md` (v0.5, ss#332); amended by this lane where marked.
Proof: sorento-crm#2632 `documentation/plans/PLANNER-3D-PROOF/BUILD-SPLIT-INPUT.md` S3 + C5.

## SS job store and worker pull API (backend, module `planner3d`)

- AC-S3-01 A staff user with `planner3d.jobs.manage` submits 1 to 3 product photos (PNG, JPEG or WebP by magic bytes, 20 MB each) plus `dimensionsMm {length,width,height}` and gets 202 with a job in `queued`. A 4th photo, a non-image file renamed `.png`, or a missing dimension answers 422 and stores nothing.
- AC-S3-02 Without `planner3d.jobs.manage` the submit answers 403; without `planner3d.jobs.read` the list/detail/download answer 403. Every read is tenant-scoped: tenant B never sees, downloads or approves tenant A's job (404).
- AC-S3-03 The worker claims work with `POST /planner3d/worker/claim` and `Authorization: Bearer <worker token>`. No token, a wrong token, or an unset server token answers 401 and claims nothing. SS holds only the sha256 hash of the token (`PLANNER3D_WORKER_TOKEN_SHA256`, operator config like `GPU_WORKER_URL`), compares in constant time and never logs it.
- AC-S3-04 Claim hands out the OLDEST queued job, moves it to `running` and stamps the worker name; two concurrent claims never get the same job (guarded UPDATE, rowcount 1). An empty queue answers 204.
- AC-S3-05 Jobs submitted while no worker polls (Mac off) stay `queued` and are handed out in order once a worker claims again.
- AC-S3-06 The worker downloads inputs only for a job it holds (`running`, claimed by that worker name); other jobs answer 404.
- AC-S3-07 The worker uploads each output by name; SS caps the read (GLB 100 MB, image 40 MB, other export 100 MB), takes the real type from the first bytes (GLB `glTF` magic, PNG, OBJ/MTL/glTF JSON/STL/FBX signatures), computes its own sha256 and stores it through `storage_for_tenant`. A mismatch fails the upload with 422 and stores nothing.
- AC-S3-08 Heartbeat updates progress; a `running` job with no heartbeat for 10 minutes goes back to `queued` on the next claim (attempt count +1); after 3 attempts it fails with `worker_lost`.
- AC-S3-09 Finish `succeeded` on a model job needs 2 or 3 `candidate-N.glb` outputs; finish `failed` carries `error{code,message}`. Time (`gpuSeconds`) and peak memory (`peakRssMb`) are stored on the job.
- AC-S3-10 Staff approve one candidate (`POST /planner3d/jobs/{id}/approve {candidate}`): the job keeps the choice and a `convert` job is queued. Approving twice, approving a non-existent candidate or a job that is not `succeeded` answers 409/422.
- AC-S3-11 The finished `convert` job holds `model.glb`, `model.gltf`, `model.obj` + `model.mtl`, `model.fbx` and `model.stl`; staff download each by name.
- AC-S3-12 Paste-back guarantee: for a `render` job SS re-runs `product_diff` on the uploaded PNG against the scene and mask it sent; non-zero product diff fails the job with `product_changed` whatever the worker reported. A JPEG render output is refused.
- AC-S3-13 Cancel: a queued or running job can be cancelled by staff; the worker's next heartbeat answers 409 `cancelled` and the worker stops.

## Mac worker (`planner3d_worker/`)

- AC-S3-20 One job at a time. Before claiming, the worker reads swap use; above the cap (default 80 % of total swap or free RAM below 2 GB) it does not claim and waits.
- AC-S3-21 The model runs in a child process with a memory cap (default 8 GB RSS); over the cap the child is killed and the job fails with `memory_cap`.
- AC-S3-22 Engine `stub` (CI default) turns photos into a deterministic box GLB scaled to the dimensions, 2-3 candidates, under 2 s.
- AC-S3-23 Engine `triposr` (HF `stabilityai/TripoSR`, MIT) runs on `mps` when available, else CPU, and keeps the proof pipeline: cut out, reconstruct, stand upright, face forward, scale to LxWxH, JSON report per candidate.
- AC-S3-24 Every candidate GLB is Y up, metres, origin at the base centre, bounding box within 1 mm of the requested dimensions.
- AC-S3-25 Convert writes glTF (embedded buffers), OBJ + MTL, FBX (assimp) and STL from the approved GLB; each re-opens with a reader and keeps the triangle count.
- AC-S3-26 `render_only` port: `composite`, `product_diff`, `verify_saved`, `.png` only (B10), the proof's 28 test cases pass unchanged in meaning.
- AC-S3-27 Time and peak memory per job are measured and reported; one real TripoSR run on this Mac is recorded in the evidence file.
- AC-S3-28 The worker token and any HF token live in the macOS keychain (or the environment of the launchd job), never in a file in git.
