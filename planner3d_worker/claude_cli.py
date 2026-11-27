"""Run the claude-procedural engine once, outside Shared Service (step 1 API confirmation and the pilot).

    python -m planner3d_worker.claude_cli --photo P [--photo P] [--drawing D] --dims L,W,H \
        [--category CODE] [--model M] [--approach sdf|primitives] --out DIR --ledger PATH --ref CODE

The API key comes from the keychain inside the engine; it is never an argument.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from planner3d_worker.claude.ledger import Ledger
from planner3d_worker.claude.routing import Routing
from planner3d_worker.engines.claude_procedural import ClaudeProceduralEngine, EngineFailure


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="planner3d_worker.claude_cli")
    ap.add_argument("--photo", action="append", required=True, type=Path)
    ap.add_argument("--drawing", type=Path)
    ap.add_argument("--dims", required=True, help="length,width,height in mm")
    ap.add_argument("--category")
    ap.add_argument("--model")
    ap.add_argument("--approach", choices=["sdf", "primitives"])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ledger", type=Path)
    ap.add_argument("--routing", type=Path, help="routing JSON (default: env / ~/planner3d/claude-routing.json / shipped)")
    ap.add_argument("--ref", required=True, help="product code, recorded in the ledger")
    args = ap.parse_args(argv)

    try:
        length, width, height = (float(x) for x in args.dims.split(","))
    except ValueError:
        ap.error("--dims must be L,W,H in mm")
    routing = Routing.load(args.routing)
    if args.model or args.approach:
        profile = routing.profile_for({"code": args.category} if args.category else None)
        profile = dataclasses.replace(profile, model=args.model or profile.model, approach=args.approach or profile.approach)
        routing = _Pinned(routing, profile)
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = {f"photo-{i}{p.suffix}": str(p) for i, p in enumerate(args.photo, 1)}
    if args.drawing:
        inputs[f"drawing{args.drawing.suffix}"] = str(args.drawing)
    params = {"dimensionsMm": {"length": length, "width": width, "height": height}, "productCode": args.ref, "jobRef": args.ref}
    if args.category:
        params["category"] = {"code": args.category, "name": args.category}
    engine = ClaudeProceduralEngine(routing=routing, ledger=Ledger(args.ledger) if args.ledger else None)
    try:
        produced = engine.run("model", inputs, params, args.out)
    except EngineFailure as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for name, role in produced:
        print(f"{role}\t{args.out / name}")
    return 0


class _Pinned:
    """Routing view that always answers with one profile (CLI --model/--approach)."""

    def __init__(self, routing: Routing, profile):
        self._routing = routing
        self._profile = profile
        self.spend_cap_usd = routing.spend_cap_usd

    def profile_for(self, category):
        return self._profile

    def prices(self, model):
        return self._routing.prices(model)


if __name__ == "__main__":
    sys.exit(main())
