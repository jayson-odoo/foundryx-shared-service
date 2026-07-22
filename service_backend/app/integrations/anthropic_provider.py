"""Anthropic (Claude) LLM provider — `type='llm'` (AC-BI-02).

Structured output = **forced tool use**: the schema is handed over as a single
tool's `input_schema` and `tool_choice` pins that tool, so the model must emit a
conforming object. That is Anthropic's mechanism and it stops here — callers
only ever see `LLMResult.structured` (AC-BI-01).
"""
from typing import Any, Dict, List, Optional

from app.integrations.base import LLMError, LLMResult, ModelOption
from app.integrations.llm_base import (
    DEFAULT_MAX_TOKENS,
    LLM_LIST_TIMEOUT_SECONDS,
    LLM_TIMEOUT_SECONDS,
    LLMProviderBase,
    _http_json,
    require_key,
    sorted_models,
)

API_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
# The tool the model is forced to call when a schema is requested.
_EMIT_TOOL = "emit_result"


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


class AnthropicProvider(LLMProviderBase):
    provider = "anthropic"
    title = "Anthropic (Claude)"
    description = (
        "Use Claude models for AI features — grilling, drafting and structured "
        "extraction. Bring your own API key from the Anthropic console."
    )
    icon = "sparkles"

    # Curated fallback so the model picker still renders if the live catalog
    # call fails (AC-BI-05). Deliberately short — the live list is the truth.
    static_models = [
        ModelOption(id="claude-sonnet-4-5", label="Claude Sonnet 4.5"),
        ModelOption(id="claude-opus-4-1", label="Claude Opus 4.1"),
        ModelOption(id="claude-haiku-4-5", label="Claude Haiku 4.5"),
    ]

    def models(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> List[ModelOption]:
        payload = _http_json(
            "GET",
            f"{API_BASE}/models?limit=100",
            headers=_headers(require_key(credentials)),
            timeout=LLM_LIST_TIMEOUT_SECONDS,
        )
        options = [
            ModelOption(
                id=str(row.get("id", "")),
                label=str(row.get("display_name") or row.get("id", "")),
                created=_epoch(row.get("created_at")),
            )
            for row in payload.get("data", [])
            if row.get("id")
        ]
        return sorted_models(options)

    def complete(
        self,
        config: Dict[str, Any],
        credentials: Dict[str, Any],
        *,
        model: str,
        system: str,
        messages: List[Dict[str, str]],
        output_schema: Optional[Dict[str, Any]] = None,
        temperature: float = 0,
    ) -> LLMResult:
        body: Dict[str, Any] = {
            "model": model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": temperature,
            "messages": [
                {"role": m["role"], "content": m["content"]} for m in messages
            ],
        }
        if system:
            body["system"] = system
        if output_schema is not None:
            # Forced tool use — Anthropic's structured-output mechanism.
            body["tools"] = [
                {
                    "name": _EMIT_TOOL,
                    "description": "Return the result in the required shape.",
                    "input_schema": output_schema,
                }
            ]
            body["tool_choice"] = {"type": "tool", "name": _EMIT_TOOL}

        payload = _http_json(
            "POST",
            f"{API_BASE}/messages",
            headers=_headers(require_key(credentials)),
            json_body=body,
            timeout=LLM_TIMEOUT_SECONDS,
        )

        usage = payload.get("usage") or {}
        tokens_in = int(usage.get("input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)
        blocks = payload.get("content") or []

        if output_schema is not None:
            for block in blocks:
                if block.get("type") == "tool_use" and block.get("name") == _EMIT_TOOL:
                    structured = block.get("input")
                    if not isinstance(structured, dict):
                        raise LLMError("The model returned a malformed structured result.")
                    return LLMResult(
                        structured=structured,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        model=str(payload.get("model") or model),
                        finish_reason=payload.get("stop_reason"),
                    )
            raise LLMError("The model did not return the requested structured result.")

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return LLMResult(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=str(payload.get("model") or model),
            finish_reason=payload.get("stop_reason"),
        )


def _epoch(value: Any) -> Optional[int]:
    """Anthropic dates models with an ISO-8601 `created_at`."""
    if not value:
        return None
    from datetime import datetime  # noqa: PLC0415

    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None
