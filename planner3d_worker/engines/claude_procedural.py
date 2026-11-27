"""``claude-procedural`` engine (plan planner3d-claude-procedural-engine, D1-D8).

Claude writes a Python script (trimesh + manifold3d) that builds the product; the
script runs in the macOS sandbox (``claude/sandbox.py``), the GLB is measured and
rendered, and the renders go back to Claude for at most ``max_versions - 1``
refine turns. The API key is read from the keychain at runtime inside this
engine only; it is never logged, written, put in an exception or passed on to the sandbox.
"""

from __future__ import annotations

import json
import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import trimesh

from planner3d_worker import keychain
from planner3d_worker.claude import prompts, sandbox
from planner3d_worker.claude.colours import photo_colours
from planner3d_worker.claude.ledger import Ledger, cost_usd
from planner3d_worker.claude.routing import Profile, Routing
from planner3d_worker.raster import glb_materials, render_views

KEY_ACCOUNT = "planner3d"
KEY_SERVICE = "anthropic-api-key"
MAX_TOKENS = 32000
MIN_GOOD = 2
MAX_FACES = 300_000
RENDER_FACES = 60_000  # a model over this is decimated (on a copy) before the four renders
DEFAULT_TIME_BUDGET_S = 3000.0
BAD_STOPS = {"refusal": "the model refused the request", "max_tokens": "the reply hit the output token limit"}


class EngineFailure(Exception):
    """``code`` is one of spend_cap | generation_failed | no_api_key | sandbox_unavailable."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class _Version:
    def __init__(self, n: int, model: str):
        self.n = n
        self.model = model
        self.usage: dict = {}
        self.usd = 0.0
        self.seconds = 0.0
        self.script = ""
        self.glb: Optional[bytes] = None
        self.measured: dict = {}
        self.error: Optional[str] = None
        self.faces = 0
        self.response = ""
        self.parts: list = []


def _usage_dict(usage: Any) -> dict:
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {k: int(getattr(usage, k, 0) or 0) for k in keys}


def _for_render(scene, faces: int):
    """The scene, or a decimated copy (each part to its share of RENDER_FACES) when it is over budget."""
    if faces <= RENDER_FACES:
        return scene
    try:
        ratio = RENDER_FACES / faces
        copy = scene.copy()
        for name, geom in list(copy.geometry.items()):
            target = max(4, int(len(geom.faces) * ratio))
            if len(geom.faces) > target:
                copy.geometry[name] = geom.simplify_quadric_decimation(face_count=target)
        return copy
    except Exception:  # noqa: BLE001 - rendering the full model is the fallback
        return scene


def _parts(scene, limit: int = 20) -> list[dict]:
    """Name, extents and centre in mm (length X, width Z, height Y) of each geometry node."""
    parts: list[dict] = []
    try:
        for node in list(scene.graph.nodes_geometry)[:limit]:
            transform, geom = scene.graph[node]
            g = scene.geometry[geom].copy()
            g.apply_transform(transform)
            lo, hi = g.bounds
            ext, mid = (hi - lo) * 1000.0, (hi + lo) * 500.0
            parts.append({
                "name": str(node)[:40],
                "extentsMm": [round(float(ext[0]), 1), round(float(ext[2]), 1), round(float(ext[1]), 1)],
                "centreMm": [round(float(mid[0]), 1), round(float(mid[1]), 1), round(float(mid[2]), 1)],
            })
    except Exception:  # noqa: BLE001 - the part list is advisory only
        return parts
    return parts


def _text_of(message: Any) -> str:
    return "\n".join(b.text for b in (message.content or []) if getattr(b, "type", None) == "text")


class ClaudeProceduralEngine:
    kinds = ["model"]

    def __init__(
        self,
        client: Any = None,
        routing: Optional[Routing] = None,
        ledger: Optional[Ledger] = None,
        run_script: Optional[Callable] = None,
        time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    ):
        self.time_budget_s = time_budget_s
        self._client = client
        self._routing = routing
        self._ledger = ledger
        self._run_script = run_script

    # ── wiring ──────────────────────────────────────────────────────────────

    def _client_or_key(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            key = keychain.read_secret(KEY_ACCOUNT, KEY_SERVICE)
        except keychain.KeychainError:
            raise EngineFailure("no_api_key", "no Anthropic API key in the keychain") from None
        import anthropic

        return anthropic.Anthropic(api_key=key)

    # ── run ─────────────────────────────────────────────────────────────────

    def run(self, kind: str, inputs: dict, params: dict, out_dir) -> list[tuple[str, str]]:
        if kind != "model":
            raise ValueError(f"unsupported kind: {kind}")
        out = Path(out_dir)
        routing = self._routing or Routing.load()
        ledger = self._ledger or Ledger()
        run_script = self._run_script
        if run_script is None:
            if not sandbox.available():
                raise EngineFailure("sandbox_unavailable", "the script sandbox is not available on this machine")
            run_script = sandbox.run_script
        spec = {k: params["dimensionsMm"][k] for k in ("length", "width", "height")}
        category = params.get("category")
        profile = routing.profile_for(category)
        product_code = params.get("productCode") or ""
        job_ref = params.get("_jobId") or params.get("jobRef") or ""
        photos = [Path(p) for n, p in sorted(inputs.items()) if n.startswith("photo")]
        drawing = next((Path(p) for n, p in sorted(inputs.items()) if n.startswith("drawing")), None)
        try:
            routing.prices(profile.model)
        except KeyError:
            raise EngineFailure("generation_failed", f"no price for model {profile.model}") from None
        client = self._client_or_key()
        started = time.monotonic()
        durations: list[float] = []

        try:
            first = prompts.first_turn(photos, drawing, spec, category, profile)
            finish = photo_colours(photos[0]) if photos else []
            if finish:  # after the image guard in first_turn; added to the request text
                first[-1] = {"type": "text", "text": first[-1]["text"] + "\n" + prompts.finish_line(finish)}
        except prompts.ImageTooLarge as exc:
            raise EngineFailure("generation_failed", f"bad input: {exc}") from None
        messages: list[dict] = [{"role": "user", "content": first}]
        versions: list[_Version] = []
        limit = profile.max_versions
        n = 0
        while True:
            n += 1
            good = [v for v in versions if v.glb is not None]
            extra = n > limit  # one more attempt, only while fewer than MIN_GOOD versions are usable
            if extra and (len(good) >= MIN_GOOD or n > limit + 1):
                break
            if ledger.total_usd() >= routing.spend_cap_usd:
                if len(good) >= MIN_GOOD or extra:
                    break
                raise EngineFailure("spend_cap", f"the US${routing.spend_cap_usd:.0f} spend cap is reached")
            if (len(good) >= MIN_GOOD or extra) and durations and time.monotonic() - started + max(durations) > self.time_budget_s:
                break
            ver = _Version(n, profile.model)
            versions.append(ver)
            began = time.monotonic()
            self._one_version(client, routing, ledger, profile, messages, ver, spec, run_script, out, product_code, job_ref)
            if not self._write_trail(out, ver):
                ver.glb = None
                ver.error = "the trail directory could not be created"
            durations.append(time.monotonic() - began)
        good = [v for v in versions if v.glb is not None]
        if len(good) < MIN_GOOD:
            last = next((v.error for v in reversed(versions) if v.error), "no usable model")
            raise EngineFailure("generation_failed", f"{len(good)} of {len(versions)} versions produced a model; last error: {last}"[:300])
        return self._write_candidates(good, out, spec)

    # ── one version ─────────────────────────────────────────────────────────

    def _one_version(self, client, routing, ledger, profile: Profile, messages, ver: _Version, spec, run_script, out: Path, product_code, job_ref) -> None:
        try:
            with client.messages.stream(
                model=profile.model,
                max_tokens=MAX_TOKENS,
                system=prompts.SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                output_config={"effort": profile.effort},
                messages=list(messages),
            ) as stream:
                message = stream.get_final_message()
        except EngineFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - the SDK error text is never relayed (could echo request details)
            name = type(exc).__name__
            if name in ("AuthenticationError", "PermissionDeniedError"):
                raise EngineFailure("no_api_key", "the Anthropic API rejected the key") from None
            ver.error = f"API call failed ({name})"
            self._queue_error(messages, None, ver.error)
            return

        ver.response = _text_of(message)
        ver.usage = _usage_dict(message.usage)
        ver.usd = cost_usd(ver.usage, routing.prices(profile.model))
        ledger.append({
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "jobRef": job_ref,
            "productCode": product_code,
            "model": profile.model,
            "inputTokens": ver.usage["input_tokens"],
            "outputTokens": ver.usage["output_tokens"],
            "cacheReadTokens": ver.usage["cache_read_input_tokens"],
            "cacheCreationTokens": ver.usage["cache_creation_input_tokens"],
            "usd": ver.usd,
        })

        # text only: earlier thinking blocks are not needed for a plain (tool-less) conversation
        content = [{"type": "text", "text": b.text} for b in (message.content or []) if getattr(b, "type", None) == "text" and b.text]
        stop = getattr(message, "stop_reason", None)
        if stop in BAD_STOPS:
            ver.error = BAD_STOPS[stop]
            self._queue_error(messages, content, ver.error)
            return
        try:
            ver.script = prompts.extract_script(_text_of(message))
        except ValueError as exc:
            ver.error = str(exc)
            self._queue_error(messages, content, ver.error)
            return
        try:
            sandbox.check_script(ver.script)
        except sandbox.ScriptRejected as exc:
            ver.error = f"script rejected: {exc}"
            self._queue_error(messages, content, ver.error)
            return

        work = out / f"work-{ver.n}"
        work.mkdir(parents=True, exist_ok=True)
        (work / "params.json").write_text(json.dumps({"dimensionsMm": spec}), encoding="utf-8")
        try:
            result = run_script(ver.script, work, sandbox.Limits())
        except sandbox.SandboxUnavailable:
            raise EngineFailure("sandbox_unavailable", "the script sandbox is not available on this machine") from None
        except sandbox.ScriptRejected as exc:
            ver.error = f"script rejected: {exc}"
            self._queue_error(messages, content, ver.error)
            return
        ver.seconds = float(result.seconds)
        data = result.glb_bytes
        if data is None and result.ok and result.glb is not None:
            data = sandbox.read_regular_file(Path(result.glb), sandbox.Limits().output_mb * 1024 * 1024)
            if data is None:
                result = sandbox.RunResult(False, None, "", result.seconds, "bad_output")
        if not result.ok or not data:
            ver.error = f"the script failed ({result.reason}):\n{result.stderr_tail}".strip()
            self._queue_error(messages, content, ver.error)
            return
        try:
            scene = trimesh.load(io.BytesIO(data), file_type="glb", force="scene", skip_materials=True)
            mesh = scene.to_geometry() if hasattr(scene, "to_geometry") else scene.dump(concatenate=True)
            faces = int(len(mesh.faces))
            if faces > MAX_FACES:
                ver.error = f"the model has too many faces ({faces}, at most {MAX_FACES}); simplify it (fewer segments, coarser grid)"
                self._queue_error(messages, content, ver.error)
                return
            ext = (scene.bounds[1] - scene.bounds[0]) * 1000.0
            if not (ext > 0).all():
                raise ValueError("the model has no volume")
        except Exception as exc:  # noqa: BLE001 - a bad GLB is a failed version
            ver.error = f"model.glb could not be used: {type(exc).__name__}: {exc}"[:600]
            self._queue_error(messages, content, ver.error)
            return
        ver.glb = data
        ver.faces = faces
        ver.parts = _parts(scene)
        ver.measured = {"length": round(float(ext[0]), 2), "width": round(float(ext[2]), 2), "height": round(float(ext[1]), 2)}
        renders = render_views(_for_render(scene, faces), materials=glb_materials(data))
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": prompts.refine_turn(renders, ver.measured, spec, None, faces=ver.faces, parts=ver.parts, over_budget=ver.faces > prompts.TRIANGLE_BUDGET)})

    @staticmethod
    def _write_trail(out: Path, ver: _Version) -> bool:
        """Debug trail in ``trail-N``, a directory the script never had access to, created here after
        the script ran; files are created exclusively without following links. Never uploaded (only
        candidate-N.* are returned). False when the directory could not be created fresh."""
        trail = out / f"trail-{ver.n}"
        try:
            trail.mkdir(parents=True, exist_ok=False)
            for name, text in (("response.txt", ver.response), ("error.txt", ver.error or "")):
                if not text:
                    continue
                fd = os.open(trail / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(text)
        except OSError:
            return False
        return True

    @staticmethod
    def _queue_error(messages: list, content: Optional[list], error: str) -> None:
        """Carry a failed version into the next turn: the assistant reply (when it has
        content) then a user turn holding the error."""
        if content:
            messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": [{"type": "text", "text": (
            "That version failed and produced no model.\n" + error + "\nFix it and return the full corrected script in one ```python block."
        )}]})

    # ── candidates ──────────────────────────────────────────────────────────

    def _write_candidates(self, good: list[_Version], out: Path, spec: dict) -> list[tuple[str, str]]:
        produced: list[tuple[str, str]] = []
        for idx, ver in enumerate(reversed(good[-3:]), start=1):
            glb_name, json_name = f"candidate-{idx}.glb", f"candidate-{idx}.json"
            (out / glb_name).write_bytes(ver.glb)
            report = {
                "engine": "claude-procedural",
                "model": ver.model,
                "version": ver.n,
                "usage": ver.usage,
                "usd": ver.usd,
                "seconds": ver.seconds,
                "measuredMm": ver.measured,
                "specMm": spec,
                "dimsErrorMm": {k: round(ver.measured[k] - spec[k], 2) for k in spec},
                "script": ver.script,
            }
            (out / json_name).write_text(json.dumps(report, indent=1), encoding="utf-8")
            produced += [(glb_name, "candidate"), (json_name, "report")]
        return produced
