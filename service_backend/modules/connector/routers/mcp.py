"""MCP endpoint ``POST /mcp/{p}`` - Bearer auth, JSON-RPC in/out. HTTP only."""
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from ..services import mcp_service
from ..services.oauth_service import OAuthService, Unauthorized
from ._common import oauth_service, require_method

router = APIRouter()

MAX_BODY_BYTES = 1_048_576


@router.api_route("/{p}", methods=["GET", "POST"], include_in_schema=False)
async def mcp(request: Request, svc: OAuthService = Depends(oauth_service)) -> Response:
    require_method(request, "POST")
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    try:
        if scheme.lower() != "bearer":
            raise Unauthorized()
        grant = svc.authenticate_access(token.strip())
    except Unauthorized:
        return JSONResponse(
            {"error": "invalid_token"}, status_code=401,
            headers={"WWW-Authenticate": (
                f'Bearer resource_metadata="{svc.base}/.well-known/oauth-protected-resource/mcp/{svc.product.key}"'
            )},
        )
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return JSONResponse(mcp_service.rpc_error(None, mcp_service.INVALID_REQUEST, "Too large"),
                            status_code=413)
    try:
        message = json.loads(body)
    except ValueError:
        return JSONResponse(mcp_service.rpc_error(None, mcp_service.PARSE_ERROR, "Parse error"))
    out = mcp_service.handle(svc.product, grant, message)
    if out is None:
        return Response(status_code=202)
    return JSONResponse(out, headers={"Cache-Control": "no-store"})
