"""
智答引擎（ZhiDa Engine）—— 管理后台 API 路由

提供仪表盘统计、模块开关、缓存管理等接口。
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import get_db
from app.core.resource_manager import resource_manager
from app.models.agent import Agent
from app.models.channel import ChannelConfig
from app.models.knowledge import KnowledgeBase, Document
from app.models.qa import QAHistory
from app.schemas.admin import (
    DashboardStatsOut,
    ModuleSwitchesOut,
    ModuleSwitchesUpdate,
    CacheStatsOut,
    RateLimitConfigOut,
    RateLimitConfigUpdate,
)
from app.services.cache.query_cache import query_cache
from app.services.cache.rate_limiter import rate_limiter

router = APIRouter(prefix="/admin", tags=["管理后台"])


# ============================================================
# 仪表盘统计
# ============================================================

@router.get("/dashboard", response_model=DashboardStatsOut)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
):
    """
    获取仪表盘统计数据

    包含 Agent 总数、运行中 Agent 数、今日消息/回答数、
    成功率、知识库统计、缓存命中率等。
    """
    # Agent 统计
    agent_result = await db.execute(select(Agent))
    agents = agent_result.scalars().all()
    total_agents = len(agents)
    running_agents = sum(1 for a in agents if a.status == "running")

    # 渠道统计
    ch_result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.is_active == True)  # noqa: E712
    )
    channels = ch_result.scalars().all()
    total_channels = len(channels)
    active_channels = sum(1 for c in channels if c.is_listening)

    # 今日问答统计
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    qa_result = await db.execute(
        select(QAHistory).where(QAHistory.created_at >= today_start)
    )
    today_qas = qa_result.scalars().all()
    today_answers = len(today_qas)
    today_messages = today_answers * 2  # 估算
    success_count = sum(1 for qa in today_qas if qa.confidence and qa.confidence > 0.5)
    success_rate = (success_count / today_answers * 100) if today_answers > 0 else 0.0

    # 知识库统计
    doc_result = await db.execute(select(Document))
    docs = doc_result.scalars().all()
    total_documents = len(docs)
    total_chunks = sum(d.chunk_count for d in docs)

    # 缓存统计
    cache_stats = query_cache.stats
    cache_hit_rate = cache_stats.get("hit_rate", 0.0)

    return DashboardStatsOut(
        total_agents=total_agents,
        running_agents=running_agents,
        total_channels=total_channels,
        active_channels=active_channels,
        today_messages=today_messages,
        today_answers=today_answers,
        success_rate=round(success_rate, 1),
        total_knowledge_chunks=total_chunks,
        total_documents=total_documents,
        cache_hit_rate=round(cache_hit_rate, 1),
    )


# ============================================================
# 模块开关
# ============================================================

@router.get("/settings", response_model=ModuleSwitchesOut)
async def get_module_switches():
    """
    获取当前所有模块开关状态

    前端设置页据此渲染 Toggle 控件。
    """
    return ModuleSwitchesOut(
        enable_single_flight=settings.ENABLE_SINGLE_FLIGHT,
        enable_graph_retrieval=settings.ENABLE_GRAPH_RETRIEVAL,
        enable_rerank=settings.ENABLE_RERANK,
        enable_streaming=settings.ENABLE_STREAMING,
        enable_auto_learning=settings.ENABLE_AUTO_LEARNING,
        enable_source_citation=settings.ENABLE_SOURCE_CITATION,
        enable_auto_mention=settings.ENABLE_AUTO_MENTION,
        enable_rate_limit=settings.ENABLE_RATE_LIMIT,
        enable_local_only=settings.ENABLE_LOCAL_ONLY,
    )


@router.put("/settings", response_model=ModuleSwitchesOut)
async def update_module_switches(
    request: ModuleSwitchesUpdate,
):
    """
    更新模块开关

    注意：开关更新仅在当前进程生效，重启后恢复 .env 配置。
    如需持久化，需修改 .env 文件。
    """
    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    # 返回更新后的状态
    return await get_module_switches()


# ============================================================
# 缓存管理
# ============================================================

@router.get("/cache-stats", response_model=CacheStatsOut)
async def get_cache_stats():
    """获取缓存统计"""
    stats = query_cache.stats
    return CacheStatsOut(
        hits=stats.get("hits", 0),
        misses=stats.get("misses", 0),
        total=stats.get("hits", 0) + stats.get("misses", 0),
        hit_rate=stats.get("hit_rate", 0.0),
        memory_entries=stats.get("memory_entries", 0),
        disk_entries=stats.get("disk_entries", 0),
    )


@router.post("/clear-cache")
async def clear_cache():
    """清空所有缓存"""
    await query_cache.clear()
    return {"message": "缓存已清空"}


# ============================================================
# 限流配置
# ============================================================

@router.get("/rate-limit", response_model=RateLimitConfigOut)
async def get_rate_limit_config():
    """获取限流配置"""
    return RateLimitConfigOut(
        token_bucket_rate=settings.RATE_LIMIT_TOKEN_RATE,
        token_bucket_capacity=settings.RATE_LIMIT_TOKEN_CAPACITY,
        window_size_seconds=settings.RATE_LIMIT_WINDOW_SIZE,
        window_max_requests=settings.RATE_LIMIT_WINDOW_MAX,
        question_cooldown_seconds=settings.RATE_LIMIT_COOLDOWN,
        silent_period_enabled=settings.RATE_LIMIT_SILENT_ENABLED,
        private_chat_relaxed=settings.RATE_LIMIT_PRIVATE_RELAXED,
    )


@router.put("/rate-limit", response_model=RateLimitConfigOut)
async def update_rate_limit_config(
    request: RateLimitConfigUpdate,
):
    """更新限流配置"""
    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        attr_name = f"RATE_LIMIT_{key.upper()}"
        if hasattr(settings, attr_name):
            setattr(settings, attr_name, value)

    return await get_rate_limit_config()


# ============================================================
# 资源管理
# ============================================================

@router.get("/resource-profile", response_model=dict)
async def get_resource_profile():
    """
    获取机器资源配置方案

    返回硬件检测结果和推荐的运行参数：
    - 硬件信息（内存、CPU、SSD）
    - 向量化配置（切片大小、批处理、ONNX）
    - 并发配置（最大任务数、请求频率）
    - 缓存配置
    - LLM 超时配置
    """
    return resource_manager.get_recommended_settings()