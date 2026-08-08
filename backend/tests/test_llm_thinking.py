from types import SimpleNamespace

from app.services.llm.gateway import LLMGateway


def test_deepseek_thinking_disabled_uses_official_openai_compatible_shape():
    client = SimpleNamespace(config=SimpleNamespace(
        model_name="deepseek-v4-flash",
        extra_config='{"thinking":{"type":"disabled"}}',
    ))

    assert LLMGateway._model_extra_body(client) == {
        "thinking": {"type": "disabled"},
    }


def test_unrelated_extra_config_is_not_forwarded_to_model():
    client = SimpleNamespace(config=SimpleNamespace(
        model_name="deepseek-v4-flash",
        extra_config='{"reasoning_effort":"low"}',
    ))

    assert LLMGateway._model_extra_body(client) is None
