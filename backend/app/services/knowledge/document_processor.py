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
_document_tasks: dict[int, asyncio.Task] = {}
_kb_locks: dict[int, asyncio.Lock] = {}
_active_rebuild_kb_ids: set[int] = set()


async def _sync_kb_statistics(db, kb: KnowledgeBase) -> None:
    result = await db.execute(
        select(
            func.count(Document.id),
            func.coalesce(func.sum(Document.chunk_count), 0),
            func.coalesce(func.sum(Document.parent_chunk_count), 0),
            func.coalesce(func.sum(Document.file_size), 0),
            func.coalesce(func.sum(Document.character_count), 0),
        ).where(Document.knowledge_base_id == kb.id)
    )
    document_count, chunk_count, parent_chunk_count, total_size_bytes, total_characters = result.one()
    kb.document_count = document_count
    kb.chunk_count = chunk_count
    kb.parent_chunk_count = parent_chunk_count
    kb.total_size_bytes = total_size_bytes
    kb.total_characters = total_characters


def schedule_document_processing(document_id: int) -> bool:
    """将文档加入进程内后台队列；同一文档同时只会处理一次。"""
    if document_id in _active_document_ids:
        return False

    _active_document_ids.add(document_id)
    task = asyncio.create_task(process_document(document_id), name=f"document-{document_id}")
    _tasks.add(task)
    _document_tasks[document_id] = task

    def _finished(done_task: asyncio.Task) -> None:
        _tasks.discard(done_task)
        _active_document_ids.discard(document_id)
        _document_tasks.pop(document_id, None)
        try:
            done_task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"文档后台任务异常退出: {document_id}")

    task.add_done_callback(_finished)
    return True


async def cancel_document_processing(document_id: int) -> bool:
    """取消当前进程内的文档任务，并等待协程停止，供 API 安全清理残留索引。"""
    task = _document_tasks.get(document_id)
    if task is None or task.done():
        return False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return True


def schedule_knowledge_base_rebuild(knowledge_base_id: int) -> bool:
    """异步重建一个知识库的索引，避免 HTTP 请求长期占用连接。"""
    if knowledge_base_id in _active_rebuild_kb_ids:
        return False
    _active_rebuild_kb_ids.add(knowledge_base_id)
    task = asyncio.create_task(_rebuild_knowledge_base(knowledge_base_id), name=f"kb-rebuild-{knowledge_base_id}")
    _tasks.add(task)
    def _finished(done_task: asyncio.Task) -> None:
        _tasks.discard(done_task)
        _active_rebuild_kb_ids.discard(knowledge_base_id)
        try:
            done_task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"知识库重建任务异常退出: {knowledge_base_id}")
    task.add_done_callback(_finished)
    return True


async def _rebuild_knowledge_base(knowledge_base_id: int) -> None:
    """清除旧索引后，让既有文档复用标准处理流水线重新入库。"""
    kb_lock = _kb_locks.setdefault(knowledge_base_id, asyncio.Lock())
    async with kb_lock:
        async with async_session_factory() as db:
            kb = await db.get(KnowledgeBase, knowledge_base_id)
            if kb is None:
                raise ValueError("知识库不存在")
            documents = (await db.execute(select(Document).where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.status.in_(("completed", "pending", "source_removed_retained")),
            ))).scalars().all()
            if not documents:
                raise RuntimeError("没有可重建的已完成或待处理文档")
            kb.index_status = "rebuilding"
            await db.commit()
        # 旧集合只有在成功请求重建后才删除；随后首个文档会按当前 cosine 参数创建集合。
        await index_manager.clear_knowledge_base(str(knowledge_base_id))
        async with async_session_factory() as db:
            kb = await db.get(KnowledgeBase, knowledge_base_id)
            docs = (await db.execute(select(Document).where(
                Document.knowledge_base_id == knowledge_base_id,
                Document.status.in_(("completed", "pending", "source_removed_retained")),
            ))).scalars().all()
            await db.execute(DocumentChunk.__table__.delete().where(DocumentChunk.knowledge_base_id == knowledge_base_id))
            for doc in docs:
                doc.status, doc.error_message = "pending", None
                doc.chunk_count, doc.parent_chunk_count = 0, 0
                doc.processing_stage, doc.failed_stage = "queued", None
            if kb:
                kb.chunk_count, kb.parent_chunk_count, kb.index_status = 0, 0, "rebuilding"
            await db.commit()
            document_ids = [doc.id for doc in docs]
    for document_id in document_ids:
        schedule_document_processing(document_id)
    logger.info(f"知识库 {knowledge_base_id} 已提交重建：{len(document_ids)} 篇文档")


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


async def _mark_error(document_id: int, message: str, stage: str = "unknown", timings: dict | None = None) -> None:
    async with async_session_factory() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return
        kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
        doc.status = "error"
        doc.error_message = message[:1000]
        doc.processing_stage = stage
        doc.failed_stage = stage
        for field, value in (timings or {}).items():
            setattr(doc, field, value)
        if kb:
            await _sync_kb_statistics(db, kb)
        await db.commit()


async def _cleanup_failed_processing(
    document_id: int,
    knowledge_base_id: int,
    message: str,
    stage: str = "unknown",
    timings: dict | None = None,
) -> None:
    """清理跨存储的半成品，使失败文档不会留下孤儿向量或父块。"""
    try:
        await index_manager.remove_document_chunks(str(knowledge_base_id), document_id)
    except Exception as exc:
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
        doc.processing_stage = stage
        doc.failed_stage = stage
        for field, value in (timings or {}).items():
            setattr(doc, field, value)
        kb = await db.get(KnowledgeBase, knowledge_base_id)
        if kb:
            await _sync_kb_statistics(db, kb)
        await db.commit()


def _timeout_seconds(file_size: int) -> int:
    size_mb = max(1, (file_size + 1024 * 1024 - 1) // (1024 * 1024))
    return min(settings.DOCUMENT_PROCESS_TIMEOUT_MAX_SECONDS,
               settings.DOCUMENT_PROCESS_TIMEOUT_BASE_SECONDS + size_mb * settings.DOCUMENT_PROCESS_TIMEOUT_PER_MB_SECONDS)


async def _set_stage(document_id: int, stage: str) -> None:
    async with async_session_factory() as db:
        doc = await db.get(Document, document_id)
        if doc:
            doc.processing_stage = stage
            await db.commit()


async def _process_once(document_id: int) -> None:
    """一次完整处理尝试。阶段和耗时持久化，避免长时间占用 SQLite 写事务。"""
    timings = {"parse_time_ms": 0.0, "split_time_ms": 0.0, "embedding_time_ms": 0.0, "total_time_ms": 0.0}
    started = time.monotonic()
    kb_id: int | None = None
    stage = "preparing"
    try:
        async with async_session_factory() as db:
            doc = await db.get(Document, document_id)
            if doc is None or doc.status in ("completed", "cleanup_pending"):
                return
            kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
            if kb is None:
                raise RuntimeError("知识库不存在")
            kb_id, file_path, filename, file_type = kb.id, doc.file_path, doc.filename, doc.file_type
            fingerprint = index_manager.current_fingerprint()
            existing = {key: getattr(kb, key) for key in fingerprint}
            if kb.chunk_count and any(existing[key] != value for key, value in fingerprint.items()):
                kb.index_status = "rebuild_required"
                await db.commit()
                raise RuntimeError("索引配置已变化，请先重建知识库索引后再上传文档")
            if not kb.chunk_count:
                for key, value in fingerprint.items():
                    setattr(kb, key, value)
                kb.index_status = "ready"
            doc.status, doc.error_message, doc.failed_stage, doc.processing_stage = "processing", None, None, stage
            doc.processing_attempts = (doc.processing_attempts or 0) + 1
            await db.commit()

        kb_lock = _kb_locks.setdefault(kb_id, asyncio.Lock())
        async with kb_lock:
            stage = "parsing"; await _set_stage(document_id, stage)
            phase_start = time.monotonic()
            parse_result = await document_parser.parse(file_path)
            timings["parse_time_ms"] = (time.monotonic() - phase_start) * 1000
            if settings.ENABLE_FORMAT_CHECK and not parse_quality_checker.check(parse_result).passed:
                raise RuntimeError(parse_result.error_message or "文档质量检查未通过")
            if parse_result.status.value == "failed" or not parse_result.text.strip():
                raise RuntimeError(parse_result.error_message or "解析失败")

            stage = "splitting"; await _set_stage(document_id, stage)
            phase_start = time.monotonic()
            parent_chunks, child_chunks = text_splitter.split_parent_child(normalize_text(parse_result.text), 200, 50, 4, {
                "document_id": document_id, "knowledge_base_id": kb_id, "filename": filename, "file_type": file_type,
            })
            timings["split_time_ms"] = (time.monotonic() - phase_start) * 1000

            stage = "indexing"; await _set_stage(document_id, stage)
            phase_start = time.monotonic()
            await index_manager.remove_document_chunks(str(kb_id), document_id)
            async with async_session_factory() as db:
                await db.execute(DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id))
                for index, parent in enumerate(parent_chunks):
                    db.add(DocumentChunk(document_id=document_id, knowledge_base_id=kb_id,
                        parent_id=parent.metadata.get("parent_id", f"doc_{document_id}_parent_{index}"), content=parent.text,
                        content_type=parent.metadata.get("content_type", "text"), code_lang=parent.metadata.get("code_lang"),
                        chunk_index=parent.chunk_index, metadata_json=json.dumps(parent.metadata, ensure_ascii=False)))
                await db.commit()
            indexed = await index_manager.index_chunks(str(kb_id), child_chunks)
            timings["embedding_time_ms"] = (time.monotonic() - phase_start) * 1000
            if indexed != len(child_chunks):
                raise RuntimeError(f"向量索引不完整：已写入 {indexed}/{len(child_chunks)} 个切片")

            timings["total_time_ms"] = (time.monotonic() - started) * 1000
            async with async_session_factory() as db:
                doc, kb = await db.get(Document, document_id), await db.get(KnowledgeBase, kb_id)
                if doc is None or kb is None: raise RuntimeError("文档或知识库在处理期间被删除")
                doc.chunk_count, doc.parent_chunk_count = len(child_chunks), len(parent_chunks)
                doc.character_count = len(parse_result.text)
                for key, value in timings.items(): setattr(doc, key, value)
                doc.status, doc.processing_stage, doc.failed_stage, doc.error_message = "completed", "completed", None, None
                await _sync_kb_statistics(db, kb); await db.commit()
    except Exception as exc:
        timings["total_time_ms"] = (time.monotonic() - started) * 1000
        logger.exception(f"文档 {document_id} 在 {stage} 阶段失败: {exc}")
        # Document.error_message 会被资料处理记录 API 返回；仅保存可操作的
        # 用户提示，原始异常（URL、文件路径、厂商响应）只留在服务端日志。
        public_error = "文档处理失败，请检查文件内容后重试"
        if kb_id is not None:
            await _cleanup_failed_processing(document_id, kb_id, public_error, stage, timings)
        else:
            await _mark_error(document_id, public_error, stage, timings)
        raise


async def process_document(document_id: int) -> None:
    """动态超时、有限重试的进程内任务；无需外部队列或心跳。"""
    for attempt in range(settings.DOCUMENT_PROCESS_MAX_ATTEMPTS):
        async with async_session_factory() as db:
            doc = await db.get(Document, document_id)
            if doc is None or doc.status in ("completed", "cleanup_pending"): return
            timeout = _timeout_seconds(doc.file_size)
        try:
            await asyncio.wait_for(_process_once(document_id), timeout=timeout)
            return
        except asyncio.CancelledError: raise
        except Exception as exc:
            logger.exception(f"文档 {document_id} 第 {attempt + 1} 次处理失败: {exc}")
            if isinstance(exc, asyncio.TimeoutError):
                async with async_session_factory() as db:
                    timed_out = await db.get(Document, document_id)
                    if timed_out:
                        await _cleanup_failed_processing(
                            document_id, timed_out.knowledge_base_id,
                            f"处理超时（超过 {timeout} 秒）", timed_out.processing_stage or "processing",
                            {"total_time_ms": timeout * 1000.0},
                        )
            if attempt + 1 >= settings.DOCUMENT_PROCESS_MAX_ATTEMPTS: return
            async with async_session_factory() as db:
                doc = await db.get(Document, document_id)
                if doc: doc.status, doc.error_message = "pending", f"第 {attempt + 1} 次处理失败，正在重试"; await db.commit()
            await asyncio.sleep(settings.DOCUMENT_PROCESS_RETRY_BASE_SECONDS * (2 ** attempt))
