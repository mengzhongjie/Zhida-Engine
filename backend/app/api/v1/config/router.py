"""
智答引擎（ZhiDa Engine）—— LLM 配置 API 路由

提供厂商模板查询、LLM 配置 CRUD、测试连接等接口。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.core.database import get_db
from app.core.security import encrypt_api_key, decrypt_api_key
from app.models.llm_config import LLMConfig
from app.schemas.llm_config import (
    ProviderTemplateOut,
    ProviderTemplateListOut,
    ProviderAutoFillRequest,
    ProviderAutoFillResponse,
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigOut,
    TestConnectionRequest,
    TestConnectionResponse,
)
from app.services.llm.provider_templates import (
    get_provider_by_id,
    get_cloud_providers,
)

router = APIRouter(prefix="/llm", tags=["LLM 配置"])


# ============================================================
# 辅助函数
# ============================================================

def _template_to_out(template) -> ProviderTemplateOut:
    """将 ProviderTemplate 转为输出 Schema"""
    return ProviderTemplateOut(
        provider_id=template.provider_id,
        name=template.name,
        category=template.category.value,
        base_url=template.base_url,
        default_model=template.default_model,
        available_models=template.available_models,
        requires_api_key=template.requires_api_key,
        api_key_label=template.api_key_label,
        icon=template.icon,
        description=template.description,
        docs_url=template.docs_url,
    )


def _mask_api_key(api_key: str) -> str:
    """脱敏 API Key —— 只显示前后 4 位"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]


def _config_to_out(config: LLMConfig) -> LLMConfigOut:
    """将数据库模型转为输出 Schema"""
    return LLMConfigOut(
        id=config.id,
        agent_id=config.agent_id,
        provider_id=config.provider_id,
        provider_name=config.provider_name,
        base_url=config.base_url,
        model_name=config.model_name,
        api_key=_mask_api_key(config.api_key),  # 脱敏
        is_primary=config.is_primary,
        is_fallback=config.is_fallback,
        is_active=config.is_active,
        extra_config=config.extra_config,
        max_tokens_per_request=config.max_tokens_per_request,
        max_requests_per_minute=config.max_requests_per_minute,
        max_tokens_per_minute=config.max_tokens_per_minute,
        max_tokens_per_day=config.max_tokens_per_day,
        tokens_used_today=config.tokens_used_today,
        requests_today=config.requests_today,
        last_test_at=config.last_test_at,
        last_test_success=config.last_test_success,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ============================================================
# 厂商模板查询
# ============================================================

@router.get("/providers", response_model=ProviderTemplateListOut)
async def list_providers():
    """
    获取所有厂商模板列表 —— 按云端/自定义分组

    前端用于渲染厂商选择下拉框。
    """
    cloud = [_template_to_out(t) for t in get_cloud_providers()]
    # 自定义模板单独处理
    custom = []
    custom_template = get_provider_by_id("custom")
    if custom_template:
        custom = [_template_to_out(custom_template)]

    return ProviderTemplateListOut(cloud=cloud, local=[], custom=custom)


@router.post("/providers/autofill", response_model=ProviderAutoFillResponse)
async def autofill_provider(request: ProviderAutoFillRequest):
    """
    根据厂商 ID 获取自动填充值

    用户选择厂商后，前端调用此接口获取默认 base_url、模型列表等字段，
    自动填充到表单中，API Key 字段留空由用户手动输入。
    """
    template = get_provider_by_id(request.provider_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"厂商 '{request.provider_id}' 不存在")

    return ProviderAutoFillResponse(
        provider_id=template.provider_id,
        provider_name=template.name,
        base_url=template.base_url,
        default_model=template.default_model,
        available_models=template.available_models,
        requires_api_key=template.requires_api_key,
        api_key_label=template.api_key_label,
        category=template.category.value,
    )


# ============================================================
# LLM 配置 CRUD
# ============================================================

@router.get("/configs", response_model=list[LLMConfigOut])
async def list_configs(
    agent_id: Optional[int] = Query(None, description="Agent ID，空=全局配置"),
    db: AsyncSession = Depends(get_db),
):
    """获取 LLM 配置列表"""
    query = select(LLMConfig)
    if agent_id is not None:
        query = query.where(LLMConfig.agent_id == agent_id)
    else:
        query = query.where(LLMConfig.agent_id.is_(None))

    query = query.order_by(LLMConfig.is_primary.desc(), LLMConfig.is_fallback.desc())
    result = await db.execute(query)
    configs = result.scalars().all()

    return [_config_to_out(c) for c in configs]


@router.post("/configs", response_model=LLMConfigOut)
async def create_config(
    request: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 LLM 配置"""
    if request.provider_id == "ollama":
        raise HTTPException(status_code=422, detail="不再支持本地模型配置，请使用云端 API")
    # 如果设为主模型，先将该 Agent 的其他主模型取消
    if request.is_primary:
        primary_query = select(LLMConfig).where(
            LLMConfig.is_primary == True,  # noqa: E712
            LLMConfig.agent_id == request.agent_id,
        )
        result = await db.execute(primary_query)
        existing_primary = result.scalars().all()
        for config in existing_primary:
            config.is_primary = False

    # 获取厂商模板，自动填充缺失字段
    template = get_provider_by_id(request.provider_id)
    provider_name = request.provider_name or (template.name if template else "自定义")
    base_url = request.base_url or (template.base_url if template else "")

    config = LLMConfig(
        agent_id=request.agent_id,
        provider_id=request.provider_id,
        provider_name=provider_name,
        base_url=base_url,
        model_name=request.model_name,
        api_key=encrypt_api_key(request.api_key or ""),  # 加密存储
        is_primary=request.is_primary,
        is_fallback=request.is_fallback and not request.is_primary,
        extra_config=request.extra_config,
        max_tokens_per_request=request.max_tokens_per_request,
        max_requests_per_minute=request.max_requests_per_minute,
        max_tokens_per_minute=request.max_tokens_per_minute,
        max_tokens_per_day=request.max_tokens_per_day,
    )

    db.add(config)
    await db.flush()
    await db.refresh(config)

    return _config_to_out(config)


@router.put("/configs/{config_id}", response_model=LLMConfigOut)
async def update_config(
    config_id: int,
    request: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 LLM 配置"""
    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="LLM 配置不存在")

    # 如果设为主模型，先将该 Agent 的其他主模型取消
    if request.is_primary:
        primary_query = select(LLMConfig).where(
            LLMConfig.is_primary == True,  # noqa: E712
            LLMConfig.agent_id == config.agent_id,
            LLMConfig.id != config_id,
        )
        result = await db.execute(primary_query)
        for c in result.scalars().all():
            c.is_primary = False

    # 更新字段
    update_data = request.model_dump(exclude_unset=True)
    if update_data.get("is_primary") is True:
        update_data["is_fallback"] = False
    elif update_data.get("is_fallback") is True:
        update_data["is_primary"] = False
    logger.info(f"更新配置 {config_id}: 字段={list(update_data.keys())}")
    for key, value in update_data.items():
        # API Key 特殊处理：空字符串表示不修改，有值时加密存储
        if key == "api_key":
            logger.info(f"  api_key: 收到值长度={len(value) if value else 0}, is_none={value is None}, is_empty={value == ''}")
            if value is not None and value != "":
                encrypted = encrypt_api_key(value)
                logger.info(f"  api_key: 加密后长度={len(encrypted)}, 前4位={encrypted[:4]}")
                setattr(config, key, encrypted)
            else:
                logger.info(f"  api_key: 跳过（空值不修改）")
        else:
            setattr(config, key, value)

    await db.flush()
    await db.refresh(config)

    return _config_to_out(config)


@router.delete("/configs/{config_id}")
async def delete_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除 LLM 配置"""
    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="LLM 配置不存在")

    await db.delete(config)
    await db.flush()

    return {"message": "删除成功", "id": config_id}


# ============================================================
# 测试连接
# ============================================================

@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_connection(request: TestConnectionRequest):
    """
    测试 LLM 连接 —— 发送测试消息验证连通性

    用户填写配置后，点击"测试连接"按钮调用此接口。
    """
    from app.services.llm.gateway import llm_gateway  # 延迟导入，避免启动时加载 openai

    result = await llm_gateway.test_connection(
        base_url=request.base_url,
        api_key=request.api_key,
        model_name=request.model_name,
    )

    return TestConnectionResponse(
        success=result["success"],
        message=result["message"],
        latency_ms=result["latency_ms"],
        model=result["model"],
    )


@router.post("/configs/{config_id}/test", response_model=TestConnectionResponse)
async def test_configured_model(
    config_id: int,
    db: AsyncSession = Depends(get_db),
):
    """测试已保存的 LLM 配置连接"""
    from app.services.llm.gateway import llm_gateway  # 延迟导入，避免启动时加载 openai

    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise HTTPException(status_code=404, detail="LLM 配置不存在")

    decrypted_key = decrypt_api_key(config.api_key)
    logger.info(f"测试配置 {config_id}: api_key原始长度={len(config.api_key)}, 解密后长度={len(decrypted_key)}, 解密后最后4位={decrypted_key[-4:] if decrypted_key and len(decrypted_key)>=4 else decrypted_key}")

    test_result = await llm_gateway.test_connection(
        base_url=config.base_url,
        api_key=decrypted_key,  # 解密后使用
        model_name=config.model_name,
    )

    # 更新测试结果
    from datetime import datetime
    config.last_test_at = datetime.utcnow()
    config.last_test_success = test_result["success"]
    await db.flush()

    return TestConnectionResponse(
        success=test_result["success"],
        message=test_result["message"],
        latency_ms=test_result["latency_ms"],
        model=test_result["model"],
    )
