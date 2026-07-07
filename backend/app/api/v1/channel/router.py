"""
智答引擎（ZhiDa Engine）—— 渠道配置 API 路由

提供渠道的 CRUD、监听控制、统计等接口。
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.channel import ChannelConfig
from app.schemas.channel import (
    ChannelConfigCreate,
    ChannelConfigUpdate,
    ChannelConfigOut,
    ChannelConfigListOut,
    ChannelStatsOut,
)

router = APIRouter(prefix="/channels", tags=["渠道管理"])


# ============================================================
# 辅助函数
# ============================================================

def _channel_to_out(channel: ChannelConfig) -> ChannelConfigOut:
    """将数据库模型转为输出 Schema"""
    return ChannelConfigOut(
        id=channel.id,
        agent_id=channel.agent_id,
        channel_type=channel.channel_type,
        chat_id=channel.chat_id,
        chat_name=channel.chat_name,
        is_listening=channel.is_listening,
        listen_mode=channel.listen_mode,
        enable_learning=channel.enable_learning,
        target_users=channel.target_users,
        auto_reply=channel.auto_reply,
        reply_with_source=channel.reply_with_source,
        auto_mention_on_fail=channel.auto_mention_on_fail,
        mention_user_ids=channel.mention_user_ids,
        is_active=channel.is_active,
        last_message_at=channel.last_message_at,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
    )


# ============================================================
# 渠道 CRUD
# ============================================================

@router.get("", response_model=ChannelConfigListOut)
async def list_channels(
    agent_id: Optional[int] = Query(None, description="Agent ID 过滤"),
    db: AsyncSession = Depends(get_db),
):
    """获取渠道配置列表"""
    query = select(ChannelConfig).order_by(ChannelConfig.created_at.desc())
    if agent_id is not None:
        query = query.where(ChannelConfig.agent_id == agent_id)

    result = await db.execute(query)
    channels = result.scalars().all()

    return ChannelConfigListOut(
        total=len(channels),
        items=[_channel_to_out(c) for c in channels],
    )


@router.post("", response_model=ChannelConfigOut)
async def create_channel(
    request: ChannelConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    添加监听渠道

    添加微信群/QQ群/联系人的监听配置。
    创建后默认为停止状态，需要手动启动监听。
    """
    channel = ChannelConfig(
        agent_id=request.agent_id,
        channel_type=request.channel_type,
        chat_id=request.chat_id,
        chat_name=request.chat_name or "",
        listen_mode=request.listen_mode,
        enable_learning=request.enable_learning,
        target_users=request.target_users,
        auto_reply=request.auto_reply,
        reply_with_source=request.reply_with_source,
        auto_mention_on_fail=request.auto_mention_on_fail,
        mention_user_ids=request.mention_user_ids,
        is_listening=False,
    )
    db.add(channel)
    await db.flush()
    await db.refresh(channel)

    return _channel_to_out(channel)


@router.put("/{channel_id}", response_model=ChannelConfigOut)
async def update_channel(
    channel_id: int,
    request: ChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新渠道配置"""
    result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="渠道配置不存在")

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(channel, key, value)

    await db.flush()
    await db.refresh(channel)

    return _channel_to_out(channel)


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除渠道配置"""
    result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="渠道配置不存在")

    await db.delete(channel)
    await db.flush()

    return {"message": "删除成功", "id": channel_id}


# ============================================================
# 监听控制
# ============================================================

@router.post("/{channel_id}/start-listening")
async def start_listening(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """开始监听此渠道"""
    result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="渠道配置不存在")

    channel.is_listening = True
    await db.flush()

    return {
        "message": f"已开始监听 {channel.chat_name or channel.chat_id}",
        "channel_id": channel_id,
        "is_listening": True,
    }


@router.post("/{channel_id}/stop-listening")
async def stop_listening(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """停止监听此渠道"""
    result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="渠道配置不存在")

    channel.is_listening = False
    await db.flush()

    return {
        "message": f"已停止监听 {channel.chat_name or channel.chat_id}",
        "channel_id": channel_id,
        "is_listening": False,
    }


# ============================================================
# 渠道统计
# ============================================================

@router.get("/{channel_id}/stats", response_model=ChannelStatsOut)
async def get_channel_stats(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取渠道统计"""
    result = await db.execute(
        select(ChannelConfig).where(ChannelConfig.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="渠道配置不存在")

    return ChannelStatsOut(
        channel_id=channel.id,
        chat_name=channel.chat_name or channel.chat_id,
        channel_type=channel.channel_type,
        is_listening=channel.is_listening,
        today_messages=0,
        today_answers=0,
        today_learned=0,
        last_message_at=channel.last_message_at,
    )


# ============================================================
# 扫码登录
# ============================================================

@router.post("/{channel_type}/login/qrcode")
async def generate_login_qrcode(
    channel_type: str,
):
    """
    生成登录二维码

    支持渠道: qq / wechat

    返回二维码内容和登录会话ID，前端使用二维码内容生成二维码图片。
    然后轮询 /login/status/{login_id} 检查登录状态。
    """
    from app.services.channel.base import adapter_factory

    adapter = adapter_factory.create(channel_type)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")

    result = await adapter.generate_qrcode()
    if not result:
        raise HTTPException(status_code=500, detail="生成二维码失败")

    return result


@router.get("/{channel_type}/login/status/{login_id}")
async def check_login_status(
    channel_type: str,
    login_id: str,
):
    """
    查询登录状态

    状态说明:
    - waiting: 等待扫码
    - scanned: 已扫码，等待确认
    - confirmed: 已确认登录
    - success: 登录成功（返回用户信息）
    - expired: 二维码已过期
    """
    from app.services.channel.base import adapter_factory

    adapter = adapter_factory.create(channel_type)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")

    result = await adapter.check_login_status(login_id)
    return result


# ============================================================
# 联系人列表
# ============================================================

@router.get("/{channel_type}/contacts")
async def get_contact_list(
    channel_type: str,
):
    """
    获取联系人列表（群聊 + 好友）

    需要先通过扫码登录渠道账号。
    """
    from app.services.channel.base import adapter_factory

    adapter = adapter_factory.create(channel_type)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")

    result = await adapter.get_contact_list()
    return result


@router.get("/{channel_type}/groups/{group_id}/members")
async def get_group_members(
    channel_type: str,
    group_id: str,
):
    """
    获取群成员列表

    需要先通过扫码登录渠道账号。
    """
    from app.services.channel.base import adapter_factory

    adapter = adapter_factory.create(channel_type)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"不支持的渠道类型: {channel_type}")

    members = await adapter.get_group_member_list(group_id)
    return {
        "total": len(members),
        "members": members,
    }


# ============================================================
# 支持的渠道列表
# ============================================================

@router.get("/supported/list")
async def get_supported_channels():
    """获取支持的渠道类型列表"""
    from app.services.channel.base import adapter_factory

    channels = adapter_factory.get_supported_channels()
    channel_info = []
    for ch in channels:
        adapter = adapter_factory.create(ch)
        info = await adapter.get_channel_info() if adapter else {}
        channel_info.append({
            "type": ch,
            "name": adapter.channel_name if adapter else ch,
            **info,
        })

    return {
        "total": len(channel_info),
        "items": channel_info,
    }