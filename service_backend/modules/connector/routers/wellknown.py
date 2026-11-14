"""OAuth discovery documents (RFC 9728 / RFC 8414) - public, per product.

Two URL forms per document:

- ``/.well-known/<kind>/mcp/{p}`` - the base-relative form. It is what the 401
  ``WWW-Authenticate`` header names (``<base>/.well-known/...``) and, behind a
  path-stripping proxy, what that URL arrives as.
- ``/.well-known/<kind>/<prefix>/mcp/{p}`` - the RFC 9728 / RFC 8414 path-inserted
  form an MCP client derives from the resource / issuer URL when the public base
  URL has a path (prod: ``https://<host>/be``). It is requested at the host ROOT,
  so the proxy forwards it unstripped (scripts/blue_green_deploy.sh). Served only
  when ``<prefix>`` is exactly the configured base URL's path - anything else is
  the same uniform 404 as an unknown product.
"""

from __future__ import annotations
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request

from ..services.oauth_service import OAuthService
from ._common import oauth_service, require_method

router = APIRouter()

_METHODS = ["GET", "POST"]  # non-GET answers 405 only AFTER the product resolves (uniform 404 first)


def _require_prefix(svc: OAuthService, prefix: str) -> None:
    if "/" + prefix != urlparse(svc.base).path:
        raise HTTPException(status_code=404, detail="Not found")


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


@router.api_route("/.well-known/oauth-protected-resource/{prefix:path}/mcp/{p}", methods=_METHODS,
                  include_in_schema=False)
def protected_resource_prefixed(prefix: str, request: Request,
                                svc: OAuthService = Depends(oauth_service)) -> dict:
    _require_prefix(svc, prefix)
    require_method(request, "GET")
    return svc.protected_resource_metadata()


@router.api_route("/.well-known/oauth-authorization-server/{prefix:path}/mcp/{p}", methods=_METHODS,
                  include_in_schema=False)
def authorization_server_prefixed(prefix: str, request: Request,
                                  svc: OAuthService = Depends(oauth_service)) -> dict:
    _require_prefix(svc, prefix)
    require_method(request, "GET")
    return svc.authorization_server_metadata()
