"""视觉模型配置：多模型列表、连通性测试与主/降级角色。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decrypt_api_key, encrypt_api_key, mask_api_key
from app.models.vision_config import VisionConfig
from app.schemas.vision import VisionConfigOut, VisionConfigUpdate

router = APIRouter(prefix="/vision", tags=["视觉模型配置"])


def _out(config: VisionConfig) -> VisionConfigOut:
    return VisionConfigOut(
        id=config.id, name=config.name, is_primary=config.is_primary, is_fallback=config.is_fallback,
        enabled=config.enabled, base_url=config.base_url, model_name=config.model_name,
        api_key=mask_api_key(decrypt_api_key(config.api_key)), last_test_at=config.last_test_at,
        last_test_success=config.last_test_success, last_error=config.last_error,
    )


async def _configs(db: AsyncSession) -> list[VisionConfig]:
    configs = list((await db.execute(select(VisionConfig).order_by(
        VisionConfig.is_primary.desc(), VisionConfig.is_fallback.desc(), VisionConfig.id.asc(),
    ))).scalars())
    if configs and not any(item.is_primary for item in configs):
        configs[0].is_primary = True
    return configs


async def _apply_roles(db: AsyncSession, config: VisionConfig, primary: bool, fallback: bool) -> None:
    if primary:
        for item in await _configs(db):
            if item.id != config.id:
                item.is_primary = False
        fallback = False
    config.is_primary, config.is_fallback = primary, fallback


@router.get("/configs", response_model=list[VisionConfigOut])
async def list_configs(db: AsyncSession = Depends(get_db)):
    return [_out(config) for config in await _configs(db)]


@router.post("/configs", response_model=VisionConfigOut)
async def create_config(request: VisionConfigUpdate, db: AsyncSession = Depends(get_db)):
    if request.enabled and (not request.base_url.strip() or not request.model_name.strip() or not request.api_key):
        raise HTTPException(status_code=422, detail="启用视觉模型前，请填写 API 地址、模型名称和 API Key")
    config = VisionConfig(name=request.name.strip(), enabled=request.enabled,
                          base_url=request.base_url.strip().rstrip("/"), model_name=request.model_name.strip(),
                          api_key=encrypt_api_key(request.api_key.strip()) if request.api_key else "")
    db.add(config)
    await db.flush()
    await _apply_roles(db, config, request.is_primary, request.is_fallback)
    return _out(config)


@router.put("/configs/{config_id}", response_model=VisionConfigOut)
async def update_config(config_id: int, request: VisionConfigUpdate, db: AsyncSession = Depends(get_db)):
    config = await db.get(VisionConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="视觉模型配置不存在")
    config.name, config.enabled = request.name.strip(), request.enabled
    config.base_url, config.model_name = request.base_url.strip().rstrip("/"), request.model_name.strip()
    if request.api_key:
        config.api_key = encrypt_api_key(request.api_key.strip())
    if config.enabled and (not config.base_url or not config.model_name or not config.api_key):
        raise HTTPException(status_code=422, detail="启用视觉模型前，请填写 API 地址、模型名称和 API Key")
    await _apply_roles(db, config, request.is_primary, request.is_fallback)
    return _out(config)


@router.delete("/configs/{config_id}")
async def delete_config(config_id: int, db: AsyncSession = Depends(get_db)):
    config = await db.get(VisionConfig, config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="视觉模型配置不存在")
    if config.is_primary:
        raise HTTPException(status_code=409, detail="当前主视觉模型不能删除，请先设置其他主模型")
    await db.delete(config)
    return {"success": True}


@router.post("/configs/{config_id}/test")
async def test_config(config_id: int, db: AsyncSession = Depends(get_db)):
    config = await db.get(VisionConfig, config_id)
    if config is None or not config.base_url or not config.model_name or not config.api_key:
        raise HTTPException(status_code=422, detail="请先保存完整的视觉模型配置")
    try:
        client = AsyncOpenAI(base_url=config.base_url, api_key=decrypt_api_key(config.api_key), timeout=20.0)
        response = await client.chat.completions.create(model=config.model_name, messages=[{"role": "user", "content": [
            {"type": "text", "text": "这是一张测试图片。请仅回复：视觉模型连接成功"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAN0lEQVR4nO3RwQ0AMAjDwJT9d05HMB9+vgGCZF7bXJrT9XhgwR8gEyETIRMhEyETIRMhEyEThXzH8QM9OMM6fAAAAABJRU5ErkJggg=="}},
        ]}], temperature=0, max_tokens=32)
        await client.close()
        if not (response.choices and (response.choices[0].message.content or "").strip()):
            raise RuntimeError("模型返回空正文")
        config.last_test_at, config.last_test_success, config.last_error = datetime.utcnow(), True, None
        return {"success": True, "message": "视觉模型图片输入测试成功"}
    except Exception as exc:
        logger.warning(f"视觉模型测试失败: {type(exc).__name__}: {exc}")
        config.last_test_at, config.last_test_success, config.last_error = datetime.utcnow(), False, str(exc)[:500]
        return {"success": False, "message": "视觉模型连接失败，请检查配置"}


# 兼容旧前端/旧数据库调用；新界面使用 /configs。
@router.get("/config", response_model=VisionConfigOut)
async def get_config(db: AsyncSession = Depends(get_db)):
    configs = await _configs(db)
    return _out(configs[0]) if configs else VisionConfigOut()


@router.put("/config", response_model=VisionConfigOut)
async def update_legacy_config(request: VisionConfigUpdate, db: AsyncSession = Depends(get_db)):
    """兼容单配置界面：更新首个配置，首次调用时创建主配置。"""
    configs = await _configs(db)
    if configs:
        return await update_config(configs[0].id, request, db)
    return await create_config(request.model_copy(update={"is_primary": True, "is_fallback": False}), db)
