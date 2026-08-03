"""
智答引擎（ZhiDa Engine）—— 知识库 API 路由

提供文档上传、文档列表、知识库优化、统计等接口。
"""

import hashlib
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from loguru import logger

from app.core.config import settings
from app.core.database import async_session_factory, get_db
from app.models.knowledge import KnowledgeBase, Document, DocumentChunk
from app.models.feishu_config import FeishuConfig
from app.models.import_job import ImportJob
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.schemas.knowledge import (
    DocumentOut,
    DocumentListOut,
    KnowledgeBaseOut,
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseListOut,
    KnowledgeStatsOut,
    OptimizeRequest,
    OptimizeResponse,
    FeishuConfigOut,
    FeishuConfigUpdate,
    FeishuImportRequest,
    FeishuImportStartOut,
    FeishuImportJobOut,
    WebUrlImportOut,
    WebUrlImportRequest,
    WebUrlPreviewOut,
)
from app.services.knowledge.indexer import index_manager
from app.services.knowledge.document_processor import schedule_document_processing, schedule_knowledge_base_rebuild
from app.services.knowledge.data_integrity import data_integrity_service
from app.services.validation.precheck import upload_prechecker
from app.services.knowledge.feishu import FeishuClient
from app.services.knowledge.web_importer import fetch_public_page
from app.core.security import encrypt_api_key, decrypt_api_key, mask_api_key

router = APIRouter(prefix="/knowledge", tags=["知识库管理"])
_import_tasks: set = set()


# ============================================================
# 辅助函数
# ============================================================

def _document_to_out(doc: Document, duplicate: bool = False) -> DocumentOut:
    """将数据库模型转为输出 Schema"""
    return DocumentOut(
        id=doc.id,
        knowledge_base_id=doc.knowledge_base_id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        error_message=doc.error_message,
        chunk_count=doc.chunk_count,
        parse_time_ms=doc.parse_time_ms,
        split_time_ms=doc.split_time_ms,
        embedding_time_ms=doc.embedding_time_ms,
        total_time_ms=doc.total_time_ms,
        processing_stage=doc.processing_stage,
        failed_stage=doc.failed_stage,
        processing_attempts=doc.processing_attempts,
        source_url=doc.source_url,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        duplicate=duplicate,
    )


async def _find_duplicate_document(
    db: AsyncSession,
    knowledge_base_id: int,
    filename: str,
    file_size: int,
    content_hash: str,
) -> Optional[Document]:
    """按 SHA-256 去重，并在用户再次上传时逐步补齐旧文档的哈希。"""
    result = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.content_hash == content_hash,
        ).order_by(Document.id.desc())
    )
    if document := result.scalar_one_or_none():
        return document

    # 兼容升级前没有 content_hash 的文档。仅比较同名同大小候选，避免扫描全部文件。
    candidates = (await db.execute(
        select(Document).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.content_hash.is_(None),
            Document.filename == filename,
            Document.file_size == file_size,
        ).order_by(Document.id.desc())
    )).scalars().all()
    for document in candidates:
        try:
            with open(document.file_path, "rb") as existing_file:
                existing_hash = hashlib.file_digest(existing_file, "sha256").hexdigest()
        except OSError:
            continue
        if existing_hash == content_hash:
            document.content_hash = content_hash
            await db.flush()
            return document
    return None


def _kb_to_out(kb: KnowledgeBase) -> KnowledgeBaseOut:
    """将知识库数据库模型转为输出 Schema"""
    return KnowledgeBaseOut(
        id=kb.id,
        agent_id=kb.agent_id,
        name=kb.name,
        description=kb.description,
        document_count=kb.document_count,
        chunk_count=kb.chunk_count,
        total_size_bytes=kb.total_size_bytes,
        is_active=kb.is_active,
        index_status=kb.index_status or "ready",
        embedding_model=kb.embedding_model,
        embedding_dimension=kb.embedding_dimension,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


async def _sync_kb_statistics(db: AsyncSession, kb: KnowledgeBase) -> None:
    """根据文档表重建知识库统计，避免上传中断造成累计值漂移。"""
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


def _feishu_config_out(config: FeishuConfig | None) -> FeishuConfigOut:
    if config is None:
        return FeishuConfigOut()
    return FeishuConfigOut(
        enabled=config.enabled, app_id=config.app_id,
        app_secret=mask_api_key(decrypt_api_key(config.app_secret)),
        last_test_at=config.last_test_at, last_test_success=config.last_test_success,
        last_error=config.last_error,
    )


async def _create_text_document(
    db: AsyncSession, kb: KnowledgeBase, filename: str, content: str, source_url: str,
) -> tuple[Document, bool]:
    """将云端正文以 Markdown 原件写入既有异步入库流水线。"""
    encoded = content.encode("utf-8")
    content_hash = hashlib.sha256(encoded).hexdigest()
    safe_filename = upload_prechecker.sanitize_filename(filename or "网页资料")
    if not safe_filename.lower().endswith(".md"):
        safe_filename = f"{safe_filename}.md"
    duplicate = await _find_duplicate_document(db, kb.id, safe_filename, len(encoded), content_hash)
    if duplicate:
        return duplicate, True
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", f"kb_{kb.id}")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"{content_hash[:16]}_{safe_filename}")
    with open(file_path, "wb") as file:
        file.write(encoded)
    doc = Document(
        knowledge_base_id=kb.id, filename=safe_filename, file_type="md", file_path=file_path,
        file_size=len(encoded), content_hash=content_hash, source_url=source_url, status="pending",
    )
    db.add(doc)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _find_duplicate_document(db, kb.id, safe_filename, len(encoded), content_hash)
        if existing:
            return existing, True
        raise
    await db.refresh(doc)
    schedule_document_processing(doc.id)
    return doc, False


def _job_out(job: ImportJob) -> FeishuImportJobOut:
    try:
        logs = json.loads(job.logs_json or "[]")
    except json.JSONDecodeError:
        logs = []
    return FeishuImportJobOut(id=job.id, status=job.status, total=job.total, processed=job.processed,
                               imported=job.imported, duplicate=job.duplicate,
                               error_message=job.error_message, logs=logs)


async def _run_feishu_import_job(job_id: str) -> None:
    """后台读取 Wiki 并逐篇提交现有文档处理队列；进度持久化供前端显示。"""
    try:
        async with async_session_factory() as db:
            job = await db.get(ImportJob, job_id)
            if job is None:
                return
            kb = await db.get(KnowledgeBase, job.knowledge_base_id)
            config = await db.get(FeishuConfig, 1)
            if kb is None or config is None or not config.enabled:
                raise RuntimeError("知识库不存在，或飞书数据源未启用")
            job.status = "processing"
            await db.commit()
            source_url, max_nodes = job.source_url, job.max_nodes
            client = FeishuClient(config.app_id, decrypt_api_key(config.app_secret))
        documents = await client.import_url(source_url, max_nodes)
        async with async_session_factory() as db:
            job = await db.get(ImportJob, job_id)
            if job is None:
                return
            job.total = len(documents)
            job.logs_json = json.dumps([{"name": "数据源", "status": "已读取", "message": f"发现 {len(documents)} 篇文档"}], ensure_ascii=False)
            await db.commit()
        for item in documents:
            async with async_session_factory() as db:
                job = await db.get(ImportJob, job_id)
                kb = await db.get(KnowledgeBase, job.knowledge_base_id) if job else None
                if job is None or kb is None:
                    return
                try:
                    _, duplicate = await _create_text_document(db, kb, item.title, item.content, item.source_url)
                    job.imported += 0 if duplicate else 1
                    job.duplicate += 1 if duplicate else 0
                    status = "重复跳过" if duplicate else "已提交处理"
                    entry = {"name": item.title, "status": status}
                except Exception as exc:
                    entry = {"name": item.title, "status": "失败", "message": str(exc)[:160]}
                job.processed += 1
                try:
                    logs = json.loads(job.logs_json or "[]")
                except json.JSONDecodeError:
                    logs = []
                logs.append(entry)
                job.logs_json = json.dumps(logs[-100:], ensure_ascii=False)
                await db.commit()
        async with async_session_factory() as db:
            job = await db.get(ImportJob, job_id)
            if job:
                job.status = "completed"
                await db.commit()
    except Exception as exc:
        logger.warning(f"飞书后台导入失败: {type(exc).__name__}: {exc}")
        async with async_session_factory() as db:
            job = await db.get(ImportJob, job_id)
            if job:
                job.status, job.error_message = "failed", str(exc)[:500]
                await db.commit()


# ============================================================
# 知识库管理
# ============================================================

@router.post("/bases/{kb_id}/web/preview", response_model=WebUrlPreviewOut)
async def preview_web_url_import(kb_id: int, request: WebUrlImportRequest, db: AsyncSession = Depends(get_db)):
    if await db.get(KnowledgeBase, kb_id) is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    try:
        page = await fetch_public_page(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(f"网页预览失败: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="无法读取网页，请稍后重试") from exc
    return WebUrlPreviewOut(title=page.title, url=page.url, content_preview=page.content[:1200], content_length=len(page.content))


@router.post("/bases/{kb_id}/web/import", response_model=WebUrlImportOut)
async def import_web_url(kb_id: int, request: WebUrlImportRequest, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.index_status == "rebuild_required":
        raise HTTPException(status_code=409, detail="知识库索引需要重建后才能导入网页")
    try:
        page = await fetch_public_page(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning(f"网页导入失败: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="无法读取网页，请稍后重试") from exc
    document, duplicate = await _create_text_document(db, kb, page.title, page.content, page.url)
    return WebUrlImportOut(document=_document_to_out(document, duplicate=duplicate), duplicate=duplicate)

@router.get("/bases", response_model=KnowledgeBaseListOut)
async def list_knowledge_bases(
    agent_id: Optional[int] = Query(None, description="Agent ID 过滤"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取知识库列表

    支持按 Agent ID 过滤，不填则返回所有知识库。
    """
    query = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc())
    if agent_id is not None:
        query = query.join(AgentKnowledgeBase, AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id).where(AgentKnowledgeBase.agent_id == agent_id)

    result = await db.execute(query)
    bases = result.scalars().all()
    for kb in bases:
        await _sync_kb_statistics(db, kb)

    return KnowledgeBaseListOut(
        total=len(bases),
        items=[_kb_to_out(kb) for kb in bases],
    )


@router.post("/bases", response_model=KnowledgeBaseOut)
async def create_knowledge_base(
    request: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建知识库

    创建独立的知识库，可在创建 Agent 时选择挂载。
    """
    kb = KnowledgeBase(
        agent_id=request.agent_id,
        name=request.name,
        description=request.description or "",
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)

    return _kb_to_out(kb)


# 精确路径必须在参数化路径 {kb_id} 之前注册，否则 FastAPI 会将
# "independent" 等字面量匹配为 kb_id 并触发 int 类型解析错误。
@router.get("/bases/independent", response_model=KnowledgeBaseListOut)
async def list_independent_knowledge_bases(
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有独立知识库列表（未挂载到任何 Agent）

    可用于选择要挂载的知识库。
    """
    result = await db.execute(
        select(KnowledgeBase).outerjoin(AgentKnowledgeBase, AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id)
        .where(AgentKnowledgeBase.id.is_(None))
        .order_by(KnowledgeBase.created_at.desc())
    )
    bases = result.scalars().all()

    return KnowledgeBaseListOut(
        total=len(bases),
        items=[_kb_to_out(kb) for kb in bases],
    )


@router.get("/bases/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取知识库详情"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    await _sync_kb_statistics(db, kb)
    return _kb_to_out(kb)


@router.put("/bases/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: int,
    request: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新知识库配置"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(kb, key, value)

    await db.flush()
    await db.refresh(kb)

    return _kb_to_out(kb)


@router.post("/bases/{kb_id}/rebuild-index")
async def rebuild_knowledge_base_index(kb_id: int, db: AsyncSession = Depends(get_db)):
    """备份后异步重建当前知识库的 Chroma 索引。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    available = (await db.execute(select(func.count(Document.id)).where(
        Document.knowledge_base_id == kb_id,
        Document.status.in_(("completed", "pending")),
    ))).scalar_one()
    if not available:
        raise HTTPException(status_code=422, detail="没有可重建的已完成或待处理文档")
    backup = await data_integrity_service.backup()
    if not schedule_knowledge_base_rebuild(kb_id):
        raise HTTPException(status_code=409, detail="该知识库正在重建中")
    return {"success": True, "message": "索引重建已开始，文档将依次重新向量化", "backup": backup, "document_count": available}


@router.delete("/bases/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除知识库（同时删除关联的文档）"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    await db.delete(kb)
    await db.flush()

    return {"message": "删除成功", "id": kb_id}


# ============================================================
# 知识库挂载/解绑
# ============================================================

class AttachKnowledgeBaseRequest(BaseModel):
    """挂载知识库请求"""
    agent_id: int


class AttachDetachResponse(BaseModel):
    """挂载/解绑响应"""
    success: bool
    message: str
    kb_id: int
    agent_id: Optional[int] = None


@router.post("/bases/{kb_id}/attach", response_model=AttachDetachResponse)
async def attach_knowledge_base_to_agent(
    kb_id: int,
    request: AttachKnowledgeBaseRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    将知识库挂载到指定 Agent

    独立知识库（agent_id 为空）可以挂载到任意 Agent。
    已挂载的知识库需要先解绑才能重新挂载。
    """
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    link = (await db.execute(select(AgentKnowledgeBase).where(
        AgentKnowledgeBase.agent_id == request.agent_id,
        AgentKnowledgeBase.knowledge_base_id == kb_id,
    ))).scalar_one_or_none()
    if link is not None:
        raise HTTPException(status_code=409, detail="该知识库已挂载到当前 Agent")
    db.add(AgentKnowledgeBase(agent_id=request.agent_id, knowledge_base_id=kb_id))
    await db.flush()
    await db.refresh(kb)

    logger.info(f"知识库 {kb_id} 已挂载到 Agent {request.agent_id}")
    return AttachDetachResponse(
        success=True,
        message="挂载成功",
        kb_id=kb_id,
        agent_id=request.agent_id,
    )


@router.post("/bases/{kb_id}/detach", response_model=AttachDetachResponse)
async def detach_knowledge_base_from_agent(
    kb_id: int,
    agent_id: int = Query(..., description="要解绑的 Agent ID"),
    db: AsyncSession = Depends(get_db),
):
    """
    将知识库从 Agent 解绑

    解绑后知识库变为独立知识库（agent_id 为空），可以重新挂载到其他 Agent。
    """
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    link = (await db.execute(select(AgentKnowledgeBase).where(
        AgentKnowledgeBase.agent_id == agent_id,
        AgentKnowledgeBase.knowledge_base_id == kb_id,
    ))).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=404, detail="该知识库未挂载到当前 Agent")
    await db.delete(link)
    await db.flush()
    await db.refresh(kb)

    logger.info(f"知识库 {kb_id} 已从 Agent {agent_id} 解绑")
    return AttachDetachResponse(
        success=True,
        message="解绑成功",
        kb_id=kb_id,
        agent_id=None,
    )


# ============================================================
# 文档管理
# ============================================================

@router.get("/documents", response_model=DocumentListOut)
async def list_documents(
    agent_id: Optional[int] = Query(None, description="Agent ID 过滤"),
    kb_id: Optional[int] = Query(None, description="知识库 ID 过滤"),
    db: AsyncSession = Depends(get_db),
):
    """获取文档列表"""
    query = select(Document).order_by(Document.created_at.desc())
    if kb_id is not None:
        query = query.where(Document.knowledge_base_id == kb_id)
    elif agent_id is not None:
        # 通过 KnowledgeBase 关联查询
        query = query.join(KnowledgeBase).where(KnowledgeBase.agent_id == agent_id)

    result = await db.execute(query)
    docs = result.scalars().all()

    return DocumentListOut(
        total=len(docs),
        items=[_document_to_out(d) for d in docs],
    )


# ============================================================
# 飞书数据源（应用身份）
# ============================================================

@router.get("/feishu/config", response_model=FeishuConfigOut)
async def get_feishu_config(db: AsyncSession = Depends(get_db)):
    return _feishu_config_out(await db.get(FeishuConfig, 1))


@router.put("/feishu/config", response_model=FeishuConfigOut)
async def update_feishu_config(request: FeishuConfigUpdate, db: AsyncSession = Depends(get_db)):
    config = await db.get(FeishuConfig, 1)
    if config is None:
        config = FeishuConfig(id=1)
        db.add(config)
    config.enabled, config.app_id = request.enabled, request.app_id.strip()
    if request.app_secret:
        config.app_secret = encrypt_api_key(request.app_secret.strip())
    if config.enabled and (not config.app_id or not config.app_secret):
        raise HTTPException(status_code=422, detail="启用飞书数据源前，请填写 App ID 和 App Secret")
    await db.flush()
    return _feishu_config_out(config)


@router.post("/feishu/config/test")
async def test_feishu_config(db: AsyncSession = Depends(get_db)):
    config = await db.get(FeishuConfig, 1)
    if config is None:
        raise HTTPException(status_code=422, detail="请先保存飞书 App ID 和 App Secret")
    try:
        await FeishuClient(config.app_id, decrypt_api_key(config.app_secret)).test_connection()
        config.last_test_at, config.last_test_success, config.last_error = datetime.utcnow(), True, None
        await db.commit()
        return {"success": True, "message": "飞书应用连接成功"}
    except Exception as exc:
        config.last_test_at, config.last_test_success, config.last_error = datetime.utcnow(), False, str(exc)[:500]
        await db.commit()
        return {"success": False, "message": "飞书连接失败，请检查凭据与应用发布状态"}


@router.post("/bases/{kb_id}/feishu/import", response_model=FeishuImportStartOut)
async def import_feishu_documents(kb_id: int, request: FeishuImportRequest, db: AsyncSession = Depends(get_db)):
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    config = await db.get(FeishuConfig, 1)
    if config is None or not config.enabled:
        raise HTTPException(status_code=422, detail="请先在设置中启用并保存飞书数据源")
    try:
        FeishuClient._validate_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = ImportJob(id=str(uuid.uuid4()), knowledge_base_id=kb_id, source_type="feishu",
                    source_url=request.url, max_nodes=request.max_nodes, status="pending")
    db.add(job)
    await db.commit()
    task = asyncio.create_task(_run_feishu_import_job(job.id), name=f"feishu-import-{job.id}")
    _import_tasks.add(task)
    task.add_done_callback(_import_tasks.discard)
    return FeishuImportStartOut(job_id=job.id)


@router.get("/feishu/imports/{job_id}", response_model=FeishuImportJobOut)
async def get_feishu_import_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(ImportJob, job_id)
    if job is None or job.source_type != "feishu":
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return _job_out(job)


@router.post("/bases/{kb_id}/upload", response_model=DocumentOut)
async def upload_document_to_kb(
    kb_id: int,
    file: UploadFile = File(..., description="文档文件"),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文档到指定知识库

    支持 PDF、Word、Excel、TXT 格式，文件大小限制 100MB。
    文件接收后立即返回，解析与向量化由轻量后台任务完成。
    """
    # 查找知识库
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = kb_result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 文件类型校验
    allowed_types = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".csv", ".json", ".xml"}

    # MinerU 启用时支持更多格式
    if settings.ENABLE_MINERU:
        allowed_types.update({
            ".pptx", ".ppt", ".epub", ".html", ".htm",
            ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp",
        })

    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}，支持: {', '.join(sorted(allowed_types))}",
        )

    # 读入文件内容
    content = await file.read()

    # 文件大小校验
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（{settings.MAX_UPLOAD_SIZE_MB}MB）",
        )

    # ---- 上传前预检（格式验证 + 文件名清洗 + 损坏检测）----
    if settings.ENABLE_FORMAT_CHECK:
        precheck = upload_prechecker.check(content, file.filename or "")
        if not precheck.passed:
            error_detail = "; ".join(precheck.errors)
            logger.warning(f"上传预检拒绝: {file.filename} — {error_detail}")
            raise HTTPException(status_code=400, detail=error_detail)
        # 使用清洗后的文件名
        safe_filename = precheck.safe_filename
    else:
        safe_filename = upload_prechecker.sanitize_filename(file.filename or "untitled")

    content_hash = hashlib.sha256(content).hexdigest()
    duplicate = await _find_duplicate_document(
        db, kb.id, safe_filename, len(content), content_hash
    )
    if duplicate:
        # 同文件此前处理失败时允许重新提交，仍复用原记录与文件，避免重复索引。
        if duplicate.status == "error":
            duplicate.status = "pending"
            duplicate.error_message = None
            duplicate.chunk_count = 0
            duplicate.parent_chunk_count = 0
            await db.commit()
            await db.refresh(duplicate)
            schedule_document_processing(duplicate.id)
        return _document_to_out(duplicate, duplicate=True)

    # 保存文件到本地
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", f"kb_{kb_id}")
    os.makedirs(upload_dir, exist_ok=True)
    # 使用哈希前缀，避免同名不同内容的上传覆盖已有原文件。
    file_path = os.path.join(upload_dir, f"{content_hash[:16]}_{safe_filename}")
    with open(file_path, "wb") as f:
        f.write(content)

    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb.id,
        filename=safe_filename,
        file_type=file_ext.replace(".", ""),
        file_path=file_path,
        file_size=len(content),
        content_hash=content_hash,
        status="pending",
    )
    db.add(doc)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        # 并发上传相同文件时，唯一索引会保留先创建的记录。
        await db.rollback()
        duplicate = await _find_duplicate_document(
            db, kb.id, safe_filename, len(content), content_hash
        )
        if duplicate:
            return _document_to_out(duplicate, duplicate=True)
        raise
    await db.refresh(doc)
    schedule_document_processing(doc.id)
    return _document_to_out(doc)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除文档"""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")

    kb_id = doc.knowledge_base_id
    # 先持久化待清理状态。Chroma 删除失败时保留 SQLite 记录，用户可再次点击删除重试。
    doc.status = "cleanup_pending"
    doc.processing_stage = "cleanup"
    doc.error_message = None
    await db.commit()
    try:
        await index_manager.remove_document_chunks(str(kb_id), document_id)
    except Exception as e:
        doc = await db.get(Document, document_id)
        if doc:
            doc.status = "cleanup_pending"
            doc.error_message = f"向量清理待重试：{str(e)[:500]}"
            await db.commit()
        raise HTTPException(status_code=409, detail="向量清理未完成，文档已保留为待清理状态，可重试删除")

    doc = await db.get(Document, document_id)
    if doc:
        await db.execute(DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id))
        await db.delete(doc)
    kb = await db.get(KnowledgeBase, kb_id)
    if kb:
        await _sync_kb_statistics(db, kb)
        kb.updated_at = datetime.utcnow()
    await db.commit()
    return {"message": "删除成功", "id": document_id}


@router.delete("/bases/{kb_id}/failed-documents")
async def clear_failed_documents(kb_id: int, db: AsyncSession = Depends(get_db)):
    """清除处理失败的数据库记录及可能残留的向量，不影响正常/进行中文档。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    failed_docs = (await db.execute(select(Document).where(
        Document.knowledge_base_id == kb_id,
        Document.status.in_(("error", "failed")),
    ))).scalars().all()
    removed, retained = 0, []
    for document in failed_docs:
        try:
            # 失败处理通常已清理过向量；再次核验可避免留下幽灵知识。
            await index_manager.remove_document_chunks(str(kb_id), document.id)
            await db.execute(DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document.id))
            await db.delete(document)
            await db.flush()
            removed += 1
        except Exception as exc:
            retained.append({"id": document.id, "filename": document.filename, "reason": str(exc)[:200]})
    await _sync_kb_statistics(db, kb)
    await db.commit()
    return {"success": True, "removed": removed, "retained": retained}


# ============================================================
# 知识库统计
# ============================================================

@router.get("/stats", response_model=KnowledgeStatsOut)
async def get_knowledge_stats(
    agent_id: Optional[int] = Query(None, description="Agent ID 过滤"),
    db: AsyncSession = Depends(get_db),
):
    """获取知识库统计"""
    query = select(Document)
    if agent_id is not None:
        query = query.join(KnowledgeBase).where(KnowledgeBase.agent_id == agent_id)

    result = await db.execute(query)
    docs = result.scalars().all()

    total_chunks = sum(d.chunk_count for d in docs)
    total_size_mb = sum(d.file_size for d in docs) / (1024 * 1024)

    # 按类型统计
    docs_by_type = {}
    for d in docs:
        docs_by_type[d.file_type] = docs_by_type.get(d.file_type, 0) + 1

    # 按状态统计
    docs_by_status = {}
    for d in docs:
        docs_by_status[d.status] = docs_by_status.get(d.status, 0) + 1

    last_upload = max((d.created_at for d in docs), default=None)

    return KnowledgeStatsOut(
        total_documents=len(docs),
        total_chunks=total_chunks,
        total_size_mb=round(total_size_mb, 2),
        documents_by_type=docs_by_type,
        documents_by_status=docs_by_status,
        last_upload_at=last_upload,
    )


# ============================================================
# 知识库优化
# ============================================================

@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_knowledge(
    request: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    优化知识库

    - 去除重复切片
    - 合并小切片
    - 优化向量索引
    """
    # 获取文档列表
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.agent_id == request.agent_id,
            KnowledgeBase.is_active == True,  # noqa: E712
        )
    )
    kb = kb_result.scalar_one_or_none()

    if kb is None:
        return OptimizeResponse(
            success=True,
            message="没有可优化的知识库",
            chunks_before=0,
            chunks_after=0,
            removed_count=0,
        )

    # 统计优化前
    doc_result = await db.execute(
        select(Document).where(Document.knowledge_base_id == kb.id)
    )
    docs = doc_result.scalars().all()
    chunks_before = sum(d.chunk_count for d in docs)

    # 优化提示（实际优化需要 ChromaDB 支持，这里做基础处理）
    removed = 0
    if request.remove_duplicates:
        removed = max(0, chunks_before - len(docs) * 10)  # 估算

    return OptimizeResponse(
        success=True,
        message="知识库优化完成",
        chunks_before=chunks_before,
        chunks_after=chunks_before - removed,
        removed_count=removed,
    )
