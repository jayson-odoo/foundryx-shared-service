"""AutoCount integration provider (AC-13-01 / AC-13-04).

Registers into the CORE provider registry (``app/integrations``) as an ``erp``
connection, so AutoCount is configured through the same `/settings/integrations`
Resource shell as SMTP/S3 - no bespoke connection UI.

Two shapes deviate from the other providers, both forced by the vendor API:

* **No AppSecret.** Verified live: auth is a single ``POST /api/Server/Login``
  with an ``AppId`` header and ``{UserID, Password}``. The Postman collection's
  two-step ``Auth/Login`` → ``Server/Login`` flow does not exist.
* **No company field.** The server resolves the company from the ``AppId``
  header and returns ``DatabaseName``/``CompanyName`` on login - so the company
  is DISCOVERED and stored read-only, never entered by the operator (D16,
  foolproof-UI: never ask for something we can determine, and never let an
  operator type a value that will be silently overridden).

``test()`` names the failing STEP (AC-13-04). "Connection failed" catch-alls are
banned - the operator has to know whether to fix the URL, the AppId, or the
credentials.
"""
from typing import Any, Dict, List, Optional

from app.integrations.base import TestResult

from .client import (
    AutoCountAppError,
    AutoCountAuthError,
    AutoCountClient,
    AutoCountError,
    AutoCountRelayError,
    AutoCountTransportError,
)

PROVIDER_KEY = "autocount"
CONNECTION_TYPE = "erp"


def client_from_connection(
    config: Dict[str, Any],
    credentials: Dict[str, Any],
    *,
    transport: Optional[Any] = None,
) -> AutoCountClient:
    """Build a client from a connection's stored config + DECRYPTED credentials.

    Callers pass credentials already decrypted via ``app/secrets.py``
    (``decrypt_secret``, with ``InvalidToken`` caught as a clean reject) - this
    module never handles ciphertext or a module-local Fernet key.
    """
    return AutoCountClient(
        base_url=str(config.get("baseUrl", "")).strip(),
        app_id=str(credentials.get("appId") or config.get("appId") or "").strip(),
        user_id=str(config.get("userId", "")).strip(),
        password=str(credentials.get("password", "")),
        # Explicit per connection, never silently downgraded (plan §11).
        verify_tls=bool(config.get("verifyTls", True)),
        transport=transport,
    )


class AutoCountProvider:
    provider = PROVIDER_KEY
    type = CONNECTION_TYPE
    title = "AutoCount"
    description = (
        "Sync products, stock, suppliers, customers and documents with an on-premise "
        "AutoCount company. One connection per AutoCount company."
    )
    icon = "refresh-cw"
    test_label = "Test connection"
    # Connection check only - there is no meaningful targeted test for a read
    # integration (and a write probe against a customer's live ledger is not
    # something a Test button may ever do).
    test_target = None

    def fields(self) -> List[Dict[str, Any]]:
        """Config schema driving the integrations form.

        Deliberately FOUR fields. No AppSecret (does not exist) and no company
        picker (discovered from the login response) - offering either would be
        asking the operator for something we cannot use.
        """
        return [
            {
                "key": "baseUrl",
                "label": "AutoCount API base URL",
                "type": "text",
                "required": True,
                "placeholder": "https://autocount.customer.com",
            },
            {
                "key": "appId",
                "label": "AppId",
                "type": "password",
                "required": True,
                "secret": True,
            },
            {
                "key": "userId",
                "label": "User ID",
                "type": "text",
                "required": True,
                "placeholder": "ADMIN",
            },
            {
                "key": "password",
                "label": "Password",
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
    ) -> TestResult:
        """Verify the connection by signing in ONCE, and report which step failed.

        Success echoes the DISCOVERED company so the operator can confirm the
        AppId selected the company they intended - the AppId is opaque, so this
        readback is the only way to catch "right credentials, wrong company".
        """
        base_url = str(config.get("baseUrl", "")).strip()
        if not base_url:
            return TestResult(ok=False, message="Enter the AutoCount API base URL.")
        if not base_url.lower().startswith(("http://", "https://")):
            return TestResult(
                ok=False,
                message="The base URL must start with http:// or https://.",
            )

        client = client_from_connection(config, credentials)
        try:
            session = client.login()
        except AutoCountTransportError as exc:
            # Unreachable / timeout - distinct from an auth rejection.
            return TestResult(ok=False, message=exc.message)
        except AutoCountAuthError as exc:
            return TestResult(
                ok=False,
                message=(
                    f"AutoCount rejected the sign-in: {exc.message} Check the User ID "
                    f"and Password."
                ),
            )
        except AutoCountRelayError as exc:
            # A bad AppId surfaces here - the relay faults rather than replying
            # cleanly. The AppId is the actionable thing, so name it. The raw
            # .NET stack trace stays in exc.detail (log only), never shown.
            return TestResult(
                ok=False,
                message=(
                    f"Signed in to {base_url} but AutoCount returned an internal error. "
                    f"This usually means the AppId is not recognised. ({exc.message})"
                ),
            )
        except AutoCountAppError as exc:
            return TestResult(ok=False, message=exc.message)
        except AutoCountError as exc:  # defensive - never leak a raw traceback
            return TestResult(ok=False, message=exc.message)
        finally:
            client.close()

        company = session.company_name or session.database_name
        if not company:
            return TestResult(
                ok=True,
                message=(
                    "Signed in successfully, but AutoCount did not report a company "
                    "name. Confirm the AppId maps to the intended company database."
                ),
            )
        return TestResult(
            ok=True,
            message=f"Connected to {company} ({session.database_name}).",
        )
