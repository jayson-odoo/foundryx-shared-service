"""Request body size cap for the API-key gateway (`/api/v1/omnichannel/`).

Pure ASGI. Bytes are counted as they stream through `receive()`, so a chunked
body with no Content-Length and a body longer than its declared length are
both stopped at the cap, and a declared Content-Length over the cap is refused
before any body is read. It runs before routing and before the key dependency,
so it holds for a missing or bad key too.

The answer is the gateway's own envelope: 422 `invalid_request` built with
`ApiError(...).to_body()`, the shape `install_api_error_handler`'s ApiError
handler emits (app/api_errors.py).
"""
from typing import Optional

from fastapi.responses import JSONResponse
from starlette._utils import get_route_path
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api_errors import ApiError

GATEWAY_PREFIX = "/api/v1/omnichannel/"
JSON_BODY_CAP = 256 * 1024
# Multipart sends carry a media file: the largest Meta media ceiling (DOCUMENT,
# 100 MiB, modules/omnichannel/services/media_pipeline.META_CEILINGS) plus a
# 1 MiB margin for the form framing and the payload part. Core must not import
# module code, so this is a core constant; tests keep it >= the module ceiling.
MULTIPART_BODY_CAP = 100 * 1024 * 1024 + 1024 * 1024
SEND_PATH = "/api/v1/omnichannel/messages"
TOO_LARGE = "Request body is too large."


def is_multipart(content_type: Optional[str]) -> bool:
    """The ONE multipart test, shared by this cap and the send route (case-insensitive)."""
    return (content_type or "").strip().lower().startswith("multipart/")


def _header(scope: Scope, name: bytes) -> Optional[str]:
    for key, value in scope.get("headers") or []:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


class GatewayBodyCapMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = get_route_path(scope)  # root_path stripped, so a configured root cannot skip the cap
        if not path.startswith(GATEWAY_PREFIX):
            await self.app(scope, receive, send)
            return

        # The multipart allowance is for the send route's file only; the client's
        # content type never raises the cap of any other route.
        is_send = scope.get("method") == "POST" and path.rstrip("/") == SEND_PATH
        multipart = is_send and is_multipart(_header(scope, b"content-type"))
        cap = MULTIPART_BODY_CAP if multipart else JSON_BODY_CAP

        declared = _header(scope, b"content-length")
        if declared is not None:
            try:
                if int(declared) > cap:
                    await self._refuse(scope, receive, send)
                    return
            except ValueError:
                pass  # a malformed length is left to the server and the stream count

        counted = 0
        refused = False

        async def counting_receive() -> Message:
            nonlocal counted, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message.get("type") == "http.request":
                counted += len(message.get("body", b"") or b"")
                if counted > cap:
                    # The framework turns an error raised from receive() into its
                    # own 400, so answer here, then end the stream for the app.
                    refused = True
                    await self._refuse(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not refused:  # the refusal is already on the wire; drop the app's own answer
                await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except ClientDisconnect:
            # Only the disconnect WE handed the app after refusing is expected;
            # a ClientDisconnect with no refusal, or any other error, still raises.
            if not refused:
                raise

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send) -> None:
        body = ApiError(422, "invalid_request", TOO_LARGE).to_body()
        await JSONResponse(status_code=422, content=body, headers={"connection": "close"})(scope, receive, send)
