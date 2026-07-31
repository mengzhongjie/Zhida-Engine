from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.miniapp.router import _decode_sources, _validate_gateway_signature
from app.core.config import settings
from app.services.qa.prompt import PromptTemplate


def test_local_dev_openid_is_accepted_only_when_debug(monkeypatch):
    request = SimpleNamespace(headers={"X-Miniapp-Dev-Openid": "local-user"})
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "MINIPROGRAM_DEV_OPENID", "local-user")

    assert _validate_gateway_signature(request) == "local-user"


def test_local_dev_header_is_rejected_outside_debug(monkeypatch):
    request = SimpleNamespace(headers={"X-Miniapp-Dev-Openid": "local-user"})
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "MINIPROGRAM_DEV_OPENID", "local-user")
    monkeypatch.setattr(settings, "MINIPROGRAM_GATEWAY_SECRET", "")

    with pytest.raises(HTTPException) as exc_info:
        _validate_gateway_signature(request)
    assert exc_info.value.status_code == 503


def test_session_sources_support_json_and_legacy_literal():
    expected = [{"text": "片段", "metadata": {"filename": "手册.pdf"}}]

    assert _decode_sources('[{"text":"片段","metadata":{"filename":"手册.pdf"}}]') == expected
    assert _decode_sources("[{'text': '片段', 'metadata': {'filename': '手册.pdf'}}]") == expected
    assert _decode_sources("不是有效来源") == []


def test_prompt_includes_recent_conversation_for_follow_up_questions():
    prompt = PromptTemplate().build_qa_prompt(
        question="那保修期呢？",
        context="产品 A 的保修期为一年。",
        conversation_context="用户：产品 A 支持退货吗？\n助手：支持七天退货。",
    )

    assert "## 最近对话" in prompt
    assert "产品 A 支持退货吗" in prompt
    assert "那保修期呢" in prompt
