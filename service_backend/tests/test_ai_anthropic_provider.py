"""Anthropic provider request shape: forced tool_choice + temperature for older models, auto
tool and no temperature for the models that refuse the former (HTTP 400). `_http_json` is mocked."""
import pytest

from app.integrations import anthropic_provider as ap
from app.integrations.base import LLMError

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
CREDS = {"apiKey": "sk-test"}


def _run(monkeypatch, model, payload=None, **kw):
    seen = {}

    def fake(method, url, **kwargs):
        seen["body"] = kwargs["json_body"]
        return payload or {
            "content": [{"type": "tool_use", "name": ap._EMIT_TOOL, "input": {"a": "x"}}],
            "usage": {"input_tokens": 3, "output_tokens": 2}, "model": model, "stop_reason": "tool_use",
        }

    monkeypatch.setattr(ap, "_http_json", fake)
    result = ap.AnthropicProvider().complete({}, CREDS, model=model, system="sys", messages=[{"role": "user", "content": "hi"}],
                                             output_schema=SCHEMA, temperature=0.3, **kw)
    return seen["body"], result


@pytest.mark.parametrize("model", ["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5", ""])
def test_other_models_keep_forced_tool_choice_and_temperature(monkeypatch, model):
    body, result = _run(monkeypatch, model)
    assert body["tool_choice"] == {"type": "tool", "name": ap._EMIT_TOOL}
    assert body["temperature"] == 0.3 and body["system"] == "sys"
    assert "strict" not in body["tools"][0]
    assert result.structured == {"a": "x"}


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-fable-5-2"])
def test_new_models_use_auto_tool_choice_plain_tool_and_no_temperature(monkeypatch, model):
    body, result = _run(monkeypatch, model)
    assert body["tool_choice"] == {"type": "auto"}
    assert "temperature" not in body
    assert "strict" not in body["tools"][0] and body["tools"][0]["name"] == ap._EMIT_TOOL
    assert body["system"].startswith("sys") and ap._EMIT_TOOL in body["system"]
    assert result.structured == {"a": "x"}


def test_new_model_answering_in_text_is_an_llm_error(monkeypatch):
    payload = {"content": [{"type": "text", "text": "hello"}], "usage": {}, "stop_reason": "end_turn"}
    with pytest.raises(LLMError):
        _run(monkeypatch, "claude-sonnet-5-5", payload=payload)
