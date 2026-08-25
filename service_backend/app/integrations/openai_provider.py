"""OpenAI LLM provider - `type='llm'` (AC-BI-02).

Structured output = the **`json_schema` response format**. Note `strict` is
deliberately NOT set: strict mode requires every property to appear in
`required`, which would forbid the partial extraction the grill explicitly
permits (Bi-D13 - "partial emit is success, invention is not"). Our own
`form_engine` validation is the authority either way (D22-A), so the response
format is a shaping hint, not the gate.
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

API_BASE = "https://api.openai.com/v1"
# The catalog carries embeddings/audio/image/moderation models too - the picker
# must only offer models that will actually work (foolproof-UI).
_NON_CHAT_HINTS = (
    "embedding", "whisper", "tts", "dall-e", "moderation", "audio",
    "image", "realtime", "transcribe", "sora", "codex",
)


def _headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "content-type": "application/json"}


def _is_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    if any(hint in lowered for hint in _NON_CHAT_HINTS):
        return False
    return lowered.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))


class OpenAIProvider(LLMProviderBase):
    provider = "openai"
    title = "OpenAI"
    description = (
        "Use OpenAI models for AI features - grilling, drafting and structured "
        "extraction. Bring your own API key from the OpenAI platform."
    )
    icon = "bot"

    static_models = [
        ModelOption(id="gpt-4.1", label="GPT-4.1"),
        ModelOption(id="gpt-4o", label="GPT-4o"),
        ModelOption(id="gpt-4o-mini", label="GPT-4o mini"),
    ]

    def models(self, config: Dict[str, Any], credentials: Dict[str, Any]) -> List[ModelOption]:
        payload = _http_json(
            "GET",
            f"{API_BASE}/models",
            headers=_headers(require_key(credentials)),
            timeout=LLM_LIST_TIMEOUT_SECONDS,
        )
        options = [
            ModelOption(
                id=str(row["id"]),
                label=str(row["id"]),
                created=int(row["created"]) if row.get("created") else None,
            )
            for row in payload.get("data", [])
            if row.get("id") and _is_chat_model(str(row["id"]))
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
        wire: List[Dict[str, str]] = []
        if system:
            wire.append({"role": "system", "content": system})
        wire.extend({"role": m["role"], "content": m["content"]} for m in messages)

        body: Dict[str, Any] = {
            "model": model,
            "messages": wire,
            "temperature": temperature,
            "max_completion_tokens": DEFAULT_MAX_TOKENS,
        }
        if output_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": output_schema},
            }

        payload = _http_json(
            "POST",
            f"{API_BASE}/chat/completions",
            headers=_headers(require_key(credentials)),
            json_body=body,
            timeout=LLM_TIMEOUT_SECONDS,
        )

        usage = payload.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError("The model returned no completion.")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        finish_reason = choices[0].get("finish_reason")
        resolved_model = str(payload.get("model") or model)

        if output_schema is not None:
            # A truncated response ("length" = hit max_completion_tokens) is
            # never valid structured output - refuse cleanly, never blind-parse a
            # fragment (defense: a runaway model must produce an LLMError).
            if finish_reason == "length":
                raise LLMError(
                    "The model's structured response was cut off at the token "
                    "limit - try again."
                )
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
                model=resolved_model,
                finish_reason=finish_reason,
            )

        return LLMResult(
            text=content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=resolved_model,
            finish_reason=finish_reason,
        )
