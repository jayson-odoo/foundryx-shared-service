"""Engines for the planner3d worker. An engine has ``kinds`` (job kinds it can
run) and ``run(kind, inputs, params, out_dir) -> [(file name, role)]``; it runs
inside the capped child process, so it must be picklable."""

from __future__ import annotations


class MultiEngine:
    """Routes each job kind to the engine that owns it."""

    def __init__(self, engines):
        self._by_kind = {kind: engine for engine in engines for kind in engine.kinds}
        self.kinds = list(self._by_kind)

    def run(self, kind, inputs, params, out_dir):
        return self._by_kind[kind].run(kind, inputs, params, out_dir)


def build_engine(name: str) -> MultiEngine:
    from .convert_engine import ConvertEngine
    from .render_engine import RenderEngine

    if name == "stub":
        from .stub import StubEngine

        return MultiEngine([StubEngine(), RenderEngine(), ConvertEngine()])
    if name == "triposr":
        from .triposr import TripoSREngine

        return MultiEngine([TripoSREngine(), RenderEngine(), ConvertEngine()])
    if name == "claude":
        from .claude_procedural import ClaudeProceduralEngine

        return MultiEngine([ClaudeProceduralEngine(), RenderEngine(), ConvertEngine()])
    raise ValueError(f"unknown engine: {name}")
