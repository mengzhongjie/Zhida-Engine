"""安全重建单个知识库的父子块与 Chroma 索引。

流程：确认服务已停止 → 完整备份 → 构建临时 cosine 集合 → 黄金查询验证
→ 短事务切换父块和集合 → 一致性复核 → 清理旧/污染集合。
"""

import argparse
import asyncio
import json
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.embedding.router import init_embedding_config  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import async_session_factory, engine, init_db  # noqa: E402
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase  # noqa: E402
from app.services.knowledge.embedder import embedding_service  # noqa: E402
from app.services.knowledge.indexer import index_manager  # noqa: E402
from app.services.knowledge.parser import document_parser  # noqa: E402
from app.services.knowledge.splitter import TextChunk, text_splitter  # noqa: E402
from app.services.knowledge.text_normalizer import normalize_text  # noqa: E402


GOLDEN_QUERIES = {
    "量子计算": ("量子", "计算"),
    "如何开发RAG": ("rag",),
    "Agent工程师面试": ("agent", "工程师"),
    "Raft 一致性哈希": ("raft",),
    "多Agent协作": ("agent", "协作"),
}


def ensure_service_stopped() -> None:
    with socket.socket() as client:
        client.settimeout(0.5)
        if client.connect_ex((settings.API_HOST, settings.API_PORT)) == 0:
            raise RuntimeError("服务仍在运行。请先停止智答引擎，避免重建期间产生并发写入。")


def backup_data(timestamp: str) -> Path:
    source = Path(settings.DATA_DIR)
    backup_root = source.parent / "ZhidaEngine Backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    target = backup_root / f"before-kb-rebuild-{timestamp}"
    if target.exists():
        raise RuntimeError(f"备份目录已存在: {target}")
    shutil.copytree(source, target)
    return target


async def load_documents(kb_id: int) -> tuple[KnowledgeBase, list[Document]]:
    async with async_session_factory() as db:
        kb = await db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise ValueError(f"知识库不存在: {kb_id}")
        result = await db.execute(
            select(Document).where(
                Document.knowledge_base_id == kb_id,
                Document.status == "completed",
            ).order_by(Document.id)
        )
        return kb, list(result.scalars())


async def parse_and_split(documents: list[Document], kb_id: int):
    parent_rows: list[dict] = []
    child_chunks: list[TextChunk] = []
    child_counts: dict[int, int] = {}
    parent_counts: dict[int, int] = {}

    for doc in documents:
        if not Path(doc.file_path).is_file():
            raise FileNotFoundError(f"原始文件不存在: {doc.file_path}")
        parsed = await document_parser.parse(doc.file_path)
        if parsed.status.value == "failed" or not parsed.text.strip():
            raise RuntimeError(f"重新解析失败: {doc.filename}: {parsed.error_message or '无文本'}")
        parents, children = text_splitter.split_parent_child(
            normalize_text(parsed.text),
            child_size=200,
            child_overlap=50,
            parent_multiplier=4,
            metadata={
                "document_id": doc.id,
                "knowledge_base_id": kb_id,
                "filename": doc.filename,
                "file_type": doc.file_type,
            },
        )
        child_counts[doc.id] = len(children)
        parent_counts[doc.id] = len(parents)
        child_chunks.extend(children)
        for parent in parents:
            parent_rows.append({
                "document_id": doc.id,
                "knowledge_base_id": kb_id,
                "parent_id": parent.metadata["parent_id"],
                "content": parent.text,
                "content_type": parent.metadata.get("content_type", "text"),
                "code_lang": parent.metadata.get("code_lang"),
                "chunk_index": parent.chunk_index,
                "metadata_json": json.dumps(parent.metadata, ensure_ascii=False),
            })
        print(f"已解析 {doc.filename}: {len(parents)} 父块 / {len(children)} 子块")

    return parent_rows, child_chunks, parent_counts, child_counts


async def build_temporary_collection(kb_id: int, timestamp: str, chunks: list[TextChunk]):
    name = f"kb_{kb_id}_rebuild_{timestamp}"
    client = index_manager._client
    existing_names = {collection.name for collection in client.list_collections()}
    if name in existing_names:
        raise RuntimeError(f"临时集合已存在: {name}")
    collection = client.create_collection(
        name=name,
        metadata={
            "kb_id": str(kb_id),
            "rebuild": timestamp,
            "hnsw:space": "cosine",
            "hnsw:M": 16,
            "hnsw:construction_ef": 200,
            "hnsw:search_ef": 64,
        },
    )

    batch_size = 32
    try:
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start:start + batch_size]
            embeddings = await embedding_service.embed_texts([chunk.text for chunk in batch])
            collection.add(
                ids=[
                    f"doc_{chunk.metadata['document_id']}_child_{chunk.chunk_index}"
                    for chunk in batch
                ],
                embeddings=embeddings,
                documents=[chunk.text for chunk in batch],
                metadatas=[{
                    key: value if isinstance(value, (str, int, float, bool)) else str(value)
                    for key, value in chunk.metadata.items()
                } for chunk in batch],
            )
            print(f"向量化进度: {min(start + len(batch), len(chunks))}/{len(chunks)}")
    except Exception:
        client.delete_collection(name=name)
        raise

    if collection.count() != len(chunks):
        raise RuntimeError(f"临时索引数量不一致: {collection.count()} != {len(chunks)}")
    return collection


async def validate_golden_queries(collection) -> None:
    print("黄金查询验证:")
    for query, expected_terms in GOLDEN_QUERIES.items():
        embedding = await embedding_service.embed_query(normalize_text(query))
        result = collection.query(
            query_embeddings=[embedding],
            n_results=min(10, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        documents = result.get("documents", [[]])[0]
        joined = "\n".join(normalize_text(text).lower() for text in documents)
        if not documents or not any(term.lower() in joined for term in expected_terms):
            raise RuntimeError(f"黄金查询未通过: {query}")
        top_meta = result.get("metadatas", [[]])[0][0] or {}
        print(f"  通过 {query} → {top_meta.get('filename', '未知来源')}")


async def switch_index(
    kb_id: int,
    timestamp: str,
    temporary,
    parent_rows: list[dict],
    parent_counts: dict[int, int],
    child_counts: dict[int, int],
) -> str:
    client = index_manager._client
    canonical_name = f"kb_{kb_id}"
    archive_name = f"kb_{kb_id}_old_{timestamp}"
    temporary_name = temporary.name
    old = client.get_collection(canonical_name)
    switched = False
    committed = False

    async with async_session_factory() as db:
        try:
            await db.execute(delete(DocumentChunk).where(DocumentChunk.knowledge_base_id == kb_id))
            db.add_all([DocumentChunk(**row) for row in parent_rows])
            result = await db.execute(
                select(Document).where(
                    Document.knowledge_base_id == kb_id,
                    Document.id.in_(child_counts),
                )
            )
            documents = list(result.scalars())
            for doc in documents:
                doc.chunk_count = child_counts[doc.id]
                doc.parent_chunk_count = parent_counts[doc.id]
            kb = await db.get(KnowledgeBase, kb_id)
            kb.chunk_count = sum(child_counts.values())
            kb.parent_chunk_count = sum(parent_counts.values())
            await db.flush()

            old.modify(name=archive_name)
            try:
                temporary.modify(name=canonical_name)
            except Exception:
                old.modify(name=canonical_name)
                raise
            switched = True
            await db.commit()
            committed = True
        except Exception:
            await db.rollback()
            if switched and not committed:
                client.get_collection(canonical_name).modify(name=temporary_name)
                client.get_collection(archive_name).modify(name=canonical_name)
            raise

    index_manager._collections.pop(str(kb_id), None)
    return archive_name


async def verify_and_cleanup(kb_id: int, archive_name: str, expected_children: int) -> None:
    client = index_manager._client
    current = client.get_collection(f"kb_{kb_id}")
    if current.count() != expected_children:
        raise RuntimeError("切换后 Chroma 数量校验失败；旧索引仍保留，可从备份恢复")
    async with async_session_factory() as db:
        parent_count = await db.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.knowledge_base_id == kb_id)
        )
    print(f"切换后一致性: Chroma={current.count()}, SQLite父块={parent_count}")

    # 完整目录备份已经落盘；成功复核后才删除旧索引和已确认的空污染集合。
    client.delete_collection(archive_name)
    for polluted in ("kb_kb_4", "kb_kb_5"):
        try:
            collection = client.get_collection(polluted)
            if collection.count() == 0:
                client.delete_collection(polluted)
                print(f"已清理空污染集合: {polluted}")
        except Exception:
            pass


async def rebuild(kb_id: int, apply: bool) -> None:
    ensure_service_stopped()
    if not apply:
        # 检查模式兼容尚未执行新版本迁移的旧数据库。
        async with async_session_factory() as db:
            row = (await db.execute(text(
                "SELECT kb.id, kb.name, COUNT(d.id) "
                "FROM knowledge_bases kb LEFT JOIN documents d "
                "ON d.knowledge_base_id=kb.id AND d.status='completed' "
                "WHERE kb.id=:kb_id GROUP BY kb.id, kb.name"
            ), {"kb_id": kb_id})).one_or_none()
        if row is None:
            raise ValueError(f"知识库不存在: {kb_id}")
        print(f"目标知识库: {row[0]} / {row[1]}; 已完成文档: {row[2]}")
        print("仅检查模式完成。加入 --apply 才会备份、向量化并切换索引。")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_data(timestamp)
    print(f"完整备份已创建: {backup_path}")

    # 备份完成后再升级旧库结构，保证任何迁移都可恢复。
    await init_db()
    kb, documents = await load_documents(kb_id)
    print(f"目标知识库: {kb.id} / {kb.name}; 已完成文档: {len(documents)}")
    if not documents:
        raise RuntimeError("没有可重建的 completed 文档")

    async with async_session_factory() as db:
        await init_embedding_config(db)
    print(f"Embedding: {embedding_service.model_name} / {embedding_service.dimension}维")

    parent_rows, children, parent_counts, child_counts = await parse_and_split(documents, kb_id)
    temporary = await build_temporary_collection(kb_id, timestamp, children)
    await validate_golden_queries(temporary)
    archive_name = await switch_index(
        kb_id, timestamp, temporary, parent_rows, parent_counts, child_counts
    )
    await verify_and_cleanup(kb_id, archive_name, len(children))
    print(f"知识库 {kb_id} 重建完成: {len(parent_rows)} 父块 / {len(children)} 子块")


def main() -> None:
    parser = argparse.ArgumentParser(description="安全重建知识库索引")
    parser.add_argument("knowledge_base_id", type=int)
    parser.add_argument("--apply", action="store_true", help="执行备份、重建和切换")
    args = parser.parse_args()
    try:
        asyncio.run(rebuild(args.knowledge_base_id, args.apply))
    finally:
        asyncio.run(engine.dispose())


if __name__ == "__main__":
    main()
