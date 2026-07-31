"""轻量文档后台处理器：不依赖队列，服务重启后可自动续处理。"""

import asyncio
import json
import time

from loguru import logger
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.services.knowledge.indexer import index_manager
from app.services.knowledge.parser import document_parser
from app.services.knowledge.splitter import text_splitter
from app.services.knowledge.text_normalizer import normalize_text
from app.services.validation.quality_checker import parse_quality_checker

_tasks: set[asyncio.Task] = set()
_active_document_ids: set[int] = set()
_kb_locks: dict[int, asyncio.Lock] = {}


async def _sync_kb_statistics(db, kb: KnowledgeBase) -> None:
    result = await db.execute(
        select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.chunk_count), 0),
            func.coalesce(func.sum(Document.parent_chunk_count), 0),
            func.coalesce(func.sum(Document.file_size), 0),
        ).where(Document.knowledge_base_id == kb.id)
    )
    document_count, chunk_count, parent_chunk_count, total_size_bytes = result.one()
    kb.document_count = document_count
    kb.chunk_count = chunk_count
    kb.parent_chunk_count = parent_chunk_count
    kb.total_size_bytes = total_size_bytes


def schedule_document_processing(document_id: int) -> bool:
    """将文档加入进程内后台队列；同一文档同时只会处理一次。"""
    if document_id in _active_document_ids:
        return False

    _active_document_ids.add(document_id)
    task = asyncio.create_task(process_document(document_id), name=f"document-{document_id}")
    _tasks.add(task)

    def _finished(done_task: asyncio.Task) -> None:
        _tasks.discard(done_task)
        _active_document_ids.discard(document_id)
        try:
            done_task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"文档后台任务异常退出: {document_id}")

    task.add_done_callback(_finished)
    return True


async def resume_unfinished_document_processing() -> int:
    """服务重启后恢复等待中或处理中断的文档。"""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Document.id).where(Document.status.in_(("pending", "processing")))
        )
        document_ids = list(result.scalars())
    for document_id in document_ids:
        schedule_document_processing(document_id)
    if document_ids:
        logger.info(f"已恢复 {len(document_ids)} 个未完成文档任务")
    return len(document_ids)


async def _mark_error(document_id: int, message: str, parse_time_ms: float = 0.0) -> None:
    async with async_session_factory() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return
        kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
        doc.status = "error"
        doc.error_message = message[:1000]
        if parse_time_ms:
            doc.parse_time_ms = parse_time_ms
        if kb:
            await _sync_kb_statistics(db, kb)
        await db.commit()


async def _cleanup_failed_processing(
    document_id: int,
    knowledge_base_id: int,
    message: str,
    parse_time_ms: float = 0.0,
) -> None:
    """清理跨存储的半成品，使失败文档不会留下孤儿向量或父块。"""
    try:
        await index_manager.remove_document_chunks(str(knowledge_base_id), document_id)
    except Exception:
        logger.warning(f"清理失败文档的向量索引失败: {document_id}")

    async with async_session_factory() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return
        await db.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )
        doc.chunk_count = 0
        doc.parent_chunk_count = 0
        doc.status = "error"
        doc.error_message = message[:1000]
        if parse_time_ms:
            doc.parse_time_ms = parse_time_ms
        kb = await db.get(KnowledgeBase, knowledge_base_id)
        if kb:
            await _sync_kb_statistics(db, kb)
        await db.commit()


async def process_document(document_id: int) -> None:
    """解析、切分、入库与向量化。任何失败都会明确标记为 error。"""
    kb_id: int | None = None
    elapsed_ms = 0.0
    try:
        # 短事务 1：只更新任务状态并复制后续处理需要的信息。
        async with async_session_factory() as db:
            doc = await db.get(Document, document_id)
            if doc is None or doc.status == "completed":
                return
            kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
            if kb is None:
                await _mark_error(document_id, "知识库不存在")
                return

            kb_id = kb.id
            doc.status = "processing"
            doc.error_message = None
            await db.commit()

            file_path = doc.file_path
            filename = doc.filename
            file_type = doc.file_type

        # 同一知识库串行修改 Chroma，仍允许问答读取及不同知识库并行处理。
        kb_lock = _kb_locks.setdefault(kb_id, asyncio.Lock())
        async with kb_lock:
            started_at = time.time()
            parse_result = await document_parser.parse(file_path)
            elapsed_ms = (time.time() - started_at) * 1000

            if settings.ENABLE_FORMAT_CHECK:
                quality = parse_quality_checker.check(parse_result)
                if not quality.passed:
                    message = parse_result.error_message or (
                        f"文档质量检查未通过 (评分 {quality.score}/100): "
                        + "; ".join(quality.errors or quality.warnings)
                    )
                    await _cleanup_failed_processing(document_id, kb_id, message, elapsed_ms)
                    return

            if parse_result.status.value == "failed" or not parse_result.text.strip():
                await _cleanup_failed_processing(
                    document_id,
                    kb_id,
                    parse_result.error_message or "解析失败",
                    elapsed_ms,
                )
                return

            normalized_text = normalize_text(parse_result.text)
            parent_chunks, child_chunks = text_splitter.split_parent_child(
                text=normalized_text,
                child_size=200,
                child_overlap=50,
                parent_multiplier=4,
                metadata={
                    "document_id": document_id,
                    "knowledge_base_id": kb_id,
                    "filename": filename,
                    "file_type": file_type,
                },
            )

            # 长耗时向量化之前提交父块；不持有 SQLite 写事务。
            await index_manager.remove_document_chunks(str(kb_id), document_id)
            async with async_session_factory() as db:
                await db.execute(
                    DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
                )
                for index, parent in enumerate(parent_chunks):
                    db.add(DocumentChunk(
                        document_id=document_id,
                        knowledge_base_id=kb_id,
                        parent_id=parent.metadata.get("parent_id", f"doc_{document_id}_parent_{index}"),
                        content=parent.text,
                        content_type=parent.metadata.get("content_type", "text"),
                        code_lang=parent.metadata.get("code_lang"),
                        chunk_index=parent.chunk_index,
                        metadata_json=json.dumps(parent.metadata, ensure_ascii=False),
                    ))
                await db.commit()

            # 云端 Embedding 和 Chroma 写入阶段没有 SQLite 写事务。
            indexed = await index_manager.index_chunks(str(kb_id), child_chunks)
            if indexed != len(child_chunks):
                raise RuntimeError(f"向量索引不完整：已写入 {indexed}/{len(child_chunks)} 个切片")

            # 短事务 3：索引完整后再发布 completed 状态。
            async with async_session_factory() as db:
                doc = await db.get(Document, document_id)
                kb = await db.get(KnowledgeBase, kb_id)
                if doc is None or kb is None:
                    raise RuntimeError("文档或知识库在处理期间被删除")
                doc.chunk_count = len(child_chunks)
                doc.parent_chunk_count = len(parent_chunks)
                doc.parse_time_ms = elapsed_ms
                doc.status = "completed"
                doc.error_message = None
                await _sync_kb_statistics(db, kb)
                await db.commit()
            logger.info(f"文档 {document_id} 后台处理完成: {indexed} 个子块")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(f"文档 {document_id} 后台处理失败: {exc}")
        if kb_id is not None:
            await _cleanup_failed_processing(document_id, kb_id, str(exc), elapsed_ms)
        else:
            await _mark_error(document_id, str(exc), elapsed_ms)
