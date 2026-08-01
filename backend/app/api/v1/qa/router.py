"""
智答引擎（ZhiDa Engine）—— 问答 API 路由

提供问答测试、问答历史、用户反馈等接口。
"""

import json
import time
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import get_db
from app.models.qa import QAHistory, QAPair
from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase
from app.schemas.qa import (
    QAAskRequest,
    QAAnswerOut,
    QASource,
    QAHistoryOut,
    QAHistoryListOut,
    QAFeedbackRequest,
)
from app.services.cache.query_cache import query_cache
from app.services.cache.idempotency import single_flight
from app.services.qa.generator import answer_generator

router = APIRouter(prefix="/qa", tags=["问答"])


# ============================================================
# 辅助函数
# ============================================================

def _qa_to_out(qa: QAHistory) -> QAHistoryOut:
    """将数据库模型转为输出 Schema"""
    return QAHistoryOut(
        id=qa.id,
        agent_id=qa.agent_id,
        question=qa.question,
        answer=qa.answer,
        sources=qa.sources,
        confidence=qa.confidence or 0.0,
        response_time_ms=qa.response_time_ms or 0.0,
        model_used=qa.model_used or "",
        from_cache=qa.from_cache or False,
        chat_id=qa.chat_id,
        chat_type=qa.chat_type,
        user_id=qa.user_id,
        feedback=qa.feedback,
        created_at=qa.created_at,
    )


# ============================================================
# 问答接口
# ============================================================

@router.post("/ask", response_model=QAAnswerOut)
async def ask_question(
    request: QAAskRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    提问接口 —— 完整的 RAG 问答流程

    流程：
    1. 检查缓存（三层缓存：内存→diskcache→LLM）
    2. 混合检索（向量+关键词）
    3. 重排序
    4. LLM 生成回答
    5. 记录问答历史
    """
    start_time = time.time()

    # Agent 和知识库均按请求显式解析，避免使用全局默认知识库。
    agent = await db.get(Agent, request.agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent 不存在或未启用")
    kb_result = await db.execute(
        select(KnowledgeBase.id).where(KnowledgeBase.agent_id == request.agent_id, KnowledgeBase.is_active == True)  # noqa: E712
    )
    knowledge_base_ids = [str(kb_id) for kb_id in kb_result.scalars()]
    # 允许无知识库问答（RAG 降级策略：reply_mode=auto/hybrid 时 LLM 自行回答）

    answer = await answer_generator.generate(
        knowledge_base_ids=knowledge_base_ids,
        question=request.question,
        user_id=request.user_id,
        agent_id=request.agent_id,
        reply_mode=agent.reply_mode,
    )
    sources = [
        QASource(
            document_name=item.get("metadata", {}).get("filename", "未知"),
            chunk_text=item.get("text", ""),
            score=item.get("score", 0.0),
            source_type=item.get("metadata", {}).get("source_type", "document"),
        )
        for item in answer.sources
    ]

    elapsed_ms = (time.time() - start_time) * 1000

    # 4. 缓存结果
    # 记录问答历史
    try:
        qa_record = QAHistory(
            agent_id=request.agent_id,
            question=request.question,
            answer=answer.answer,
            sources=json.dumps([source.model_dump() for source in sources], ensure_ascii=False),
            total_time_ms=elapsed_ms,
            is_cache_hit=answer.is_cache_hit,
            channel="web",
            chat_id=request.chat_id,
            user_id=request.user_id,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
            is_degraded=answer.degraded,
            web_search_count=answer.web_search_count,
        )
        db.add(qa_record)
        await db.flush()
    except Exception:
        pass  # 记录失败不影响回答返回

    return QAAnswerOut(
        question=request.question,
        answer=answer.answer,
        sources=sources,
        confidence=0.8,
        response_time_ms=elapsed_ms,
        model_used=answer.model_used,
        from_cache=answer.is_cache_hit,
    )


# ============================================================
# 问答历史
# ============================================================

@router.get("/history", response_model=QAHistoryListOut)
async def list_history(
    agent_id: Optional[int] = Query(None, description="Agent ID 过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
):
    """获取问答历史列表"""
    query = select(QAHistory).order_by(QAHistory.created_at.desc())
    if agent_id is not None:
        query = query.where(QAHistory.agent_id == agent_id)

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    qas = result.scalars().all()

    return QAHistoryListOut(
        total=total,
        items=[_qa_to_out(qa) for qa in qas],
    )


@router.delete("/history/{qa_id}")
async def delete_history(
    qa_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除单条问答历史"""
    result = await db.execute(select(QAHistory).where(QAHistory.id == qa_id))
    qa = result.scalar_one_or_none()
    if qa is None:
        raise HTTPException(status_code=404, detail="问答记录不存在")

    await db.delete(qa)
    await db.flush()

    return {"message": "删除成功", "id": qa_id}


# ============================================================
# 用户反馈
# ============================================================

@router.post("/feedback")
async def submit_feedback(
    request: QAFeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    提交用户反馈

    反馈用于优化检索精度和回答质量。
    - useful: 回答有用，提高相关文档权重
    - useless: 回答无用，降低相关文档权重
    """
    result = await db.execute(select(QAHistory).where(QAHistory.id == request.qa_id))
    qa = result.scalar_one_or_none()
    if qa is None:
        raise HTTPException(status_code=404, detail="问答记录不存在")

    qa.feedback = request.feedback
    await db.flush()

    # 反馈为 useless 时，记录供后续优化
    if request.feedback == "useless":
        # TODO: 将问答对加入待优化队列，调整检索权重
        pass

    return {"message": "反馈已记录", "id": request.qa_id, "feedback": request.feedback}
