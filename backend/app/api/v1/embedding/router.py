"""
智答引擎（ZhiDa Engine）—— 向量化配置 API 路由

提供 Embedding 模型配置的查询、更新、测试连接等接口。
支持本地模型（BGE 等）和云端 API（OpenAI 兼容）两种模式切换。
"""

import time
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from app.models.embedding_config import EmbeddingConfig
from app.models.embedding_profile import EmbeddingProfile
from app.models.knowledge import KnowledgeBase
from app.schemas.embedding import (
    EmbeddingConfigOut,
    EmbeddingConfigUpdate,
    EmbeddingTestRequest,
    EmbeddingTestResponse,
)
from app.services.knowledge.embedder import (
    embedding_service,
    LocalBGEEmbedding,
    CloudEmbedding,
)
from app.services.knowledge.document_processor import schedule_knowledge_base_rebuild
from app.services.knowledge.embedding_providers import (
    BUILTIN_EMBEDDING_PROVIDERS,
    get_embedding_provider_by_id,
    get_cloud_embedding_providers,
    EmbeddingProviderTemplate,
)

router = APIRouter(prefix="/embedding", tags=["向量化配置"])

class EmbeddingProfileRequest(BaseModel):
    name: str = "向量模型"
    provider_id: str = "custom"
    provider_name: str = "自定义"
    mode: str = "local"
    local_model: str = "BAAI/bge-large-zh-v1.5"
    local_device: str = "cpu"
    cloud_base_url: str = ""
    cloud_api_key: str | None = None
    cloud_model: str = "text-embedding-3-small"
    cloud_dimension: int = 1536
    is_active: bool = True


def _profile_out(item: EmbeddingProfile) -> dict:
    return {
        "id": item.id, "name": item.name, "provider_id": item.provider_id,
        "provider_name": item.provider_name, "mode": item.mode,
        "local_model": item.local_model, "local_device": item.local_device,
        "cloud_base_url": item.cloud_base_url,
        "cloud_api_key": mask_api_key(decrypt_api_key(item.cloud_api_key)),
        "cloud_model": item.cloud_model, "cloud_dimension": item.cloud_dimension,
        "model": item.local_model if item.mode == "local" else item.cloud_model,
        "dimension": item.cloud_dimension if item.mode == "cloud" else None,
        "is_primary": item.is_primary, "is_active": item.is_active,
        "last_test_at": item.last_test_at, "last_test_success": item.last_test_success,
        "last_error": item.last_error,
    }


async def _ensure_embedding_profile(db: AsyncSession) -> None:
    # scalar 可能是 0/None；不要依赖 SQLAlchemy Row 的真值，避免每次读取
    # 配置页都错误地重新种子化一条“当前向量模型”。
    existing_id = (await db.execute(select(EmbeddingProfile.id).limit(1))).scalar_one_or_none()
    if existing_id is not None:
        return
    current = (await db.execute(select(EmbeddingConfig).where(EmbeddingConfig.id == 1))).scalar_one_or_none()
    item = EmbeddingProfile(
        name="当前向量模型", provider_id="local" if not current or current.mode == "local" else "custom",
        provider_name="本地模型" if not current or current.mode == "local" else "云端 API",
        mode=current.mode if current else getattr(settings, "EMBEDDING_MODE", "local"),
        local_model=current.local_model if current else settings.EMBEDDING_MODEL,
        local_device=current.local_device if current else settings.EMBEDDING_DEVICE,
        cloud_base_url=current.cloud_base_url if current else getattr(settings, "EMBEDDING_CLOUD_BASE_URL", ""),
        cloud_api_key=current.cloud_api_key if current else getattr(settings, "EMBEDDING_CLOUD_API_KEY", ""),
        cloud_model=current.cloud_model if current else getattr(settings, "EMBEDDING_CLOUD_MODEL", "text-embedding-3-small"),
        cloud_dimension=current.cloud_dimension if current else getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 1536),
        is_primary=True, is_active=True,
    )
    db.add(item)
    await db.flush()


@router.get("/profiles")
async def list_embedding_profiles(db: AsyncSession = Depends(get_db)):
    await _ensure_embedding_profile(db)
    items = (await db.execute(select(EmbeddingProfile).order_by(
        EmbeddingProfile.is_primary.desc(), EmbeddingProfile.updated_at.desc(),
    ))).scalars().all()
    return [_profile_out(item) for item in items]


@router.post("/profiles")
async def create_embedding_profile(request: EmbeddingProfileRequest, db: AsyncSession = Depends(get_db)):
    if request.mode not in {"local", "cloud"}:
        raise HTTPException(status_code=422, detail="向量模式只能是 local 或 cloud")
    if request.mode == "cloud" and (not request.cloud_base_url or not request.cloud_model or not request.cloud_api_key):
        raise HTTPException(status_code=422, detail="请填写完整的云端向量配置")
    item = EmbeddingProfile(
        name=request.name.strip(), provider_id=request.provider_id, provider_name=request.provider_name,
        mode=request.mode, is_active=request.is_active, local_model=request.local_model,
        local_device=request.local_device, cloud_base_url=request.cloud_base_url.strip().rstrip("/"),
        cloud_api_key=encrypt_api_key(request.cloud_api_key) if request.cloud_api_key else "",
        cloud_model=request.cloud_model, cloud_dimension=request.cloud_dimension,
    )
    db.add(item)
    await db.flush()
    return _profile_out(item)


@router.put("/profiles/{profile_id}")
async def update_embedding_profile(profile_id: int, request: EmbeddingProfileRequest, db: AsyncSession = Depends(get_db)):
    item = await db.get(EmbeddingProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="向量配置不存在")
    if item.is_primary:
        changed = (request.mode != item.mode or request.local_model != item.local_model or
                   request.cloud_model != item.cloud_model or request.cloud_dimension != item.cloud_dimension)
        if changed and (await db.execute(select(KnowledgeBase.id).where(KnowledgeBase.chunk_count > 0))).first():
            raise HTTPException(status_code=409, detail="主向量配置已被索引使用；请新增配置并通过‘设为主模型’执行重建切换")
    item.name, item.provider_id, item.provider_name = request.name.strip(), request.provider_id, request.provider_name
    item.mode, item.local_model, item.local_device = request.mode, request.local_model, request.local_device
    item.cloud_base_url = request.cloud_base_url.strip().rstrip("/")
    item.cloud_model, item.cloud_dimension, item.is_active = request.cloud_model, request.cloud_dimension, request.is_active
    if request.cloud_api_key:
        item.cloud_api_key = encrypt_api_key(request.cloud_api_key)
    return _profile_out(item)


@router.delete("/profiles/{profile_id}")
async def delete_embedding_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(EmbeddingProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="向量配置不存在")
    if item.is_primary:
        raise HTTPException(status_code=409, detail="当前主向量配置不能删除")
    await db.delete(item)
    return {"success": True}


@router.post("/profiles/{profile_id}/test", response_model=EmbeddingTestResponse)
async def test_embedding_profile(profile_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(EmbeddingProfile, profile_id)
    if item is None:
        raise HTTPException(status_code=404, detail="向量配置不存在")
    started = time.time()
    try:
        service = (CloudEmbedding(base_url=item.cloud_base_url, api_key=decrypt_api_key(item.cloud_api_key),
                                  model_name=item.cloud_model, dimension=item.cloud_dimension)
                   if item.mode == "cloud" else LocalBGEEmbedding(item.local_model, item.local_device))
        result = await service.embed_text("测试连接")
        item.last_test_at, item.last_test_success, item.last_error = datetime.utcnow(), True, None
        return EmbeddingTestResponse(success=True, message="连接成功", latency_ms=(time.time()-started)*1000, dimension=len(result))
    except Exception as exc:
        item.last_test_at, item.last_test_success, item.last_error = datetime.utcnow(), False, str(exc)[:500]
        return EmbeddingTestResponse(success=False, message=f"连接失败: {exc}", latency_ms=(time.time()-started)*1000)


@router.post("/profiles/{profile_id}/activate")
async def activate_embedding_profile(profile_id: int, rebuild: bool = Query(False), db: AsyncSession = Depends(get_db)):
    item = await db.get(EmbeddingProfile, profile_id)
    if item is None or not item.is_active:
        raise HTTPException(status_code=404, detail="可用向量配置不存在")
    affected = list((await db.execute(select(KnowledgeBase).where(KnowledgeBase.chunk_count > 0))).scalars())
    if affected and not rebuild:
        raise HTTPException(status_code=409, detail={"message": "切换向量模型需要重建现有知识库索引", "requires_rebuild": True,
                                                     "knowledge_base_count": len(affected)})
    for other in (await db.execute(select(EmbeddingProfile))).scalars():
        other.is_primary = other.id == item.id
    settings.EMBEDDING_MODE, settings.EMBEDDING_MODEL, settings.EMBEDDING_DEVICE = item.mode, item.local_model, item.local_device
    settings.EMBEDDING_CLOUD_BASE_URL, settings.EMBEDDING_CLOUD_API_KEY = item.cloud_base_url, item.cloud_api_key
    settings.EMBEDDING_CLOUD_MODEL, settings.EMBEDDING_CLOUD_DIMENSION = item.cloud_model, item.cloud_dimension
    _reload_embedding_service()
    await save_embedding_config_to_db(db)
    for kb in affected:
        kb.index_status = "rebuild_required"
    await db.commit()
    for kb in affected:
        schedule_knowledge_base_rebuild(kb.id)
    return {**_profile_out(item), "rebuild_started": len(affected)}


# ============================================================
# 数据库持久化辅助函数
# ============================================================

async def load_embedding_config_from_db(db: AsyncSession) -> bool:
    """
    从数据库加载向量化配置到 settings

    Returns:
        True 表示从数据库加载了配置，False 表示数据库中没有配置（使用默认值）
    """
    result = await db.execute(select(EmbeddingConfig).where(EmbeddingConfig.id == 1))
    config = result.scalar_one_or_none()

    if config is None:
        logger.info("数据库中无向量化配置，使用默认值")
        return False

    # 将数据库配置同步到 settings
    settings.EMBEDDING_MODE = config.mode
    settings.EMBEDDING_MODEL = config.local_model
    settings.EMBEDDING_DEVICE = config.local_device
    settings.EMBEDDING_CLOUD_BASE_URL = config.cloud_base_url
    settings.EMBEDDING_CLOUD_API_KEY = config.cloud_api_key  # 数据库中存的是加密后的
    settings.EMBEDDING_CLOUD_MODEL = config.cloud_model
    settings.EMBEDDING_CLOUD_DIMENSION = config.cloud_dimension

    logger.info(f"从数据库加载向量化配置: mode={config.mode}, model={config.local_model if config.mode == 'local' else config.cloud_model}")
    return True


async def save_embedding_config_to_db(db: AsyncSession) -> EmbeddingConfig:
    """
    将当前 settings 中的配置保存到数据库

    只有一条记录（id=1），不存在则创建，存在则更新。
    """
    result = await db.execute(select(EmbeddingConfig).where(EmbeddingConfig.id == 1))
    config = result.scalar_one_or_none()

    if config is None:
        config = EmbeddingConfig(id=1)
        db.add(config)

    config.mode = getattr(settings, "EMBEDDING_MODE", "local")
    config.local_model = settings.EMBEDDING_MODEL
    config.local_device = settings.EMBEDDING_DEVICE
    config.cloud_base_url = getattr(settings, "EMBEDDING_CLOUD_BASE_URL", "")
    config.cloud_api_key = getattr(settings, "EMBEDDING_CLOUD_API_KEY", "")
    config.cloud_model = getattr(settings, "EMBEDDING_CLOUD_MODEL", "text-embedding-3-small")
    config.cloud_dimension = getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 1536)

    await db.flush()
    await db.refresh(config)

    logger.info("向量化配置已保存到数据库")
    return config


async def init_embedding_config(db: AsyncSession):
    """
    初始化向量化配置 —— 应用启动时调用

    1. 从数据库加载配置
    2. 根据配置重新初始化 embedding_service
    """
    loaded = await load_embedding_config_from_db(db)
    if loaded:
        _reload_embedding_service()
        logger.info("向量化配置初始化完成（从数据库加载）")
    else:
        logger.info("向量化配置初始化完成（使用默认值）")


# ============================================================
# 厂商模板 API
# ============================================================

class EmbeddingProviderOut(BaseModel):
    """向量化厂商模板输出"""
    provider_id: str
    name: str
    category: str
    base_url: str
    default_model: str
    default_dimension: int
    available_models: list[dict] = []
    requires_api_key: bool
    api_key_label: str
    icon: str
    description: str
    docs_url: str


def _provider_to_out(template: EmbeddingProviderTemplate) -> EmbeddingProviderOut:
    """模板转换为输出格式"""
    return EmbeddingProviderOut(
        provider_id=template.provider_id,
        name=template.name,
        category=template.category.value,
        base_url=template.base_url,
        default_model=template.default_model,
        default_dimension=template.default_dimension,
        available_models=[
            {"model": m, "dimension": d}
            for m, d in template.available_models
        ],
        requires_api_key=template.requires_api_key,
        api_key_label=template.api_key_label,
        icon=template.icon,
        description=template.description,
        docs_url=template.docs_url,
    )


@router.get("/providers")
async def get_embedding_providers():
    """
    获取向量化厂商模板列表

    返回所有内置的云端 Embedding 厂商模板，用户选择后可自动填充配置。
    """
    cloud = [_provider_to_out(p) for p in get_cloud_embedding_providers()]
    custom = [_provider_to_out(p) for p in BUILTIN_EMBEDDING_PROVIDERS if p.category.value == "custom"]
    return {
        "cloud": cloud,
        "custom": custom,
    }


@router.post("/providers/autofill")
async def autofill_embedding_provider(request: dict):
    """
    根据厂商 ID 自动填充配置

    选择厂商后调用此接口，自动填充 base_url、默认模型、维度等信息。
    """
    provider_id = request.get("provider_id", "")
    provider = get_embedding_provider_by_id(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="厂商不存在")

    return {
        "provider_id": provider.provider_id,
        "provider_name": provider.name,
        "base_url": provider.base_url,
        "default_model": provider.default_model,
        "default_dimension": provider.default_dimension,
        "available_models": [
            {"model": m, "dimension": d}
            for m, d in provider.available_models
        ],
    }


# ============================================================
# 辅助函数
# ============================================================

def _get_config_out() -> EmbeddingConfigOut:
    """获取当前 Embedding 配置输出（不含 is_ready，需调用方单独检查）"""
    return EmbeddingConfigOut(
        mode=getattr(settings, "EMBEDDING_MODE", "local"),
        local_model=settings.EMBEDDING_MODEL,
        local_device=settings.EMBEDDING_DEVICE,
        cloud_base_url=getattr(settings, "EMBEDDING_CLOUD_BASE_URL", ""),
        cloud_api_key=mask_api_key(decrypt_api_key(getattr(settings, "EMBEDDING_CLOUD_API_KEY", ""))),
        cloud_model=getattr(settings, "EMBEDDING_CLOUD_MODEL", "text-embedding-3-small"),
        cloud_dimension=getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 1536),
        is_ready=False,  # 由调用方单独检查
        current_model=embedding_service.model_name,
        current_dimension=embedding_service.dimension,
    )


def _reload_embedding_service():
    """重新加载 Embedding 服务实例（配置变更后调用）"""
    mode = getattr(settings, "EMBEDDING_MODE", "local")
    if mode == "cloud":
        base_url = getattr(settings, "EMBEDDING_CLOUD_BASE_URL", "")
        api_key = decrypt_api_key(getattr(settings, "EMBEDDING_CLOUD_API_KEY", ""))
        model = getattr(settings, "EMBEDDING_CLOUD_MODEL", "text-embedding-3-small")
        dimension = getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 1536)
        new_service = CloudEmbedding(
            base_url=base_url,
            api_key=api_key,
            model_name=model,
            dimension=dimension,
        )
        embedding_service.switch_to(new_service)
    else:
        new_service = LocalBGEEmbedding(
            model_name=settings.EMBEDDING_MODEL,
            device=settings.EMBEDDING_DEVICE,
        )
        embedding_service.switch_to(new_service)


# ============================================================
# 配置查询/更新
# ============================================================

@router.get("/config", response_model=EmbeddingConfigOut)
async def get_embedding_config():
    """
    获取当前向量化配置

    返回当前使用的向量化模式（本地/云端）、模型名称、维度等信息。
    """
    is_ready = False
    try:
        is_ready = await embedding_service.is_ready()
    except Exception:
        pass

    out = _get_config_out()
    out.is_ready = is_ready
    return out


@router.put("/config", response_model=EmbeddingConfigOut)
async def update_embedding_config(
    request: EmbeddingConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新向量化配置

    支持切换本地/云端模式、修改模型参数等。
    更新后自动重载 Embedding 服务实例，并持久化到数据库。
    """
    update_data = request.model_dump(exclude_unset=True)
    logger.info(f"更新向量化配置: {list(update_data.keys())}")

    # 向量模型、模式或维度改变后，新旧向量无法比较。轻量方案不做在线迁移，明确要求先重建。
    index_fields = {"mode", "model", "local_model", "cloud_model", "cloud_dimension"}
    if index_fields.intersection(update_data):
        current = {
            "mode": settings.EMBEDDING_MODE,
            "local_model": settings.EMBEDDING_MODEL,
            "cloud_model": getattr(settings, "EMBEDDING_CLOUD_MODEL", ""),
            "cloud_dimension": getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 1536),
        }
        candidate = {**current, **update_data}
        changed = any(candidate.get(key) != current.get(key) for key in current if key in candidate)
        if changed:
            affected = (await db.execute(select(KnowledgeBase.id, KnowledgeBase.name).where(KnowledgeBase.chunk_count > 0))).all()
            if affected:
                names = "、".join(name for _, name in affected[:5])
                raise HTTPException(status_code=409, detail=f"已有知识库索引（{names}）使用当前向量配置；请先重建索引后再切换模型或维度")

    setting_keys = {"local_model": "EMBEDDING_MODEL", "local_device": "EMBEDDING_DEVICE"}
    for key, value in update_data.items():
        # API Key 特殊处理：加密存储
        if key == "cloud_api_key":
            if value is not None and value != "":
                encrypted = encrypt_api_key(value)
                if not hasattr(settings, "EMBEDDING_CLOUD_API_KEY"):
                    setattr(settings, "EMBEDDING_CLOUD_API_KEY", "")
                settings.EMBEDDING_CLOUD_API_KEY = encrypted
                logger.info(f"  cloud_api_key: 已加密更新, 长度={len(encrypted)}")
            else:
                logger.info(f"  cloud_api_key: 跳过（空值不修改）")
            continue

        # 其他配置项直接映射到 settings
        setting_key = setting_keys.get(key, f"EMBEDDING_{key.upper()}")
        if hasattr(settings, setting_key):
            setattr(settings, setting_key, value)
            logger.info(f"  {key}: {value}")
        else:
            # 动态添加属性（云端配置可能不存在）
            setattr(settings, setting_key, value)
            logger.info(f"  {key}: {value} (新增)")

    # 重新加载 Embedding 服务
    _reload_embedding_service()

    # 持久化到数据库
    await save_embedding_config_to_db(db)

    out = _get_config_out()
    try:
        out.is_ready = await embedding_service.is_ready()
    except Exception:
        pass
    return out


# ============================================================
# 测试连接
# ============================================================

@router.post("/test", response_model=EmbeddingTestResponse)
async def test_embedding_connection(
    request: EmbeddingTestRequest,
):
    """
    测试向量化连接

    支持测试本地模型加载或云端 API 连接。
    不修改当前配置，仅用于验证参数是否正确。
    """
    start_time = time.time()

    try:
        if request.mode == "cloud":
            base_url = request.cloud_base_url or getattr(settings, "EMBEDDING_CLOUD_BASE_URL", "")
            api_key = request.cloud_api_key or decrypt_api_key(
                getattr(settings, "EMBEDDING_CLOUD_API_KEY", "")
            )
            model_name = request.cloud_model or getattr(settings, "EMBEDDING_CLOUD_MODEL", "")
            if not base_url or not api_key or not model_name:
                return EmbeddingTestResponse(
                    success=False,
                    message="请填写完整的云端配置，或先保存一组可复用的配置",
                )

            test_service = CloudEmbedding(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
            )

            # 发送测试请求
            result = await test_service.embed_text("测试连接")
            latency_ms = (time.time() - start_time) * 1000

            return EmbeddingTestResponse(
                success=True,
                message=f"连接成功！向量维度: {len(result)}",
                latency_ms=round(latency_ms, 2),
                dimension=len(result),
            )

        else:
            # 测试本地模型
            model_name = request.local_model or settings.EMBEDDING_MODEL
            device = request.local_device or settings.EMBEDDING_DEVICE

            test_service = LocalBGEEmbedding(
                model_name=model_name,
                device=device,
            )

            # 尝试加载模型并测试
            result = await test_service.embed_text("测试连接")
            latency_ms = (time.time() - start_time) * 1000

            return EmbeddingTestResponse(
                success=True,
                message=f"模型加载成功！向量维度: {len(result)}",
                latency_ms=round(latency_ms, 2),
                dimension=len(result),
            )

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        logger.error(f"向量化测试失败: {e}")
        error_msg = str(e)
        # 避免重复的前缀（如果异常消息已经包含"失败"等词，不再加前缀）
        if "失败" in error_msg or "错误" in error_msg:
            display_msg = error_msg
        else:
            display_msg = f"连接失败: {error_msg}"
        return EmbeddingTestResponse(
            success=False,
            message=display_msg,
            latency_ms=round(latency_ms, 2),
        )
