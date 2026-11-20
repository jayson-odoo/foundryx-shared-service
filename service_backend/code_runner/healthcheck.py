"""Container health probe that never dials a socket.

The runner's seccomp profile denies ``connect``, so the usual "GET /health
over loopback" probe cannot run inside the container. Instead: (1) the HTTP
server must be LISTENING on the runner port (read from ``/proc/net/tcp``),
and (2) the sandbox must still execute a trivial job end to end.
"""
from __future__ import annotations

import os
import sys


_PROC_TABLES = ("/proc/net/tcp", "/proc/net/tcp6")


def _listening(port: int, tables=_PROC_TABLES) -> bool:
    needle = f":{port:04X} "
    for table in tables:
        try:
            with open(table, encoding="utf-8") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            parts = row.split()
            if len(parts) > 3 and needle in f" {parts[1]} " and parts[3] == "0A":  # 0A = LISTEN
                return True
    return False


def main() -> int:
    from code_runner.sandbox import execute

    port = int(os.environ.get("CODE_RUNNER_PORT") or 8011)
    if not _listening(port):
        print(f"runner is not listening on {port}", file=sys.stderr)
        return 1
    result = execute("result = {'ok': True}", {})
    if not result.ok or result.result != {"ok": True}:
        print(f"sandbox smoke failed: {result.termination} {result.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
