"""
智答引擎（ZhiDa Engine）—— 管理后台 API 路由

提供仪表盘统计、模块开关、缓存管理等接口。
"""

from datetime import datetime, date, timedelta, time as dt_time
import platform
import sys
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from loguru import logger

from app.core.config import settings
from app.core.database import get_db
from app.core.resource_manager import resource_manager
from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase, Document
from app.models.qa import QAHistory
from app.models.llm_config import LLMConfig
from app.models.web_search_config import WebSearchConfig
from app.schemas.admin import (
    DashboardStatsOut,
    ModuleSwitchesOut,
    ModuleSwitchesUpdate,
    CacheStatsOut,
    RateLimitConfigOut,
    RateLimitConfigUpdate,
    LLMUsageStatsOut,
    MemoryItemOut,
    MemorySearchIn,
    MemoryAddIn,
    MemoryUpdateIn,
    MemoryStatsOut,
    WebSearchConfigOut,
    WebSearchConfigUpdate,
    WebSearchTestRequest,
    WebSearchTestResponse,
)
from app.services.cache.query_cache import query_cache
from app.services.cache.rate_limiter import rate_limiter
from app.services.memory.memory_service import memory_service
from app.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from app.services.knowledge.data_integrity import data_integrity_service

router = APIRouter(prefix="/admin", tags=["管理后台"])


@router.get("/reliability")
async def get_reliability_report():
    """只读核验 SQLite 与 Chroma，不会自动删除或重建数据。"""
    return await data_integrity_service.report()


@router.post("/reliability/backup")
async def create_reliability_backup():
    name = await data_integrity_service.backup()
    return {"success": True, "backup": name}


@router.post("/reliability/cleanup-pending")
async def retry_pending_cleanup():
    removed = await data_integrity_service.cleanup_pending()
    return {"success": True, "removed": removed}


@router.get("/system-info")
async def get_system_info():
    """供本地管理台展示真实运行环境，不暴露任何密钥。"""
    profile = resource_manager.detect_hardware()
    return {
        "app_name": settings.APP_NAME, "app_version": settings.APP_VERSION,
        "python_version": sys.version.split()[0], "platform": platform.platform(),
        "data_dir": str(settings.DATA_DIR), "api_address": f"{settings.API_HOST}:{settings.API_PORT}",
        "cpu_cores": profile.cpu_cores, "memory_gb": profile.total_memory_gb,
        "storage_type": "SSD" if profile.is_ssd else "HDD", "resource_profile": profile.profile_name,
    }


@router.get("/component-health")
async def get_component_health(db: AsyncSession = Depends(get_db)):
    """快速、无副作用的组件可用性检查；不触发模型调用。"""
    checks: list[dict] = []
    try:
        await db.execute(text("SELECT 1"))
        checks.append({"key": "sqlite", "name": "SQLite 数据库", "available": True, "message": "读写连接正常"})
    except Exception as exc:
        checks.append({"key": "sqlite", "name": "SQLite 数据库", "available": False, "message": str(exc)[:100]})
    try:
        from app.services.knowledge.indexer import index_manager
        index_manager._client.heartbeat()
        checks.append({"key": "chroma", "name": "Chroma 向量库", "available": True, "message": "嵌入式索引正常"})
    except Exception as exc:
        checks.append({"key": "chroma", "name": "Chroma 向量库", "available": False, "message": str(exc)[:100]})
    try:
        from app.services.knowledge.embedder import embedding_service
        ready = await embedding_service.is_ready()
        checks.append({"key": "embedding", "name": "向量化服务", "available": ready, "message": embedding_service.model_name})
    except Exception as exc:
        checks.append({"key": "embedding", "name": "向量化服务", "available": False, "message": str(exc)[:100]})
    try:
        from app.models.vision_config import VisionConfig
        vision = (await db.execute(select(VisionConfig).where(
            VisionConfig.enabled == True,  # noqa: E712
            (VisionConfig.is_primary == True) | (VisionConfig.is_fallback == True),  # noqa: E712
        ).order_by(
            VisionConfig.is_primary.desc(), VisionConfig.is_fallback.desc(), VisionConfig.id.asc(),
        ))).scalars().first()
        if vision is None:
            checks.append({"key": "vision", "name": "视觉模型", "available": False, "configured": False, "message": "未启用"})
        elif not vision.base_url or not vision.model_name or not vision.api_key:
            checks.append({"key": "vision", "name": "视觉模型", "available": False, "configured": False, "message": "配置不完整"})
        else:
            checks.append({"key": "vision", "name": "视觉模型", "available": vision.last_test_success is True,
                           "configured": True, "message": vision.model_name if vision.last_test_success is True else "待测试或最近测试失败"})
    except Exception as exc:
        checks.append({"key": "vision", "name": "视觉模型", "available": False, "message": str(exc)[:100]})
    return {"items": checks, "checked_at": datetime.utcnow().isoformat()}


async def load_web_search_config(db: AsyncSession) -> None:
    config = await db.get(WebSearchConfig, 1)
    if config is None:
        return
    settings.WEB_SEARCH_ENABLED = config.enabled
    settings.WEB_SEARCH_PROVIDER = config.provider
    settings.WEB_SEARCH_MAX_RESULTS = config.max_results
    settings.WEB_SEARCH_API_KEY = decrypt_api_key(
        config.exa_api_key if config.provider == "exa" else config.tavily_api_key
    )


@router.get("/web-search", response_model=WebSearchConfigOut)
async def get_web_search_config(db: AsyncSession = Depends(get_db)):
    config = await db.get(WebSearchConfig, 1)
    if config is None:
        return WebSearchConfigOut(enabled=settings.WEB_SEARCH_ENABLED, provider=settings.WEB_SEARCH_PROVIDER, max_results=settings.WEB_SEARCH_MAX_RESULTS)
    return WebSearchConfigOut(
        enabled=config.enabled,
        provider=config.provider,
        tavily_api_key=mask_api_key(decrypt_api_key(config.tavily_api_key)),
        exa_api_key=mask_api_key(decrypt_api_key(config.exa_api_key)),
        tavily_configured=bool(config.tavily_api_key),
        exa_configured=bool(config.exa_api_key),
        max_results=config.max_results,
    )


@router.put("/web-search", response_model=WebSearchConfigOut)
async def update_web_search_config(request: WebSearchConfigUpdate, db: AsyncSession = Depends(get_db)):
    config = await db.get(WebSearchConfig, 1)
    if config is None:
        config = WebSearchConfig(id=1)
        db.add(config)
    config.enabled, config.provider, config.max_results = request.enabled, request.provider, request.max_results
    if request.tavily_api_key:
        config.tavily_api_key = encrypt_api_key(request.tavily_api_key)
    if request.exa_api_key:
        config.exa_api_key = encrypt_api_key(request.exa_api_key)
    settings.WEB_SEARCH_ENABLED = config.enabled
    settings.WEB_SEARCH_PROVIDER = config.provider
    settings.WEB_SEARCH_MAX_RESULTS = config.max_results
    settings.WEB_SEARCH_API_KEY = decrypt_api_key(
        config.exa_api_key if config.provider == "exa" else config.tavily_api_key
    )
    await db.flush()
    return await get_web_search_config(db)


@router.post("/web-search/test", response_model=WebSearchTestResponse)
async def test_web_search_config(request: WebSearchTestRequest, db: AsyncSession = Depends(get_db)):
    config = await db.get(WebSearchConfig, 1)
    saved_key = ""
    if config:
        saved_key = decrypt_api_key(config.exa_api_key if request.provider == "exa" else config.tavily_api_key)
    api_key = request.api_key or saved_key
    from app.services.qa.web_search import web_search_service

    try:
        results = await web_search_service.search_with_config(
            request.query, request.provider, api_key, request.max_results, raise_errors=True,
        )
    except RuntimeError as exc:
        return WebSearchTestResponse(success=False, message=str(exc)[:300], provider=request.provider)
    if not results:
        if request.provider in {"tavily", "exa"} and not api_key:
            provider_name = "Exa" if request.provider == "exa" else "Tavily"
            return WebSearchTestResponse(success=False, message=f"请先填写或保存 {provider_name} API Key", provider=request.provider)
        if request.provider == "duckduckgo":
            return WebSearchTestResponse(
                success=False,
                message="DuckDuckGo 未返回结果，可能受网络访问、限流或页面规则影响",
                provider=request.provider,
            )
        return WebSearchTestResponse(success=False, message="未获取到结果，请检查搜索服务、网络或 API Key", provider=request.provider)
    return WebSearchTestResponse(success=True, message="网络检索可用", provider=request.provider, result_count=len(results))


# ============================================================
# 仪表盘统计
# ============================================================

@router.get("/dashboard", response_model=DashboardStatsOut)
async def get_dashboard_stats(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
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

    # 今日问答统计（含 Token 用量）
    range_start = datetime.combine(start_date or date.today(), dt_time.min)
    range_end = datetime.combine((end_date or date.today()) + timedelta(days=1), dt_time.min)
    qa_result = await db.execute(
        select(QAHistory).where(QAHistory.created_at >= range_start, QAHistory.created_at < range_end)
    )
    today_qas = qa_result.scalars().all()
    today_answers = len(today_qas)
    today_messages = today_answers * 2  # 估算
    # 成功率：非降级回答 / 总回答（is_degraded=False 且 is_cache_hit=False 为真实成功）
    real_answers = sum(1 for qa in today_qas if qa.answer and not qa.is_degraded)
    success_rate = (real_answers / today_answers * 100) if today_answers > 0 else 0.0
    # Token 统计
    today_input_tokens = sum(qa.input_tokens or 0 for qa in today_qas)
    today_output_tokens = sum(qa.output_tokens or 0 for qa in today_qas)
    def _legacy_web_search_count(raw_sources: str | None) -> int:
        """兼容新字段上线前的历史记录；实际新记录以独立计数为准。"""
        try:
            sources = json.loads(raw_sources or "[]")
            return int(any((item.get("metadata") or {}).get("source_type") == "web" or item.get("source_type") == "web" for item in sources))
        except (TypeError, ValueError, AttributeError):
            return 0

    web_search_count = sum(
        qa.web_search_count if (qa.web_search_count or 0) > 0 else _legacy_web_search_count(qa.sources)
        for qa in today_qas
    )

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
        today_messages=today_messages,
        today_answers=today_answers,
        success_rate=round(success_rate, 1),
        total_knowledge_chunks=total_chunks,
        total_documents=total_documents,
        cache_hit_rate=round(cache_hit_rate, 1),
        today_input_tokens=today_input_tokens,
        today_output_tokens=today_output_tokens,
        web_search_count=web_search_count,
    )


@router.get("/model-health")
async def get_model_health(db: AsyncSession = Depends(get_db)):
    configs = (await db.execute(select(LLMConfig).where(LLMConfig.is_active == True).order_by(LLMConfig.is_primary.desc(), LLMConfig.is_fallback.desc()))).scalars().all()  # noqa: E712
    from app.services.llm.gateway import llm_gateway
    chat_models = []
    for config in configs:
        test = await llm_gateway.test_connection(config.base_url, decrypt_api_key(config.api_key), config.model_name)
        chat_models.append({
            "name": config.model_name,
            "role": "默认问答模型" if config.is_primary else "兜底问答模型" if config.is_fallback else "问答模型",
            "available": test["success"],
            "message": test["message"],
        })
    from app.services.knowledge.embedder import embedding_service
    return {"chat_models": chat_models, "embedding": {"name": embedding_service.model_name, "available": await embedding_service.is_ready()}}


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
        enable_source_citation=settings.ENABLE_SOURCE_CITATION,
        enable_rate_limit=settings.ENABLE_RATE_LIMIT,
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
        # 转换为 settings 中的全大写下划线格式。
        attr_name = key.upper()
        if hasattr(settings, attr_name):
            setattr(settings, attr_name, value)
            logger.info(f"更新模块开关: {attr_name} = {value}")
        else:
            logger.warning(f"未知的配置项: {key}")

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


# ============================================================
# LLM 使用统计（仪表盘监控用，30s 刷新）
# ============================================================

@router.get("/llm-usage", response_model=list[LLMUsageStatsOut])
async def get_llm_usage_stats(
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有 LLM 配置的使用统计

    仪表盘每 30 秒调用一次，展示各 LLM 配置的：
    - 今日 Token 用量 / 限额
    - 今日请求数 / 限额
    - 连接状态
    """
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.is_active == True).order_by(LLMConfig.is_primary.desc())  # noqa: E712
    )
    configs = result.scalars().all()

    return configs


# ============================================================
# 记忆层管理
# ============================================================

@router.get("/memory/stats", response_model=MemoryStatsOut)
async def get_memory_stats():
    """
    获取记忆层统计信息

    返回记忆层是否可用、记忆总数等统计数据。
    """
    if not memory_service.is_available:
        # 尝试初始化
        try:
            await memory_service.initialize()
        except Exception:
            pass

    total_count = 0
    if memory_service.is_available:
        try:
            all_memories = await memory_service.get_all(limit=1000)
            total_count = len(all_memories)
        except Exception:
            total_count = 0

    return MemoryStatsOut(
        is_available=memory_service.is_available,
        total_count=total_count,
    )


@router.get("/memory/list", response_model=list[MemoryItemOut])
async def list_memories(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 50,
):
    """
    获取记忆列表

    可按 user_id / agent_id / run_id 过滤。
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        memories = await memory_service.get_all(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            limit=limit,
        )
        return memories
    except Exception as e:
        logger.error(f"获取记忆列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记忆列表失败: {str(e)}")


@router.post("/memory/search", response_model=list[MemoryItemOut])
async def search_memories(request: MemorySearchIn):
    """
    搜索记忆

    按语义相似度搜索相关记忆。
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        memories = await memory_service.search(
            query=request.query,
            user_id=request.user_id,
            agent_id=request.agent_id,
            run_id=request.run_id,
            limit=request.limit,
        )
        return memories
    except Exception as e:
        logger.error(f"搜索记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索记忆失败: {str(e)}")


@router.get("/memory/{memory_id}", response_model=MemoryItemOut)
async def get_memory(memory_id: str):
    """
    获取单条记忆详情
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        memory = await memory_service.get(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return memory
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记忆失败: {str(e)}")


@router.post("/memory", response_model=dict)
async def add_memory(request: MemoryAddIn):
    """
    手动添加记忆

    直接添加一段文本作为记忆（不经过 LLM 抽取）。
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        result = await memory_service.add_text(
            text=request.content,
            user_id=request.user_id,
            agent_id=request.agent_id,
            metadata=request.metadata,
        )
        return result
    except Exception as e:
        logger.error(f"添加记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加记忆失败: {str(e)}")


@router.put("/memory/{memory_id}", response_model=dict)
async def update_memory(memory_id: str, request: MemoryUpdateIn):
    """
    更新记忆内容
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        success = await memory_service.update(memory_id, request.content)
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新记忆失败: {str(e)}")


@router.delete("/memory/{memory_id}", response_model=dict)
async def delete_memory(memory_id: str):
    """
    删除单条记忆
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        success = await memory_service.delete(memory_id)
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除记忆失败: {str(e)}")


@router.delete("/memory", response_model=dict)
async def clear_memories(
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
    """
    清空记忆

    可按 user_id / agent_id / run_id 过滤，不传参数则清空所有记忆。
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        success = await memory_service.delete_all(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
        )
        return {"success": success}
    except Exception as e:
        logger.error(f"清空记忆失败: {e}")
        raise HTTPException(status_code=500, detail=f"清空记忆失败: {str(e)}")


@router.get("/memory/history/{memory_id}", response_model=list[dict])
async def get_memory_history(memory_id: str, limit: int = 50):
    """
    获取单条记忆的历史变更记录
    """
    if not memory_service.is_available:
        raise HTTPException(status_code=503, detail="记忆层未初始化")

    try:
        history = await memory_service.history(memory_id=memory_id, limit=limit)
        return history
    except Exception as e:
        logger.error(f"获取记忆历史失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取记忆历史失败: {str(e)}")
