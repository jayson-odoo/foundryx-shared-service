"""Sorento consumer connection provider (plan 14 §4, AC-14-15).

The OUTBOUND counterpart to ``AutoCountProvider``. Where the ``erp`` connection
points *at* AutoCount to read from, this ``consumer`` connection points *at*
Sorento to push to - the direction differs, so the identity must too. It plugs
into the SAME core provider registry as SMTP / S3 / AutoCount, so an operator
configures the Sorento target from the standard `/settings/integrations`
Resource shell with no bespoke UI.

Three fields: the base URL, the contract version the ESB should speak to
this Sorento (``sorentoContractVersion``, a select - ``1`` legacy or ``2``;
new connections default to ``2``, an existing connection with no stored value
keeps behaving as ``1`` until the operator picks one on the edit form - there
is no backfill, see ``sinks_sorento.sorento_sink_from_connection``), and the
integration's own API key. Auth is ``X-API-Key`` (never ``Authorization:
Bearer``, never the legacy ``EXTERNAL_API_KEY`` - its hash is seeded onto the
*n8n* integration, so presenting it would misattribute every write,
AC-14-15). The key is a write-only secret, Fernet-encrypted in
``credentials_json`` and never echoed.

**Uniqueness note (plan 14 §4):** ``type='consumer'`` is NOT carved out of
core's connection unique indexes, and deliberately so. ``uq_connection_tenant_type``
(``type NOT IN ('payment','erp') AND is_active``) therefore keeps ONE active
consumer per tenant, and ``uq_connection_tenant_provider`` (``type != 'erp' AND
is_active``) keeps one active ``sorento`` provider per tenant - which is exactly
v1's "one Sorento target per tenant". No index migration is needed.

``test()`` runs a harmless AUTHENTICATED probe and names the failing step
(AC-13-04 house rule - "connection failed" catch-alls are banned): a 401/403 is
a rejected key, a transport error is an unreachable host, a 2xx is success.
After a successful probe it reads ``GET /api/v1/external/contract`` and
compares MAJOR versions: a connection set to a version newer than the one
Sorento advertises fails the test naming both (a legacy Sorento has no
contract endpoint at all - that is reported, never treated as a failure).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.integrations.base import TestResult

from .sinks_sorento import SINK_CONCURRENCY_KEY, contract_major

SORENTO_PROVIDER_KEY = "sorento"
# Connection category. Distinct from AutoCount's ``erp`` (which points AT
# AutoCount to read) - this points AT Sorento to write.
SORENTO_CONNECTION_TYPE = "consumer"

# A read endpoint that authenticates the caller yet writes nothing - the safe
# probe surface. An unknown ``source_ref`` returns an empty result, so the probe
# never touches real data.
_PROBE_PATH = "/api/v1/external/read/suppliers"
# A ref that cannot exist, so the probe reads back nothing even on success.
_PROBE_REF = "__probe__"
# Sorento's contract self-description (cross-repo contract section 9/10):
# ``{"version": "2.1", ...}`` - a STRING, compared on the MAJOR only. A Sorento
# older than contract 2 has no such route (404), which is information, not a
# failure.
_CONTRACT_PATH = "/api/v1/external/contract"
CONTRACT_VERSION_KEY = "sorentoContractVersion"


class SorentoProvider:
    provider = SORENTO_PROVIDER_KEY
    type = SORENTO_CONNECTION_TYPE
    title = "Sorento"
    description = (
        "Push AutoCount suppliers and customers into a Sorento workspace. The "
        "outbound target for the AutoCount ESB - one Sorento per workspace."
    )
    icon = "upload-cloud"
    test_label = "Test connection"
    # Connection check only - a write probe against a live Sorento is not
    # something a Test button may ever do.
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        """Config schema driving the integrations form. Four fields: the base
        URL (displayable config), the contract version (select, displayable
        config - same shape as the SMTP provider's ``security`` select, which
        the generic integrations form already renders and prefills from the
        stored config on edit), the push concurrency (select,
        feat/sink-concurrency-ui) and the API key (write-only secret)."""
        return [
            {
                "key": "baseUrl",
                "label": "Sorento base URL",
                "type": "text",
                "required": True,
                "placeholder": "https://sorento.customer.com",
            },
            {
                "key": CONTRACT_VERSION_KEY,
                "label": "Contract version",
                "type": "select",
                "required": True,
                "defaultValue": "2",
                "options": [
                    {"value": "1", "label": "1 (legacy)"},
                    {"value": "2", "label": "2"},
                ],
            },
            {
                "key": "apiKey",
                "label": "API key",
                "type": "password",
                "required": True,
                "secret": True,
            },
            {
                "key": SINK_CONCURRENCY_KEY,
                "label": "Push concurrency",
                "type": "select",
                "required": False,
                # NO `defaultValue` - unset means the platform default, not a
                # stored "1". An operator raises this during a backlog drain
                # and sets it back afterwards, no deploy (see
                # `SorentoSink._resolve_concurrency`).
                "options": [
                    {"value": "1", "label": "1 (sequential)"},
                    {"value": "2", "label": "2"},
                    {"value": "3", "label": "3"},
                    {"value": "4", "label": "4"},
                ],
                # What this connection actually runs at right now, read at
                # REQUEST time - the read-mode / edit prefill for an unset
                # connection (`storedOrEffective` on the frontend).
                "effectiveValue": str(settings.autocount_sink_concurrency),
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
        # Absent = 1, exactly as the sink resolves it (an existing connection
        # saved before the field existed keeps its legacy behaviour).
        chosen = str(config.get(CONTRACT_VERSION_KEY) or "1").strip()
        chosen_major = contract_major(chosen)
        if chosen_major is None:
            return TestResult(
                ok=False,
                message="Choose contract version 1 or 2.",
            )

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
            # Unreachable / timeout / DNS - distinct from an auth rejection.
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
        # A 4xx here (401/403 handled above) means the request reached Sorento
        # AND authenticated - a benign quibble on the probe body, not a
        # connection problem. The connection is proven usable; now check the
        # contract the operator picked against the one Sorento advertises.
        return self._check_contract(
            base_url, api_key, chosen=chosen, chosen_major=chosen_major,
            transport=transport,
        )

    def _check_contract(
        self,
        base_url: str,
        api_key: str,
        *,
        chosen: str,
        chosen_major: int,
        transport: Optional[httpx.BaseTransport],
    ) -> TestResult:
        """Compare the connection's contract version with Sorento's own.

        ``GET /api/v1/external/contract`` answers ``{"version": "2.1"}`` on a
        Sorento at contract 2 or later. Only the MAJOR matters: ``2`` against
        an advertised ``2.1`` passes, ``2`` against ``1.x`` (or against no
        endpoint that answers a version) is reported, and only "chosen newer
        than advertised" FAILS the test - that connection would push payloads
        Sorento rejects. A legacy Sorento has no contract route at all, so a
        404 / transport error / unreadable body is named in the message and
        never fails the test on its own.
        """
        connected = f"Connected to Sorento at {base_url}"
        url = f"{base_url.rstrip('/')}{_CONTRACT_PATH}"
        advertised: Optional[str] = None
        detail = "its contract endpoint was unreachable"
        try:
            with httpx.Client(timeout=10.0, transport=transport) as client:
                response = client.get(url, headers={"X-API-Key": api_key})
        except httpx.HTTPError:
            response = None
        if response is not None:
            detail = f"its contract endpoint answered HTTP {response.status_code}"
            if response.status_code < 400:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                version = body.get("version") if isinstance(body, dict) else None
                if contract_major(version) is not None:
                    advertised = str(version)
                else:
                    detail = "its contract endpoint did not report a version"
        if advertised is None:
            return TestResult(
                ok=True,
                message=(
                    f"{connected} (contract version {chosen} selected; {detail}, "
                    f"so the version could not be verified - a Sorento older than "
                    f"contract 2 has no such endpoint)."
                ),
            )
        # ``advertised`` is only set once it parsed (the None branch above
        # returned), so this is an int; clamped to 1 so the message can never
        # offer "version 0".
        advertised_major = max(contract_major(advertised) or 1, 1)
        if chosen_major > advertised_major:
            return TestResult(
                ok=False,
                message=(
                    f"Sorento advertises contract {advertised}; this connection is "
                    f"set to version {chosen}. Choose version {advertised_major} or "
                    f"upgrade Sorento."
                ),
            )
        return TestResult(
            ok=True,
            message=(
                f"{connected} (contract {advertised} advertised, connection set "
                f"to version {chosen})."
            ),
        )

