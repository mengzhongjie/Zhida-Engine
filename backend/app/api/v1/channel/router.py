"""QQ 官方机器人管理接口。"""
import re
from pydantic import BaseModel, Field, field_validator
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import decrypt_api_key, encrypt_api_key, mask_api_key
from app.models.agent import Agent
from app.models.qq_bot import QQBotConfig, QQBotGroupBinding

router = APIRouter(prefix="/qq-bot", tags=["QQ 机器人"])
_OPEN_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

class ConfigIn(BaseModel):
    enabled: bool = False
    app_id: str = Field(default="", max_length=100)
    app_secret: str | None = Field(default=None, max_length=500)

class BindingIn(BaseModel):
    group_openid: str = Field(min_length=1, max_length=128)
    agent_id: int = Field(gt=0)
    is_active: bool = True
    @field_validator("group_openid")
    @classmethod
    def valid_openid(cls, value: str):
        value = value.strip()
        if not _OPEN_ID.fullmatch(value): raise ValueError("群 OpenID 格式不合法")
        return value

async def _config(db):
    item = await db.get(QQBotConfig, 1)
    if item is None:
        item = QQBotConfig(id=1); db.add(item); await db.flush()
    return item

def _out(item):
    return {"enabled": item.enabled, "app_id": item.app_id, "app_secret": mask_api_key(decrypt_api_key(item.app_secret)), "last_test_success": item.last_test_success, "last_error": item.last_error}

@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)): return _out(await _config(db))

@router.put("/config")
async def save_config(payload: ConfigIn, db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    if payload.enabled and (not payload.app_id.strip() or not (payload.app_secret or item.app_secret)):
        raise HTTPException(422, "启用前请填写 AppID 与 AppSecret")
    item.enabled, item.app_id = payload.enabled, payload.app_id.strip()
    if payload.app_secret: item.app_secret = encrypt_api_key(payload.app_secret.strip())
    await db.commit()
    from app.services.channel.qq_bot import qq_bot_service
    await qq_bot_service.reload()
    return _out(item)

@router.post("/config/test")
async def test_config(db: AsyncSession = Depends(get_db)):
    item = await _config(db)
    if not item.app_id or not item.app_secret: raise HTTPException(422, "请先填写 AppID 与 AppSecret")
    from app.services.channel.qq_bot import qq_bot_service
    ok, detail = await qq_bot_service.test_credentials(item.app_id, decrypt_api_key(item.app_secret))
    item.last_test_success, item.last_error = ok, None if ok else detail
    await db.commit(); return {"success": ok, "message": "QQ 官方机器人凭据可用" if ok else detail}

@router.get("/bindings")
async def bindings(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(QQBotGroupBinding, Agent.name).join(Agent, Agent.id == QQBotGroupBinding.agent_id).order_by(QQBotGroupBinding.id.desc()))).all()
    return [{"id": row[0].id, "group_openid": row[0].group_openid, "agent_id": row[0].agent_id, "agent_name": row[1], "is_active": row[0].is_active} for row in rows]

@router.post("/bindings")
async def add_binding(payload: BindingIn, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, payload.agent_id)
    if not agent or not agent.is_active: raise HTTPException(422, "请选择已启用的 Agent")
    if (await db.execute(select(QQBotGroupBinding.id).where(QQBotGroupBinding.group_openid == payload.group_openid))).scalar_one_or_none() is not None: raise HTTPException(409, "该群已绑定 Agent")
    item = QQBotGroupBinding(**payload.model_dump()); db.add(item); await db.commit(); await db.refresh(item)
    return {"id": item.id}

@router.delete("/bindings/{binding_id}")
async def delete_binding(binding_id: int, db: AsyncSession = Depends(get_db)):
    item = await db.get(QQBotGroupBinding, binding_id)
    if item is None: raise HTTPException(404, "群绑定不存在")
    await db.delete(item); await db.commit(); return {"deleted": binding_id}
