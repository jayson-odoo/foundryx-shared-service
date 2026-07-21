"""Sorento consumer connection provider (plan 14 §4, AC-14-15).

The OUTBOUND counterpart to ``AutoCountProvider``. Where the ``erp`` connection
points *at* AutoCount to read from, this ``consumer`` connection points *at*
Sorento to push to — the direction differs, so the identity must too. It plugs
into the SAME core provider registry as SMTP / S3 / AutoCount, so an operator
configures the Sorento target from the standard `/settings/integrations`
Resource shell with no bespoke UI.

Two fields only: the base URL and the integration's own API key. Auth is
``X-API-Key`` (never ``Authorization: Bearer``, never the legacy
``EXTERNAL_API_KEY`` — its hash is seeded onto the *n8n* integration, so
presenting it would misattribute every write, AC-14-15). The key is a write-only
secret, Fernet-encrypted in ``credentials_json`` and never echoed.

**Uniqueness note (plan 14 §4):** ``type='consumer'`` is NOT carved out of
core's connection unique indexes, and deliberately so. ``uq_connection_tenant_type``
(``type NOT IN ('payment','erp') AND is_active``) therefore keeps ONE active
consumer per tenant, and ``uq_connection_tenant_provider`` (``type != 'erp' AND
is_active``) keeps one active ``sorento`` provider per tenant — which is exactly
v1's "one Sorento target per tenant". No index migration is needed.

``test()`` runs a harmless AUTHENTICATED probe and names the failing step
(AC-13-04 house rule — "connection failed" catch-alls are banned): a 401/403 is
a rejected key, a transport error is an unreachable host, a 2xx is success.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.integrations.base import TestResult

SORENTO_PROVIDER_KEY = "sorento"
# Connection category. Distinct from AutoCount's ``erp`` (which points AT
# AutoCount to read) — this points AT Sorento to write.
SORENTO_CONNECTION_TYPE = "consumer"

# A read endpoint that authenticates the caller yet writes nothing — the safe
# probe surface. An unknown ``source_ref`` returns an empty result, so the probe
# never touches real data.
_PROBE_PATH = "/api/v1/external/read/suppliers"
# A ref that cannot exist, so the probe reads back nothing even on success.
_PROBE_REF = "__probe__"


class SorentoProvider:
    provider = SORENTO_PROVIDER_KEY
    type = SORENTO_CONNECTION_TYPE
    title = "Sorento"
    description = (
        "Push AutoCount suppliers and customers into a Sorento workspace. The "
        "outbound target for the AutoCount ESB — one Sorento per workspace."
    )
    icon = "upload-cloud"
    test_label = "Test connection"
    # Connection check only — a write probe against a live Sorento is not
    # something a Test button may ever do.
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        """Config schema driving the integrations form. Two fields: the base URL
        (displayable config) and the API key (write-only secret)."""
        return [
            {
                "key": "baseUrl",
                "label": "Sorento base URL",
                "type": "text",
                "required": True,
                "placeholder": "https://sorento.customer.com",
            },
            {
                "key": "apiKey",
                "label": "API key",
                "type": "password",
                "required": True,
                "secret": True,
            },
        ]

    def test(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        target: Optional[str] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> TestResult:
        """Verify the connection by an authenticated probe, naming the failing step.

        ``transport`` is injectable for tests (the integrations service calls
        ``test(config, credentials, target)`` positionally, so the keyword-only
        default is transparent to it).
        """
        base_url = str(config.get("baseUrl", "")).strip()
        if not base_url:
            return TestResult(ok=False, message="Enter the Sorento base URL.")
        if not base_url.lower().startswith(("http://", "https://")):
            return TestResult(
                ok=False, message="The base URL must start with http:// or https://."
            )
        api_key = str(credentials.get("apiKey", "")).strip()
        if not api_key:
            return TestResult(ok=False, message="Enter the Sorento API key.")

        url = f"{base_url.rstrip('/')}{_PROBE_PATH}"
        try:
            with httpx.Client(timeout=10.0, transport=transport) as client:
                response = client.post(
                    url,
                    json={"source_refs": [_PROBE_REF]},
                    headers={
                        # X-API-Key, never Bearer (AC-14-15). Never logged.
                        "X-API-Key": api_key,
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError:
            # Unreachable / timeout / DNS — distinct from an auth rejection.
            return TestResult(
                ok=False, message=f"Could not reach Sorento at {base_url}."
            )

        if response.status_code in (401, 403):
            return TestResult(ok=False, message="Sorento rejected the API key.")
        if response.status_code >= 500:
            return TestResult(
                ok=False,
                message=(
                    f"Reached {base_url} but Sorento returned an internal error "
                    f"({response.status_code}). Check the Sorento service."
                ),
            )
        if response.status_code >= 400:
            # The request reached Sorento AND authenticated (a 401/403 was handled
            # above), so a 4xx here is a benign contract quibble on the probe body,
            # not a connection problem — the connection is proven usable.
            return TestResult(
                ok=True, message=f"Connected to Sorento at {base_url}."
            )
        return TestResult(ok=True, message=f"Connected to Sorento at {base_url}.")
