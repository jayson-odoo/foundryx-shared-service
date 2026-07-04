"""Structured error envelope for the public gateway API (`/api/v1/*`).

Every public-API error returns ``{"error": {"code", "message", "details"?}}``
with a stable, machine-readable ``code`` (plan sprint-1/01 AC-01-36). Internal
(session-authed) endpoints keep FastAPI's default ``{"detail": …}`` shape.
"""
from typing import Any, Optional

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

PUBLIC_API_PREFIX = "/api/v1/"


class ApiError(Exception):
    """Raise inside a public `/api/v1/*` handler to emit the structured envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def to_body(self) -> dict:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            err["details"] = self.details
        return {"error": err}


def install_api_error_handler(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:  # noqa: ANN202
        return JSONResponse(status_code=exc.status_code, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(  # noqa: ANN202
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Public gateway paths get the structured envelope (AC-01-36); internal
        # endpoints keep FastAPI's default {detail:[...]} shape.
        if request.url.path.startswith(PUBLIC_API_PREFIX):
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=ApiError(
                    422,
                    "invalid_request",
                    "Request validation failed.",
                    jsonable_encoder(exc.errors()),
                ).to_body(),
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": jsonable_encoder(exc.errors())},
        )
