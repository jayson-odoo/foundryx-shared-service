"""One signed consumer-webhook POST attempt - CORE since plan 64 (R5).

Moved from ``modules/omnichannel/services/webhook_delivery.py`` so every Service
that pushes to a consumer-supplied URL (omnichannel, Lead Capture) runs the SAME
deadline-bounded, connect-guarded POST and the SAME outcome rules. The callers
keep their own delivery rows, retry ladders and signature headers; this module
only answers "did this one attempt succeed, and if not, why" (text that never
names the host or echoes the response body).

Rules carried over unchanged:
- The address check (``check``) runs INSIDE the attempt's budget and is re-run on
  every attempt: DNS may have been re-pointed since registration.
- One attempt (connect, TLS, headers, body) ends by its total deadline; the
  coroutine is cancelled at the deadline in every phase.
- At most ``RESPONSE_BYTE_CAP`` response bytes are read; the status code alone
  decides success.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple, Type

import anyio
import httpx

from app.services.url_guard import UrlGuardError

logger = logging.getLogger(__name__)

RESPONSE_BYTE_CAP = 65536
DEADLINE_ERROR = "Consumer did not answer within {seconds} seconds."


class DeliveryDeadlineError(Exception):
    """The attempt ran past its total deadline."""


class PostReply:
    """What one attempt needs from a response."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


@dataclass
class AttemptOutcome:
    ok: bool
    status_code: Optional[int]
    error: Optional[str]


def run_under_deadline(make_coro: Callable[[], Any], timeout: float) -> Any:
    """Run one coroutine on a fresh loop, cancelled at ``timeout`` (cancelling
    closes the connection in every phase). Raises DeliveryDeadlineError at the
    deadline. From inside a running loop (an async route reaching an eager
    task) the same work runs on a short-lived thread with its own loop.
    The loop's default executor is not joined: a host lookup cannot be
    interrupted and may finish on its own, but nothing is sent after the deadline."""

    def run() -> Any:
        async def bounded() -> Any:
            # Level-triggered: keeps cancelling until the work really ends, even
            # if something inside swallows one cancellation.
            with anyio.fail_after(timeout):
                return await make_coro()

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(bounded())
        except TimeoutError:
            raise DeliveryDeadlineError() from None
        finally:
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()
    box: Dict[str, Any] = {}

    def in_thread() -> None:
        try:
            box["value"] = run()
        except BaseException as exc:  # noqa: BLE001 - handed to the caller
            box["error"] = exc

    worker = threading.Thread(target=in_thread, name="webhook-post", daemon=True)
    worker.start()
    worker.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


async def post_async(
    url: str,
    content: bytes,
    headers: Dict[str, str],
    budget: float,
    transport_factory: Callable[[], httpx.AsyncBaseTransport],
) -> PostReply:
    """One streamed POST through the guarded transport ``transport_factory``
    builds (the connection goes only to an address that passed the guard at
    connect time). Building the transport loads the CA bundle (blocking), so it
    runs off the loop, inside the deadline."""
    transport = await anyio.to_thread.run_sync(transport_factory, abandon_on_cancel=True)
    async with httpx.AsyncClient(
        transport=transport, timeout=budget, follow_redirects=False
    ) as client:
        async with client.stream("POST", url, content=content, headers=headers) as resp:
            if not resp.is_stream_consumed:
                read = 0
                async for chunk in resp.aiter_raw():
                    read += len(chunk)
                    if read >= RESPONSE_BYTE_CAP:
                        break  # enough; the connection is closed without the rest
            return PostReply(resp.status_code)


def attempt_post(
    url: str,
    body: bytes,
    headers: Dict[str, str],
    *,
    deadline_seconds: float,
    check: Callable[[str, float], float],
    post: Callable[..., PostReply],
    refused: Tuple[Type[BaseException], ...] = (UrlGuardError,),
    log_ref: str = "",
) -> AttemptOutcome:
    """Run ONE attempt: ``check(url, budget) -> budget left`` (raises a
    ``refused`` error for a blocked target, DeliveryDeadlineError when the
    check used the whole budget), then ``post(url, content=, headers=,
    timeout=)``. Never raises; the outcome text names no host."""
    status_code: Optional[int] = None
    error: Optional[str] = None
    ok = False
    try:
        left = check(url, deadline_seconds)
        resp = post(url, content=body, headers=headers, timeout=left)
        status_code = resp.status_code
        ok = 200 <= resp.status_code < 300
        if not ok:
            error = f"Consumer returned {resp.status_code}."
    except refused as exc:
        # Blocked target - a real failure, but never a network call.
        error = f"Delivery refused: {exc}"  # guard text names no host
    except (DeliveryDeadlineError, httpx.TimeoutException):
        error = DEADLINE_ERROR.format(seconds=deadline_seconds)
    except httpx.HTTPError as exc:
        error = f"Delivery failed: {type(exc).__name__}."
    except Exception:  # noqa: BLE001 - any other send error is a failed attempt
        logger.exception("webhook delivery %s could not be attempted", log_ref)
        error = "Delivery could not be attempted."
    return AttemptOutcome(ok=ok, status_code=status_code, error=error)
