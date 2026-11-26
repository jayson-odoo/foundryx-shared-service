# TripoSR on the Mac mini: first measured job (AC-S3-23, AC-S3-24, AC-S3-27)

Date: 26/11/2026. Machine: Mac mini, Apple Silicon (arm64), 16 GB RAM, macOS 26.5.1.
Stack: `~/planner3d/venv` (Python 3.13, torch 2.15.0, `torch.backends.mps.is_available() == True`),
`planner3d_worker/requirements.txt` + `requirements-model.txt`, TripoSR source `~/planner3d/triposr_src`
(git clone of VAST-AI-Research/TripoSR), weights `stabilityai/TripoSR` from Hugging Face, read token taken
from the login keychain inside the child process only.

## Input

One product photo: the catalogue-photo panel (420 x 400 px) of the proof's
`p1/SRT6753-WH-compare.jpg` (sorento-crm#2632). Catalogue size: length 395 mm, width 480 mm,
height 200 mm (`dimensionsMm`).

## How it ran

`TripoSREngine(n=3).run("model", ...)` through `planner3d_worker.runner.run_capped` (child process,
RSS cap 8192 MB, timeout 1800 s), after `health.can_start` passed (swap 79 % used of 8 GB at start).
Same path the pull client uses; only the SS round trip is left out.

## Result

| Measure | Value |
|---|---|
| Wall time, 3 candidates, cold (includes first download of u2net 176 MB and TripoSR weights) | 174.7 s |
| Peak RSS (runner, process tree) | 2312 MB |
| Max resident set (`/usr/bin/time -l`) | 2470 MB |
| Device per candidate | `mps` (all three) |
| Candidates | `candidate-1.glb` (fg 0.85, mc 256), `candidate-2.glb` (fg 0.75, mc 256), `candidate-3.glb` (fg 0.9, mc 320) |
| GLB size | about 400 KB each, 20,000 faces |
| Bounding box after fit (mm, X Y Z) | 395.0 x 200.0 x 480.0 for all three |
| Base and centre | min Y 0.0, X and Z centred at 0.0 |
| Max per-axis stretch to the catalogue box | 27.3 %, 31.6 %, 26.9 % |

Proof baseline for the same product on 4 CPU cores: 32.4 s for ONE candidate including a 9.2 s model
load (`p1/SRT6753-WH.json`).

## Open

- A warm-cache run (weights already on disk) was held because swap rose to 89 % from other lanes right
  after the first run; the worker's own gate (80 %) would refuse it too. The steady-state time per job is
  therefore not yet measured separately from the one-time downloads.
- Look of the candidates (invented parts, chrome) is judged by C5's approve step, not here.
