"""Google Gemini LLM provider — `type='llm'` (AC-BI-02).

Structured output = `generationConfig.responseSchema` + a JSON response mime
type. Gemini accepts only a SUBSET of JSON Schema (no `additionalProperties`,
no `$schema`, no `oneOf`…), so the adapter down-converts the schema here —
callers pass ordinary JSON Schema and never learn about this (AC-BI-01).

The API key rides as a header (`x-goog-api-key`), never in the query string:
URLs land in logs and proxies, headers don't.
"""
import json
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

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# JSON Schema keys Gemini's responseSchema dialect accepts.
_ALLOWED_SCHEMA_KEYS = {
    "type", "format", "description", "nullable", "enum",
    "items", "properties", "required", "maxItems", "minItems",
}


def _headers(api_key: str) -> Dict[str, str]:
    return {"x-goog-api-key": api_key, "content-type": "application/json"}


def to_gemini_schema(schema: Any) -> Any:
    """Down-convert JSON Schema to Gemini's accepted subset.

    Unsupported keywords are DROPPED rather than rejected: the schema is a
    shaping hint, and our own `form_engine` validation remains the authority
    (D22-A). Dropping keeps a perfectly reasonable caller schema working
    instead of failing the whole call over an `additionalProperties: false`.
    """
    if isinstance(schema, list):
        return [to_gemini_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: Dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _ALLOWED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: to_gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = to_gemini_schema(value)
        else:
            out[key] = value
    return out


class GeminiProvider(LLMProviderBase):
    provider = "gemini"
    title = "Google Gemini"
    description = (
        "Use Gemini models for AI features — grilling, drafting and structured "
        "extraction. Bring your own API key from Google AI Studio."
    )
    icon = "gem"

    static_models = [
        ModelOption(id="gemini-2.5-pro", label="Gemini 2.5 Pro"),
        ModelOption(id="gemini-2.5-flash", label="Gemini 2.5 Flash"),
        ModelOption(id="gemini-2.0-flash", label="Gemini 2.0 Flash"),
    ]

    def models(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> List[ModelOption]:
        payload = _http_json(
            "GET",
            f"{API_BASE}/models?pageSize=200",
            headers=_headers(require_key(credentials)),
            timeout=LLM_LIST_TIMEOUT_SECONDS,
        )
        options: List[ModelOption] = []
        for row in payload.get("models", []):
            name = str(row.get("name", ""))
            # Only chat-capable models — the picker never offers a model that
            # would fail at run time (foolproof-UI).
            if "generateContent" not in (row.get("supportedGenerationMethods") or []):
                continue
            model_id = name.split("/", 1)[1] if "/" in name else name
            if not model_id:
                continue
            options.append(
                ModelOption(id=model_id, label=str(row.get("displayName") or model_id))
            )
        # Gemini's catalog carries no timestamps — keep the API's own ordering.
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
        generation: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": DEFAULT_MAX_TOKENS,
        }
        if output_schema is not None:
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = to_gemini_schema(output_schema)

        body: Dict[str, Any] = {
            "contents": [
                {
                    # Gemini names the assistant role "model".
                    "role": "model" if m["role"] == "assistant" else "user",
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
            ],
            "generationConfig": generation,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        payload = _http_json(
            "POST",
            f"{API_BASE}/models/{model}:generateContent",
            headers=_headers(require_key(credentials)),
            json_body=body,
            timeout=LLM_TIMEOUT_SECONDS,
        )

        usage = payload.get("usageMetadata") or {}
        tokens_in = int(usage.get("promptTokenCount") or 0)
        tokens_out = int(usage.get("candidatesTokenCount") or 0)
        candidates = payload.get("candidates") or []
        if not candidates:
            raise LLMError("The model returned no completion.")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        content = "".join(p.get("text", "") for p in parts)
        finish_reason = candidates[0].get("finishReason")

        if output_schema is not None:
            try:
                structured = json.loads(content)
            except ValueError as exc:
                raise LLMError("The model returned a malformed structured result.") from exc
            if not isinstance(structured, dict):
                raise LLMError("The model returned a malformed structured result.")
            return LLMResult(
                structured=structured,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
                finish_reason=finish_reason,
            )

        return LLMResult(
            text=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            finish_reason=finish_reason,
        )
