"""Opt-in LIVE provider tests (AC-BI-13) - `pytest -m live`.

**Deselected by default** (`pytest.ini` sets `addopts = -m "not live"`), so a
normal run and CI need no key, cost nothing and never touch the network.

Each provider reads its own env var and **skips cleanly when that key is
absent** - so `-m live` stays green on a machine that only has the Gemini key:

    PLATFORM_LLM_API_KEY / GRILL_API_KEY  → gemini   (the guaranteed one)
    ANTHROPIC_API_KEY                     → anthropic
    OPENAI_API_KEY                        → openai

Run:  `python -m pytest -m live -q`

What these assert is narrow on purpose: the adapter ROUND-TRIPS and structured
output PARSES on each provider. Prompt quality is not CI-testable - that is what
the manual live-verification gate (AC-BI-37) is for.
"""
import os

import pytest

from app.integrations import get_provider
from app.integrations.base import LLMError

pytestmark = pytest.mark.live

# Provider → (env vars in priority order, default model).
_LIVE_PROVIDERS = {
    "gemini": (("PLATFORM_LLM_API_KEY", "GRILL_API_KEY"), "gemini-2.5-flash"),
    "anthropic": (("ANTHROPIC_API_KEY",), "claude-sonnet-4-5"),
    "openai": (("OPENAI_API_KEY",), "gpt-4o-mini"),
}


def _key_for(provider_key: str) -> str:
    env_vars, _ = _LIVE_PROVIDERS[provider_key]
    for var in env_vars:
        value = (os.environ.get(var) or "").strip()
        if value:
            return value
    return ""


def _model_for(provider_key: str) -> str:
    if provider_key == "gemini":
        return (os.environ.get("PLATFORM_LLM_MODEL") or "").strip() or _LIVE_PROVIDERS[
            provider_key
        ][1]
    return _LIVE_PROVIDERS[provider_key][1]


@pytest.fixture(params=sorted(_LIVE_PROVIDERS))
def live_provider(request):
    """Yields (provider, credentials, model), skipping providers with no key."""
    provider_key = request.param
    api_key = _key_for(provider_key)
    if not api_key:
        env_names = " / ".join(_LIVE_PROVIDERS[provider_key][0])
        pytest.skip(f"no {env_names} in the environment - skipping {provider_key}")
    provider = get_provider(provider_key)
    assert provider is not None
    return provider, {"apiKey": api_key}, _model_for(provider_key)


def test_live_models_lists_chat_models(live_provider):
    """The list-models probe (which `test()` reuses) works against the real API."""
    provider, credentials, _ = live_provider
    models = provider.models({}, credentials)
    assert models, f"{provider.provider} returned no chat models"
    assert all(m.id for m in models)


def test_live_test_reports_ok(live_provider):
    """AC-BI-04 - `test()` doubles as the model-list probe."""
    provider, credentials, _ = live_provider
    result = provider.test({}, credentials)
    assert result.ok is True, result.message


def test_live_text_completion_round_trips(live_provider):
    """AC-BI-13 - the adapter round-trips prose and reports normalized usage."""
    provider, credentials, model = live_provider
    result = provider.complete(
        {},
        credentials,
        model=model,
        system="You answer with a single word.",
        messages=[{"role": "user", "content": "Reply with the word: pong"}],
        temperature=0,
    )
    assert result.structured is None
    assert result.text and "pong" in result.text.lower()
    # Usage is normalized across vendors - this is what cost tracking reads.
    assert result.tokens_in > 0
    assert result.tokens_out > 0


def test_live_structured_output_parses(live_provider):
    """AC-BI-13 - each provider's OWN structured-output mechanism (Anthropic
    tool-use · OpenAI json_schema · Gemini responseSchema) parses to the same
    normalized `LLMResult.structured`. No caller branches on provider."""
    provider, credentials, model = live_provider
    schema = {
        "type": "object",
        "properties": {
            "problem_statement": {"type": "string", "description": "The problem"},
            "success_metric": {"type": "string", "description": "How success is measured"},
        },
    }
    result = provider.complete(
        {},
        credentials,
        model=model,
        system="Extract the requested fields from the user's message.",
        messages=[
            {
                "role": "user",
                "content": (
                    "Our checkout page takes 12 seconds to load and people abandon "
                    "their carts. We want to get it under 2 seconds."
                ),
            }
        ],
        output_schema=schema,
        temperature=0,
    )
    assert result.text is None
    assert isinstance(result.structured, dict)
    assert result.structured.get("problem_statement"), result.structured


def test_live_retired_model_fails_loudly(live_provider):
    """AC-BI-05 - a model id the provider does not serve must fail LOUDLY,
    never silently substitute a different model."""
    provider, credentials, _ = live_provider
    with pytest.raises(LLMError):
        provider.complete(
            {},
            credentials,
            model="definitely-not-a-real-model-xyz",
            system="",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0,
        )


def test_live_bad_key_is_rejected_cleanly(live_provider):
    """AC-BI-04 - a bad key yields a clean message, never a raw traceback and
    never the key echoed back."""
    provider, _, _ = live_provider
    result = provider.test({}, {"apiKey": "sk-obviously-invalid-key-000"})
    assert result.ok is False
    assert "Traceback" not in result.message
    assert "sk-obviously-invalid-key-000" not in result.message
