import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.agent import Agent  # noqa: F401 - 注册外键目标表
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.services.knowledge.embedder import BGE_QUERY_INSTRUCTION, _prepare_query
from app.services.knowledge.indexer import IndexManager, IndexResult
from app.services.knowledge.splitter import text_splitter
from app.services.knowledge.text_normalizer import normalize_text
from app.services.qa.retriever import HybridRetriever, KeywordRetriever
from app.services.qa.generator import AnswerGenerator
from app.services.llm.gateway import LLMGateway


def test_nfkc_normalizes_pdf_compatibility_characters():
    assert normalize_text("量⼦计算\r\n") == "量子计算\n"


def test_bge_instruction_is_query_only_and_model_specific():
    query = "如何开发 RAG"
    assert _prepare_query("BAAI/bge-large-zh-v1.5", query) == BGE_QUERY_INSTRUCTION + query
    assert _prepare_query("text-embedding-3-small", query) == query


@pytest.mark.asyncio
async def test_streaming_uses_fallback_only_before_any_output(monkeypatch):
    """流式主模型连接失败时可降级，已输出时不会拼接另一模型的重复回答。"""
    gateway = LLMGateway()
    primary = type("Client", (), {"config": type("Config", (), {"model_name": "primary"})()})()
    fallback = type("Client", (), {"config": type("Config", (), {"model_name": "fallback"})()})()
    gateway._primary_client = primary
    gateway._fallback_clients = [fallback]

    async def fake_stream(client, *_args):
        if client is primary:
            raise RuntimeError("primary unavailable")
        yield "fallback answer"

    monkeypatch.setattr(gateway, "_call_model_stream", fake_stream)
    parts = [part async for part in gateway.chat_stream("test")]
    assert parts == ["fallback answer"]


def test_collection_id_is_canonical_and_rejects_nested_prefix():
    assert IndexManager.normalize_knowledge_base_id(5) == "5"
    assert IndexManager.normalize_knowledge_base_id("kb_5") == "5"
    with pytest.raises(ValueError):
        IndexManager.normalize_knowledge_base_id("kb_kb_5")


def test_parent_ids_are_unique_across_documents():
    parents_a, _ = text_splitter.split_parent_child("A" * 900, metadata={"document_id": 10})
    parents_b, _ = text_splitter.split_parent_child("B" * 900, metadata={"document_id": 11})
    assert parents_a[0].metadata["parent_id"] == "doc_10_parent_0"
    assert parents_b[0].metadata["parent_id"] == "doc_11_parent_0"


@pytest.mark.asyncio
async def test_parent_lookup_uses_document_id_and_keyword_recovers_unicode(monkeypatch, tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        kb = KnowledgeBase(name="kb")
        db.add(kb)
        await db.flush()
        wrong_doc = Document(
            knowledge_base_id=kb.id, filename="raft.txt", file_type="txt",
            file_path="/tmp/raft.txt", status="completed",
        )
        right_doc = Document(
            knowledge_base_id=kb.id, filename="quantum.txt", file_type="txt",
            file_path="/tmp/quantum.txt", status="completed",
        )
        db.add_all([wrong_doc, right_doc])
        await db.flush()
        db.add_all([
            DocumentChunk(
                document_id=wrong_doc.id, knowledge_base_id=kb.id,
                parent_id="parent_0", content="Raft 一致性哈希",
                metadata_json=json.dumps({"filename": "raft.txt"}),
            ),
            DocumentChunk(
                document_id=right_doc.id, knowledge_base_id=kb.id,
                parent_id="parent_0", content="量⼦计算的基本原理",
                metadata_json=json.dumps({"filename": "quantum.txt"}),
            ),
        ])
        await db.commit()
        kb_id = kb.id
        right_doc_id = right_doc.id

    import app.core.database as database_module
    monkeypatch.setattr(database_module, "async_session_factory", sessions)

    retriever = HybridRetriever()
    fetched = await retriever._fetch_parent_chunks(
        [(right_doc_id, "parent_0")], [str(kb_id)]
    )
    assert fetched[(right_doc_id, "parent_0")]["text"] == "量⼦计算的基本原理"

    keyword_results = await retriever._search_all_parent_chunks(
        [str(kb_id)], "量子计算", top_k=5
    )
    assert keyword_results
    assert keyword_results[0].metadata["document_id"] == right_doc_id
    assert "量子计算" in keyword_results[0].text

    await engine.dispose()


def test_rrf_fuses_parent_results_without_mixing_raw_scores():
    retriever = HybridRetriever()
    vector = IndexResult(
        "v", "quantum", {"document_id": 1, "parent_id": "p1"}, score=-0.2
    )
    keyword = IndexResult(
        "k", "quantum", {"document_id": 1, "parent_id": "p1"}, score=99
    )
    merged = retriever._rrf_merge([vector], [keyword])
    assert len(merged) == 1
    assert merged[0].score == 1.0


def test_identity_question_triggers_disambiguated_web_supplement():
    result = IndexResult(
        "tim",
        "7月3日忆Tim有感。接下来想说说李四维和Tim，影视飓风直播中links和Tim一起爬山。",
        {"filename": "7月3日忆Tim有感.md"},
        score=1.0,
    )
    assert AnswerGenerator._needs_web_supplement("Tim是谁", [result])
    assert not AnswerGenerator._needs_web_supplement("Tim有什么特点", [result])
    search_query = AnswerGenerator._build_web_search_query("Tim是谁", [result])
    assert search_query == '"Tim" "影视飓风"'


def test_latin_entity_keyword_does_not_match_longer_words():
    results = KeywordRetriever().search([
        {"chunk_id": "time", "text": "Real-Time timestamp"},
        {"chunk_id": "person", "text": "Tim 是影视飓风创始人"},
    ], "Tim是谁", top_k=5)
    assert [result["chunk_id"] for result in results] == ["person"]


def test_identity_question_boosts_exact_filename_match():
    retriever = HybridRetriever()
    results = [
        IndexResult("tech", "TIM 调度协议", {"filename": "Agent工程师.pdf"}, 1.0),
        IndexResult("person", "Tim 的直播感想", {"filename": "忆Tim有感.md"}, 0.4),
    ]
    retriever._boost_identity_filename_matches(results, "Tim是谁")
    assert results[0].chunk_id == "person"
    assert results[0].score == 1.0
