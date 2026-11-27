"""``python -m planner3d_worker --base-url ... --name mac-mini --engine stub --once``."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from planner3d_worker import keychain
from planner3d_worker.client import Worker
from planner3d_worker.engines import build_engine

CLAUDE_TIMEOUT_S = 3600


def _token() -> str:
    env = os.environ.get("PLANNER3D_WORKER_TOKEN")
    if env:
        return env
    try:
        return keychain.worker_token()
    except keychain.KeychainError as exc:
        raise SystemExit(f"no worker token: set PLANNER3D_WORKER_TOKEN or add the keychain item ({exc})")


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("planner3d_worker needs Python 3.11 or newer (found %d.%d)." % sys.version_info[:2])
    parser = argparse.ArgumentParser(prog="planner3d_worker")
    parser.add_argument("--base-url", required=True, help="Shared Service API origin")
    parser.add_argument("--name", required=True, help="this worker's name")
    parser.add_argument("--engine", choices=["stub", "triposr", "claude"], default="stub")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="handle at most one job")
    mode.add_argument("--loop", action="store_true", help="poll forever (default)")
    parser.add_argument("--idle-sleep", type=float, default=10.0, help="seconds to wait when idle or refused")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # a claude job runs up to three API calls and script runs, so it gets a longer job timeout
    extra = {"timeout_s": CLAUDE_TIMEOUT_S} if args.engine == "claude" else {}
    worker = Worker(base_url=args.base_url, token=_token(), name=args.name, engine=build_engine(args.engine), **extra)
    if args.once:
        worker.run_once()
        return 0
    try:
        worker.run_loop(idle_sleep_s=args.idle_sleep)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
