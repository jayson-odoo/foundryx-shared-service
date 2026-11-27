# planner3d_worker

The pull worker for the Planner 3D module. It runs on a Mac, asks the Shared Service for queued jobs
(`/planner3d/worker/claim`), runs them one at a time and sends the files back. Shared Service never calls
the Mac, so jobs queue while the Mac is off.

Job kinds: `model` (photos to 2-3 candidate GLBs), `render` (repaint a room, product pixels pasted back
unchanged), `convert` (one GLB to glb, gltf, obj+mtl, fbx, stl).

## Setup

```bash
# Python 3.11 or newer (for example `brew install python@3.13`, then python3.13)
python3.13 -m venv ~/planner3d/venv
~/planner3d/venv/bin/pip install -r planner3d_worker/requirements.txt
# model jobs only:
~/planner3d/venv/bin/pip install -r planner3d_worker/requirements-model.txt
git clone https://github.com/VAST-AI-Research/TripoSR.git ~/planner3d/triposr_src
brew install assimp          # FBX export
```

Environment (optional): `PLANNER3D_TRIPOSR_SRC` (default `~/planner3d/triposr_src`),
`PLANNER3D_TRIPOSR_WEIGHTS` (default the Hugging Face repo `stabilityai/TripoSR`; or a local folder with
`config.yaml` + `model.ckpt`).

## Secrets (login keychain)

Both items live in the login keychain. `-w` with no value makes `security` prompt for the secret, so it
never lands in shell history or the process list.

```bash
# Worker token: generate it, then paste it at the prompt.
openssl rand -hex 32
security add-generic-password -a planner3d -s planner3d-worker-token -w

# Hash for the server (PLANNER3D_WORKER_TOKEN_SHA256), computed straight from the keychain:
security find-generic-password -a planner3d -s planner3d-worker-token -w | tr -d '\n' | shasum -a 256

# Hugging Face read token, read only by the model child process (prompts for the value).
security add-generic-password -a planner3d -s huggingface-read-token -w
```

Shared Service stores only the sha256. The worker sends the token only to an `https` base URL
(plain `http` is accepted only for `localhost`, `127.0.0.1`, `testserver` and `.test` hosts).

`PLANNER3D_WORKER_TOKEN` in the environment overrides the keychain item.

## Run

```bash
python -m planner3d_worker --base-url https://SHARED_SERVICE_HOST --name mac-mini --engine stub --once
python -m planner3d_worker --base-url https://SHARED_SERVICE_HOST --name mac-mini --engine triposr --loop
```

`--engine claude` writes the model with the Anthropic API (model jobs only; job timeout 3600 s). Setup:

```bash
~/planner3d/venv/bin/pip install -r planner3d_worker/requirements-model.txt
security add-generic-password -a planner3d -s anthropic-api-key -w   # prompts for the value
```

Routing by category: `PLANNER3D_CLAUDE_ROUTING`, else `~/planner3d/claude-routing.json`, else the shipped
`planner3d_worker/claude/routing.default.json` (copy it to start; the default profile is Opus 5.5, primitives, 3 versions, for every product kind; a `categories` entry overrides it per category code). Spend ledger: `~/planner3d/claude-ledger.jsonl`
(one line per API call; the engine stops at `spendCapUsd`). Scripts run under macOS `sandbox-exec`, so this engine
needs macOS. One run outside Shared Service: `python -m planner3d_worker.claude_cli --help`.

`--engine stub` makes box models of the right size on the CPU (no model needed). The loop sleeps 10 s
when idle, refused by the health gate (swap above 80 percent or under 2 GB free RAM) or unable to
reach Shared Service.

## Run at login

Copy `launchd/com.foundryx.planner3d-worker.plist` to `~/Library/LaunchAgents/`, replace `WORKER_USER`
and `SHARED_SERVICE_HOST`, then:

```bash
launchctl load ~/Library/LaunchAgents/com.foundryx.planner3d-worker.plist
```

## Measuring a run

Each finished job carries `gpuSeconds` (wall time of the engine) and `peakRssMb` (peak memory of the
engine process and its children, sampled every 0.2 s). Read them from `GET /planner3d/jobs/{id}`. A child
over the memory cap (8 GB) is killed and the job fails with `memory_cap`; one over 30 minutes fails with
`timeout`.

## Tests

```bash
python -m pytest -q planner3d_worker/tests
```
