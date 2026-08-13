"""输出 token 预算与长度耗尽重试的安全回归测试。"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.qa.router import _answer_options as admin_answer_options  # noqa: E402
from app.api.v1.user.router import _answer_options as user_answer_options  # noqa: E402
from app.services.qa.generator import AnswerGenerator, AnswerLengthLimitError  # noqa: E402
from app.services.llm.gateway import llm_gateway  # noqa: E402


def _fake_agent(**overrides) -> SimpleNamespace:
    """构造仅含检索参数字段的轻量 Agent，供 _answer_options 读取。"""
    defaults = dict(
        concise_top_k=4,
        detailed_top_k=8,
        concise_rewrite_count=3,
        detailed_rewrite_count=3,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.mark.parametrize("options", [admin_answer_options, user_answer_options])
def test_response_detail_token_budgets(options):
    """管理端与用户端不能因路由差异使用不同的输出上限与检索预算。"""
    agent = _fake_agent()
    assert options("concise", agent)["max_tokens"] == 4096
    assert options("detailed", agent)["max_tokens"] == 8192
    assert options("concise", agent)["top_k"] == 4
    assert options("detailed", agent)["top_k"] == 8


@pytest.mark.asyncio
async def test_length_without_content_retries_once_at_12000(monkeypatch):
    budgets: list[int] = []

    async def fake_stream(**kwargs):
        budgets.append(kwargs["max_tokens"])
        if len(budgets) == 1:
            raise RuntimeError("模型未返回可展示正文（finish_reason=length）")
        yield "正常正文"

    monkeypatch.setattr(llm_gateway, "chat_stream", fake_stream)
    generator = AnswerGenerator()
    result = [chunk async for chunk in generator._chat_stream_with_length_retry(
        prompt="test", temperature=0.5, max_tokens=4096,
    )]

    assert result == ["正常正文"]
    assert budgets == [4096, 12000]


@pytest.mark.asyncio
async def test_length_at_12000_returns_explicit_limit_error(monkeypatch):
    budgets: list[int] = []

    async def fake_stream(**kwargs):
        budgets.append(kwargs["max_tokens"])
        raise RuntimeError("模型未返回可展示正文（finish_reason=length）")
        yield "unreachable"

    monkeypatch.setattr(llm_gateway, "chat_stream", fake_stream)
    generator = AnswerGenerator()

    with pytest.raises(AnswerLengthLimitError, match="超过当前上限"):
        _ = [chunk async for chunk in generator._chat_stream_with_length_retry(
            prompt="test", temperature=0.5, max_tokens=8192,
        )]
    assert budgets == [8192, 12000]


@pytest.mark.asyncio
async def test_length_after_content_is_not_retried(monkeypatch):
    budgets: list[int] = []

    async def fake_stream(**kwargs):
        budgets.append(kwargs["max_tokens"])
        yield "已经输出"
        raise RuntimeError("模型未返回可展示正文（finish_reason=length）")

    monkeypatch.setattr(llm_gateway, "chat_stream", fake_stream)
    generator = AnswerGenerator()
    received: list[str] = []
    with pytest.raises(RuntimeError, match="finish_reason=length"):
        async for chunk in generator._chat_stream_with_length_retry(
            prompt="test", temperature=0.5, max_tokens=4096,
        ):
            received.append(chunk)
    assert received == ["已经输出"]
    assert budgets == [4096]


@pytest.mark.asyncio
async def test_non_length_error_is_not_retried(monkeypatch):
    budgets: list[int] = []

    async def fake_stream(**kwargs):
        budgets.append(kwargs["max_tokens"])
        raise RuntimeError("Request timed out")
        yield "unreachable"

    monkeypatch.setattr(llm_gateway, "chat_stream", fake_stream)
    generator = AnswerGenerator()
    with pytest.raises(RuntimeError, match="timed out"):
        _ = [chunk async for chunk in generator._chat_stream_with_length_retry(
            prompt="test", temperature=0.5, max_tokens=4096,
        )]
    assert budgets == [4096]
