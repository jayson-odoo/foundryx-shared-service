"""Run a job in a child process with an RSS cap and a wall-clock timeout."""

from __future__ import annotations

import multiprocessing as mp
import time
from typing import Any, Callable

import psutil

SAMPLE_INTERVAL_S = 0.2


class MemoryCapExceeded(Exception):
    pass


class JobTimeout(Exception):
    pass


def _child(conn: Any, target: Callable, args: tuple) -> None:
    try:
        conn.send(("ok", target(*args)))
    except BaseException as exc:  # noqa: BLE001 - relayed to the parent
        conn.send(("err", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def _rss_mb(proc: psutil.Process) -> float:
    total = 0
    try:
        procs = [proc, *proc.children(recursive=True)]
    except psutil.Error:
        return 0.0
    for p in procs:
        try:
            total += p.memory_info().rss
        except psutil.Error:
            continue
    return total / (1024 * 1024)


def _kill_tree(proc: mp.Process) -> None:
    try:
        parent = psutil.Process(proc.pid)
        for c in parent.children(recursive=True):
            try:
                c.kill()
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    proc.kill()
    proc.join(5)


def run_capped(
    target: Callable, args: tuple, rss_cap_mb: float, timeout_s: float
) -> tuple[Any, float, float]:
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(child_conn, target, args), daemon=True)
    started = time.monotonic()
    proc.start()
    child_conn.close()
    ps = psutil.Process(proc.pid)
    peak = 0.0
    try:
        while True:
            peak = max(peak, _rss_mb(ps))
            if peak > rss_cap_mb:
                _kill_tree(proc)
                raise MemoryCapExceeded(f"rss {peak:.0f} MB over cap {rss_cap_mb:.0f} MB")
            if parent_conn.poll(0):
                break
            if not proc.is_alive() and not parent_conn.poll(0):
                raise RuntimeError(f"worker process died (exit {proc.exitcode})")
            if time.monotonic() - started > timeout_s:
                _kill_tree(proc)
                raise JobTimeout(f"job exceeded {timeout_s:.0f}s")
            time.sleep(SAMPLE_INTERVAL_S)
        kind, payload = parent_conn.recv()
        proc.join(5)
    finally:
        if proc.is_alive():
            _kill_tree(proc)
        parent_conn.close()
    if kind == "err":
        raise RuntimeError(payload)
    return payload, peak, time.monotonic() - started
