"""OAuth discovery documents (RFC 9728 / RFC 8414) - public, per product."""
from fastapi import APIRouter, Depends, Request

from ..services.oauth_service import OAuthService
from ._common import oauth_service, require_method

router = APIRouter()

_METHODS = ["GET", "POST"]  # non-GET answers 405 only AFTER the product resolves (uniform 404 first)


@router.api_route("/.well-known/oauth-protected-resource/mcp/{p}", methods=_METHODS,
                  include_in_schema=False)
def protected_resource(request: Request, svc: OAuthService = Depends(oauth_service)) -> dict:
    require_method(request, "GET")
    return svc.protected_resource_metadata()


@router.api_route("/.well-known/oauth-authorization-server/mcp/{p}", methods=_METHODS,
                  include_in_schema=False)
def authorization_server(request: Request, svc: OAuthService = Depends(oauth_service)) -> dict:
    require_method(request, "GET")
    return svc.authorization_server_metadata()
