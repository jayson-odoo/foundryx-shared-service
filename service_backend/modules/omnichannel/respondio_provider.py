"""``respondio`` connection provider (plan 33 S1, D-A6-2, AC-MIG-11/12/13).

Reuses the WHOLE core connections spine for free: Fernet-encrypted write-only
``apiToken``, the standard Integrations wizard/list/test surface, blank-PATCH-
keeps-value + partial-config-merge (both already generic in
``IntegrationService.update`` - no per-provider code needed), and the existing
``uq_connection_tenant_provider`` partial index already gives ONE ACTIVE
``respondio`` connection per tenant (``type="migration"`` is not in
``EXEMPT_FROM_ONE_PER_TYPE`` - a second space migration retires the first,
BL-SS-120 tracks lifting that).
"""
from typing import Any, Dict, List, Optional

from app.integrations.base import TestResult

from .respondio.client import DEFAULT_BASE_URL, DEFAULT_REQUESTS_PER_SECOND, RespondIoClient, RespondIoError

MODULE_PROVIDER_KEY = "respondio"


class RespondIoProvider:
    provider = MODULE_PROVIDER_KEY
    type = "migration"
    title = "respond.io"
    description = (
        "Connect a respond.io workspace (Space) to migrate its contacts, "
        "message history and custom data into this workspace."
    )
    icon = "arrow-left-right"
    test_label = "Test connection"
    test_target = None  # connection check only - no targeted test
    test_needs_context = False

    def fields(self) -> List[Dict[str, Any]]:
        return [
            {
                "key": "spaceLabel",
                "label": "Space label",
                "type": "text",
                "required": True,
                "placeholder": "Acme Support",
            },
            {
                "key": "timezone",
                "label": "Workspace timezone",
                "type": "text",
                "required": True,
                "placeholder": "Asia/Kuala_Lumpur",
            },
            {
                "key": "apiToken",
                "label": "Access token",
                "type": "password",
                "required": True,
                "secret": True,
            },
            {
                "key": "requestsPerSecond",
                "label": "Requests per second",
                "type": "number",
                "required": False,
                "defaultValue": str(DEFAULT_REQUESTS_PER_SECOND),
                "advanced": True,
            },
            {
                "key": "baseUrl",
                "label": "API base URL",
                "type": "text",
                "required": False,
                "defaultValue": DEFAULT_BASE_URL,
                "advanced": True,
            },
        ]

    def test(
        self, config: Dict[str, Any], credentials: Dict[str, Any], target: Optional[str] = None
    ) -> TestResult:
        client = RespondIoClient.from_connection(config, credentials)
        try:
            client.ping()
        except RespondIoError as exc:
            if exc.status_code == 401:
                return TestResult(ok=False, message="respond.io rejected this access token.")
            if exc.status_code == 403:
                return TestResult(
                    ok=False,
                    message=(
                        "This workspace's respond.io plan does not include the "
                        "Developer API (Growth plan or above required)."
                    ),
                )
            return TestResult(
                ok=False, message="Could not verify the respond.io connection right now."
            )
        return TestResult(ok=True, message="respond.io connection verified.")
