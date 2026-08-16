"""飞书官方机器人管理接口。"""
import re
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import decrypt_api_key, encrypt_api_key, mask_api_key
from app.models.agent import Agent
from app.models.feishu_bot import FeishuBotConfig, FeishuChatBinding

router = APIRouter(prefix="/feishu-bot", tags=["飞书机器人"])
_CHAT_ID = re.compile(r"^oc_[A-Za-z0-9_-]{1,128}$")


class ConfigIn(BaseModel):
    enabled: bool = False
    app_id: str = Field(default="", max_length=100)
    app_secret: str | None = Field(default=None, max_length=500)
    response_detail: str | None = Field(default=None, pattern="^(concise|detailed)$")


class DetailIn(BaseModel):
    response_detail: str = Field(..., pattern="^(concise|detailed)$")


class BindingIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=128)
    chat_name: str = Field(default="", max_length=255)
    agent_id: int = Field(gt=0)
    is_active: bool = True

    @field_validator("chat_id")
    @classmethod
    def valid_chat_id(cls, value: str):
        value = value.strip()
        if not _CHAT_ID.fullmatch(value):
            raise ValueError("群 ID 格式不合法（应为 oc_ 开头）")
        return value


async def _config(db):
    item = await db.get(FeishuBotConfig, 1)
    if item is None:
        item = FeishuBotConfig(id=1)
        db.add(item)
        await db.flush()
    return item


def _service():
    from app.services.channel.feishu_bot import feishu_bot_service
    return feishu_bot_service


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    status = await _service().config_status()
    return {
        "enabled": status["enabled"],
        "app_id": item.app_id,
        "app_secret": mask_api_key(decrypt_api_key(item.app_secret)),
        "last_test_success": item.last_test_success,
        "last_error": item.last_error,
        "effective_app_id": status["effective_app_id"],
        "use_cloud_config": status["use_cloud_config"],
        "response_detail": item.response_detail,
    }


@router.put("/config")
async def save_config(payload: ConfigIn, db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    if payload.enabled:
        # 凭据可用：本次提交的 / 已保存的机器人凭据，或云文档飞书应用
        bot_ready = bool((payload.app_id.strip() or item.app_id) and (payload.app_secret or item.app_secret))
        if not bot_ready:
            from app.models.feishu_config import FeishuConfig
            cloud = await db.get(FeishuConfig, 1)
            if not (cloud and cloud.app_id and cloud.app_secret):
                raise HTTPException(422, "启用前请填写 App ID 与 App Secret，或先在「云文档」中配置飞书应用")
    item.enabled, item.app_id = payload.enabled, payload.app_id.strip()
    if payload.response_detail:
        item.response_detail = payload.response_detail
    if payload.app_secret:
        item.app_secret = encrypt_api_key(payload.app_secret.strip())
    await db.commit()
    await _service().reload()
    return await get_config(db)


@router.put("/config/detail")
async def update_detail(payload: DetailIn, db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    item.response_detail = payload.response_detail
    await db.commit()
    return {"response_detail": item.response_detail}


@router.post("/config/test")
async def test_config(db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    creds = await _service()._credentials()
    if not creds:
        raise HTTPException(422, "请先填写 App ID 与 App Secret（或复用云文档飞书应用）")
    app_id, secret, _ = creds
    ok, detail = await _service().test_credentials(app_id, secret)
    item.last_test_success, item.last_error = ok, None if ok else detail
    await db.commit()
    source = "云文档应用" if creds[2] == "cloud" else "机器人配置"
    return {"success": ok, "message": f"飞书机器人凭据可用（{source}）" if ok else detail}


@router.get("/chats")
async def chats(db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    if not item.enabled:
        raise HTTPException(422, "请先启用飞书机器人")
    creds = await _service()._credentials()
    if not creds:
        raise HTTPException(422, "请先配置飞书凭据（或复用云文档飞书应用）")
    try:
        return await _service().list_chats(creds[0], creds[1])
    except Exception as exc:
        import logging
        logging.getLogger("app.api.v1.feishu_bot").warning("飞书群列表获取失败: %s", str(exc)[:300])
        raise HTTPException(502, f"获取群列表失败：{str(exc)[:180]}") from exc


@router.get("/bindings")
async def bindings(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(FeishuChatBinding, Agent.name)
            .join(Agent, Agent.id == FeishuChatBinding.agent_id)
            .order_by(FeishuChatBinding.id.desc())
        )
    ).all()
    return [
        {
            "id": row[0].id,
            "chat_id": row[0].chat_id,
            "chat_name": row[0].chat_name,
            "agent_id": row[0].agent_id,
            "agent_name": row[1],
            "is_active": row[0].is_active,
        }
        for row in rows
    ]


@router.post("/bindings")
async def add_binding(payload: BindingIn, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, payload.agent_id)
    if not agent or not agent.is_active:
        raise HTTPException(422, "请选择已启用的 Agent")
    if (
        await db.execute(select(FeishuChatBinding.id).where(FeishuChatBinding.chat_id == payload.chat_id))
    ).scalar_one_or_none() is not None:
        raise HTTPException(409, "该群已绑定 Agent")
    item = FeishuChatBinding(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": item.id}


@router.delete("/bindings/{binding_id}")
async def delete_binding(binding_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(FeishuChatBinding, binding_id)
    if item is None:
        raise HTTPException(404, "群绑定不存在")
    await db.delete(item)
    await db.commit()
    return {"deleted": binding_id}
