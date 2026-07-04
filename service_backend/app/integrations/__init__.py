"""Integration framework core (plan 09 §4) — provider registry.

Core registers its own providers (smtp); App Store modules register theirs at
load time via `register_provider`. The registry feeds GET /integrations/providers
(config schemas drive the frontend wizard) and resolves providers at runtime.
"""
from app.integrations.base import (
    CheckoutResult,
    IntegrationProvider,
    PaymentError,
    PaymentProvider,
    RefundResult,
    TestResult,
    WebhookEvent,
    all_providers,
    get_provider,
    register_provider,
)
from app.integrations.billplz_provider import BillplzProvider
from app.integrations.s3_provider import R2Provider, S3Provider
from app.integrations.smtp_provider import SmtpProvider
from app.integrations.stripe_provider import StripeProvider

# Core providers (module providers register themselves at module load).
register_provider(SmtpProvider())
# Storage pair (plan sprint-2/06 D2) — two cards, one S3-compatible adapter.
register_provider(S3Provider())
register_provider(R2Provider())
# Payment gateways (plan sprint-4/07 Cluster F slice 3, AC-07-26).
register_provider(StripeProvider())
register_provider(BillplzProvider())

__all__ = [
    "IntegrationProvider",
    "PaymentProvider",
    "TestResult",
    "CheckoutResult",
    "WebhookEvent",
    "RefundResult",
    "PaymentError",
    "register_provider",
    "get_provider",
    "all_providers",
    "SmtpProvider",
    "S3Provider",
    "R2Provider",
    "StripeProvider",
    "BillplzProvider",
]
