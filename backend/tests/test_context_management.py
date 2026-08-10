"""Agent 上下文窗口、多路问题重写与融合策略回归测试。"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from types import SimpleNamespace

from app.api.v1.config.router import create_config
from app.api.v1.user.router import _context_policy, _context_usage_ratio, _trim_records_to_budget
from app.models.auth import Conversation
from app.models.qa import QAHistory
from app.schemas.agent import AgentCreate
from app.schemas.llm_config import LLMConfigCreate
from app.services.llm.gateway import ChatResult, LLMGateway, llm_gateway
from app.services.qa.generator import AnswerGenerator
from app.services.qa.retriever import HybridRetriever
from app.services.knowledge.indexer import IndexResult


def test_agent_context_window_defaults_to_64k_and_has_safe_bounds():
    assert AgentCreate(name="test").context_window_k == 64
    with pytest.raises(ValidationError):
        AgentCreate(name="test", context_window_k=16)
    with pytest.raises(ValidationError):
        AgentCreate(name="test", context_window_k=512)


def test_context_policy_uses_fixed_percentage_thresholds():
    assert _context_policy(0.59, 20) == (False, 12)
    assert _context_policy(0.60, 20) == (False, 6)
    assert _context_policy(0.80, 20) == (False, 4)
    assert _context_policy(0.95, 4) == (False, 4)
    assert _context_policy(0.95, 5) == (True, 4)


def test_context_ratio_includes_output_and_retrieval_reserves():
    conversation = Conversation(id="c", owner_type="user", owner_id=1, agent_id=1)
    conversation.context_summary = ""
    conversation.summarized_through_history_id = 0
    ratio = _context_usage_ratio(
        conversation=conversation, records=[], question="你好",
        context_window_k=64,
    )
    assert 0.30 < ratio < 0.33


def test_context_trimming_keeps_latest_complete_round_within_budget():
    conversation = Conversation(id="c", owner_type="user", owner_id=1, agent_id=1)
    conversation.context_summary = "早期摘要"
    records = [
        QAHistory(id=index, question=f"问题{index}", answer="答" * 5000)
        for index in range(1, 8)
    ]
    trimmed = _trim_records_to_budget(
        conversation=conversation, records=records, question="继续",
        context_window_k=32, max_records=6,
    )
    assert trimmed
    assert trimmed[-1].id == 7
    assert [item.id for item in trimmed] == sorted(item.id for item in trimmed)


def test_conversation_formatter_never_drops_rolling_summary():
    generator = AnswerGenerator()
    history = [{"role": "summary", "content": "关键早期事实"}]
    history.extend({"role": "user", "content": f"消息{i}"} for i in range(24))
    formatted = generator._format_conversation_context(history)
    assert "早期对话摘要：关键早期事实" in formatted


@pytest.mark.asyncio
async def test_llm_api_rejects_conflicting_model_roles_before_database_write():
    request = LLMConfigCreate(
        provider_id="custom", model_name="test",
        is_primary=True, is_context_model=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        await create_config(request=request, db=None)
    assert exc_info.value.status_code == 422


def test_llm_config_schema_rejects_removed_agent_scope():
    with pytest.raises(ValidationError):
        LLMConfigCreate(provider_id="custom", model_name="test", agent_id=2)


@pytest.mark.asyncio
async def test_context_gateway_prefers_dedicated_context_client(monkeypatch):
    gateway = LLMGateway()
    primary = SimpleNamespace(config=SimpleNamespace(
        context_rewrite_timeout_seconds=10, context_compaction_timeout_seconds=25,
    ))
    context = SimpleNamespace(config=SimpleNamespace(
        context_rewrite_timeout_seconds=10, context_compaction_timeout_seconds=25,
    ))
    gateway._primary_client = primary  # type: ignore[assignment]
    gateway._context_client = context  # type: ignore[assignment]
    selected = None

    async def fake_call(client, *_args, **_kwargs):
        nonlocal selected
        selected = client
        return ChatResult(text="ok")

    monkeypatch.setattr(gateway, "_call_model", fake_call)
    await gateway.chat_context("rewrite")
    assert selected is context


@pytest.mark.asyncio
async def test_gateway_loads_global_configs_only(monkeypatch):
    """Agent 专属模型记录不得进入实际问答链路。"""
    gateway = LLMGateway()
    global_config = SimpleNamespace(agent_id=None, is_primary=True, is_fallback=False, is_context_model=False)
    agent_config = SimpleNamespace(agent_id=2, is_primary=True, is_fallback=False, is_context_model=False)
    captured = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, query):
            captured.append(str(query))
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [global_config]))

    class FakeSessionFactory:
        def __call__(self):
            return FakeSession()

    monkeypatch.setattr("app.core.database.async_session_factory", FakeSessionFactory())
    configs = await gateway._load_configs()

    assert configs == [global_config]
    assert captured and "llm_configs.agent_id IS NULL" in captured[0]
    assert agent_config not in configs


@pytest.mark.asyncio
async def test_query_rewrite_keeps_original_and_parses_three_variants(monkeypatch):
    generator = AnswerGenerator()

    async def fake_initialize():
        return None

    async def fake_context(*_args, **_kwargs):
        return ChatResult(text='["新生报到时间", "新生报到地点", "新生报到材料"]')

    monkeypatch.setattr(llm_gateway, "initialize", fake_initialize)
    monkeypatch.setattr(llm_gateway, "chat_context", fake_context)
    variants = await generator._query_variants("什么时候报到", [], 1)
    assert variants[0] == ("什么时候报到", 1.3)
    assert [item[0] for item in variants[1:]] == ["新生报到时间", "新生报到地点", "新生报到材料"]


@pytest.mark.asyncio
async def test_multi_query_rrf_deduplicates_by_document_and_parent(monkeypatch):
    retriever = HybridRetriever()
    original_hit = IndexResult("a", "原问题命中", {"document_id": 1, "parent_id": "p"}, 0.8)
    rewritten_same_parent = IndexResult("b", "同一父块", {"document_id": 1, "parent_id": "p"}, 0.9)
    other_document_same_parent = IndexResult("c", "另一文档", {"document_id": 2, "parent_id": "p"}, 0.7)

    async def fake_retrieve(knowledge_base_ids, query, top_k=5):
        del knowledge_base_ids, top_k
        return [original_hit, other_document_same_parent] if query == "原问题" else [rewritten_same_parent]

    monkeypatch.setattr(retriever, "retrieve", fake_retrieve)
    results = await retriever.retrieve_multi_query(["1"], [("原问题", 1.3), ("改写", 1.0)], top_k=5)
    assert len(results) == 2
    assert results[0].metadata["document_id"] == 1


@pytest.mark.asyncio
async def test_multi_query_retrieval_keeps_successful_routes(monkeypatch):
    retriever = HybridRetriever()
    hit = IndexResult("a", "原问题命中", {"document_id": 1, "parent_id": "p"}, 0.8)

    async def fake_retrieve(knowledge_base_ids, query, top_k=5):
        del knowledge_base_ids, top_k
        if query == "失败改写":
            raise RuntimeError("provider failed")
        return [hit]

    monkeypatch.setattr(retriever, "retrieve", fake_retrieve)
    results = await retriever.retrieve_multi_query(
        ["1"], [("原问题", 1.3), ("失败改写", 1.0)], top_k=5,
    )
    assert results == [hit]


@pytest.mark.asyncio
async def test_compaction_uses_context_model_and_returns_summary(monkeypatch):
    generator = AnswerGenerator()

    async def fake_initialize():
        return None

    async def fake_context(*_args, **_kwargs):
        return ChatResult(text="用户将在 9 月 1 日报到；尚未确认宿舍。")

    monkeypatch.setattr(llm_gateway, "initialize", fake_initialize)
    monkeypatch.setattr(llm_gateway, "chat_context", fake_context)
    summary = await generator.compact_conversation(
        "", [{"role": "user", "content": "我9月1日报到"}], 1,
    )
    assert "9 月 1 日" in summary
