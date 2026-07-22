"""Integration framework core (plan 09 §4) — provider registry.

Core registers its own providers (smtp); App Store modules register theirs at
load time via `register_provider`. The registry feeds GET /integrations/providers
(config schemas drive the frontend wizard) and resolves providers at runtime.
"""
from app.integrations.anthropic_provider import AnthropicProvider
from app.integrations.base import (
    CheckoutResult,
    IntegrationProvider,
    LLMError,
    LLMProvider,
    LLMResult,
    ModelOption,
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
from app.integrations.gemini_provider import GeminiProvider
from app.integrations.openai_provider import OpenAIProvider
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
# LLM providers (Phase B-i slice 1, AC-BI-02). A tenant may hold several ACTIVE
# llm connections at once — `type='llm'` is carved out of uq_connection_tenant_type
# (Bi-D21) — so different agents can run different providers.
register_provider(AnthropicProvider())
register_provider(OpenAIProvider())
register_provider(GeminiProvider())

__all__ = [
    "IntegrationProvider",
    "PaymentProvider",
    "LLMProvider",
    "LLMResult",
    "LLMError",
    "ModelOption",
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
    "AnthropicProvider",
    "OpenAIProvider",
    "GeminiProvider",
]
