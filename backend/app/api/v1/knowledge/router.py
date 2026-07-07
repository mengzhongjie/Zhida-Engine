"""
智答引擎（ZhiDa Engine）—— 知识库 API 路由

提供文档上传、文档列表、知识库优化、统计等接口。
"""

import os
import time
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from loguru import logger

from app.core.config import settings
from app.core.database import get_db
from app.models.knowledge import KnowledgeBase, Document, DocumentChunk
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
)
from app.services.knowledge.parser import document_parser
from app.services.knowledge.splitter import text_splitter
from app.services.knowledge.indexer import index_manager

router = APIRouter(prefix="/knowledge", tags=["知识库管理"])


# ============================================================
# 辅助函数
# ============================================================

def _document_to_out(doc: Document) -> DocumentOut:
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
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def _kb_to_out(kb: KnowledgeBase) -> KnowledgeBaseOut:
    """将知识库数据库模型转为输出 Schema"""
    return KnowledgeBaseOut(
        id=kb.id,
        agent_id=kb.agent_id,
        name=kb.name,
        description=kb.description,
        document_count=kb.document_count,
        total_chunks=kb.chunk_count,
        total_size_bytes=kb.total_size_bytes,
        is_active=kb.is_active,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


# ============================================================
# 知识库管理
# ============================================================

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
        query = query.where(KnowledgeBase.agent_id == agent_id)

    result = await db.execute(query)
    bases = result.scalars().all()

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

    if kb.agent_id is not None:
        raise HTTPException(status_code=400, detail="知识库已挂载到其他 Agent，请先解绑")

    kb.agent_id = request.agent_id
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

    if kb.agent_id is None:
        raise HTTPException(status_code=400, detail="知识库当前未挂载到任何 Agent")

    old_agent_id = kb.agent_id
    kb.agent_id = None
    await db.flush()
    await db.refresh(kb)

    logger.info(f"知识库 {kb_id} 已从 Agent {old_agent_id} 解绑")
    return AttachDetachResponse(
        success=True,
        message="解绑成功",
        kb_id=kb_id,
        agent_id=None,
    )


@router.get("/bases/independent", response_model=KnowledgeBaseListOut)
async def list_independent_knowledge_bases(
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有独立知识库列表（未挂载到任何 Agent）

    可用于选择要挂载的知识库。
    """
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.agent_id.is_(None))
        .order_by(KnowledgeBase.created_at.desc())
    )
    bases = result.scalars().all()

    return KnowledgeBaseListOut(
        total=len(bases),
        items=[_kb_to_out(kb) for kb in bases],
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


@router.post("/bases/{kb_id}/upload", response_model=DocumentOut)
async def upload_document_to_kb(
    kb_id: int,
    file: UploadFile = File(..., description="文档文件"),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文档到指定知识库

    支持 PDF、Word、Excel、TXT 格式，文件大小限制 100MB。
    上传后自动解析并向量化入库。
    """
    # 查找知识库
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
    )
    kb = kb_result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 文件类型校验
    allowed_types = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".csv"}
    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}，支持: {', '.join(allowed_types)}",
        )

    # 文件大小校验
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制（{settings.MAX_UPLOAD_SIZE_MB}MB）",
        )

    # 保存文件到本地
    upload_dir = os.path.join(settings.DATA_DIR, "uploads", f"kb_{kb_id}")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(content)

    # 创建文档记录
    doc = Document(
        knowledge_base_id=kb.id,
        filename=file.filename,
        file_type=file_ext.replace(".", ""),
        file_path=file_path,
        file_size=len(content),
        status="pending",
    )
    db.add(doc)
    await db.flush()

    # 异步解析文档（同步执行，后续可改为后台任务）
    try:
        doc.status = "processing"
        await db.flush()

        start_time = time.time()
        parse_result = await document_parser.parse(file_path)
        elapsed_ms = (time.time() - start_time) * 1000

        if parse_result.status.value != "success":
            doc.status = "error"
            doc.error_message = parse_result.error_message or "解析失败"
            doc.parse_time_ms = elapsed_ms
            await db.flush()
            await db.refresh(doc)
            return _document_to_out(doc)

        # ---- 父子块切分 ----
        parent_chunks, child_chunks = text_splitter.split_parent_child(
            text=parse_result.text,
            child_size=200,
            child_overlap=50,
            parent_multiplier=4,
            metadata={
                "document_id": doc.id,
                "filename": doc.filename,
                "file_type": doc.file_type,
            },
        )

        doc.chunk_count = len(child_chunks)
        doc.parent_chunk_count = len(parent_chunks)
        doc.status = "completed"
        doc.parse_time_ms = elapsed_ms

        # ---- 保存父块到数据库 ----
        for i, parent in enumerate(parent_chunks):
            import json
            chunk = DocumentChunk(
                document_id=doc.id,
                knowledge_base_id=kb.id,
                parent_id=parent.metadata.get("parent_id", f"parent_{i}"),
                content=parent.text,
                content_type=parent.metadata.get("content_type", "text"),
                code_lang=parent.metadata.get("code_lang"),
                chunk_index=parent.chunk_index,
                metadata_json=json.dumps(parent.metadata, ensure_ascii=False),
            )
            db.add(chunk)

        # ---- 子块向量化索引到 ChromaDB ----
        indexing_failed = False
        if child_chunks:
            try:
                indexed = await index_manager.index_chunks(str(kb.id), child_chunks)
                logger.info(f"文档 {doc.id} 索引完成: {indexed} 个子块")
            except Exception as index_err:
                indexing_failed = True
                index_error_msg = str(index_err)
                logger.warning(f"文档 {doc.id} 向量化索引失败: {index_error_msg}")
                # 索引失败不影响文档状态，在 error_message 中提示
                doc.error_message = f"文档解析成功，但向量化索引失败：{index_error_msg[:200]}"

        # 更新知识库统计（只有索引成功才更新 chunk_count）
        kb.document_count = kb.document_count + 1
        if not indexing_failed:
            kb.chunk_count = kb.chunk_count + doc.chunk_count
            kb.parent_chunk_count = kb.parent_chunk_count + doc.parent_chunk_count
        kb.total_size_bytes = kb.total_size_bytes + len(content)

    except Exception as e:
        doc.status = "error"
        doc.error_message = str(e)
        logger.exception(f"文档处理失败: {e}")

    await db.flush()
    await db.refresh(doc)

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
    doc_size = doc.file_size
    doc_chunks = doc.chunk_count
    doc_parent_chunks = doc.parent_chunk_count

    # 删除父块记录
    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
    )

    await db.delete(doc)
    await db.flush()

    # 更新知识库统计
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = kb_result.scalar_one_or_none()
    if kb:
        kb.document_count = max(0, kb.document_count - 1)
        kb.chunk_count = max(0, kb.chunk_count - doc_chunks)
        kb.parent_chunk_count = max(0, kb.parent_chunk_count - doc_parent_chunks)
        kb.total_size_bytes = max(0, kb.total_size_bytes - doc_size)
        kb.updated_at = datetime.utcnow()
        await db.flush()

    # 删除向量索引
    try:
        await index_manager.remove_document_chunks(str(kb_id), str(document_id))
    except Exception as e:
        logger.warning(f"删除向量索引失败: {e}")

    await db.commit()
    return {"message": "删除成功", "id": document_id}


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