"""
智答引擎（ZhiDa Engine）—— 管理后台 API 路由

提供仪表盘统计、模块开关、缓存管理等接口。
"""

from datetime import datetime, date, timedelta
import hashlib
import secrets
import hmac
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from loguru import logger

from app.core.config import settings
from app.core.database import get_db
from app.core.resource_manager import resource_manager
from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase, Document
from app.models.qa import QAHistory
from app.models.llm_config import LLMConfig
from app.models.miniapp import AdminLoginTicket, AdminSession, Invitation, InvitationClaim, MiniAppDailyUsage, MiniAppUser
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
)
from app.schemas.miniapp import (
    AdminTicketConfirm,
    AdminTicketOut,
    AdminTicketPollOut,
    InvitationCreate,
    InvitationCreateOut,
    InvitationOut,
)
from app.services.cache.query_cache import query_cache
from app.services.cache.rate_limiter import rate_limiter
from app.services.memory.memory_service import memory_service

router = APIRouter(prefix="/admin", tags=["管理后台"])


def _invite_code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


async def _invitation_out(db: AsyncSession, invitation: Invitation) -> InvitationOut:
    if invitation.status == "active" and invitation.expires_at and invitation.expires_at < datetime.utcnow():
        invitation.status = "expired"
    claim_result = await db.execute(
        select(InvitationClaim).where(InvitationClaim.invitation_id == invitation.id)
    )
    claim = claim_result.scalar_one_or_none()
    usage_today = 0
    if claim:
        usage_result = await db.execute(
            select(MiniAppDailyUsage.question_count).where(
                MiniAppDailyUsage.user_id == claim.user_id,
                MiniAppDailyUsage.usage_date == date.today(),
            )
        )
        usage_today = usage_result.scalar() or 0
    return InvitationOut(
        id=invitation.id,
        code_hint=invitation.code_hint,
        daily_question_limit=invitation.daily_question_limit,
        expires_at=invitation.expires_at,
        note=invitation.note,
        status=invitation.status,
        claimed_at=claim.claimed_at if claim else None,
        claimed_by_user_id=claim.user_id if claim else None,
        created_at=invitation.created_at,
        usage_today=usage_today,
    )


def _validate_miniapp_gateway(request: Request) -> str:
    secret = settings.MINIPROGRAM_GATEWAY_SECRET
    openid = request.headers.get("X-Miniapp-Openid", "").strip()
    timestamp = request.headers.get("X-Miniapp-Timestamp", "")
    signature = request.headers.get("X-Miniapp-Signature", "")
    if not secret or not openid or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="缺少小程序网关签名")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="无效的小程序网关时间戳") from exc
    if abs(time.time() - timestamp_int) > settings.MINIPROGRAM_SIGNATURE_TTL_SECONDS:
        raise HTTPException(status_code=401, detail="小程序网关签名已过期")
    expected = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.{openid}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="无效的小程序网关签名")
    return openid


# ============================================================
# 管理员小程序扫码登录
# ============================================================

@router.get("/auth/status")
async def get_admin_auth_status():
    """供网页前端判断当前部署是否需要管理员扫码登录。"""
    return {"required": settings.ADMIN_AUTH_REQUIRED}

@router.post("/auth/tickets", response_model=AdminTicketOut)
async def create_admin_login_ticket(db: AsyncSession = Depends(get_db)):
    """浏览器创建一次性二维码票据，小程序扫描后确认管理员身份。"""
    ticket_id = secrets.token_urlsafe(24)
    ticket = AdminLoginTicket(id=ticket_id, expires_at=datetime.utcnow() + timedelta(minutes=2))
    db.add(ticket)
    await db.flush()
    return AdminTicketOut(ticket_id=ticket_id, qr_payload=f"zhida-admin:{ticket_id}", expires_at=ticket.expires_at)


@router.post("/auth/confirm", response_model=AdminTicketPollOut)
async def confirm_admin_login(
    payload: AdminTicketConfirm,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """由 CloudBase 云函数调用，只有配置的管理员 OpenID 可以确认二维码。"""
    openid = _validate_miniapp_gateway(request)
    allowed_openids = {item.strip() for item in settings.ADMIN_OPENIDS.split(",") if item.strip()}
    if openid not in allowed_openids:
        raise HTTPException(status_code=403, detail="当前微信账号不是管理员")
    ticket = await db.get(AdminLoginTicket, payload.ticket_id)
    if ticket is None or ticket.status != "pending" or ticket.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="登录二维码已失效")
    ticket.status = "approved"
    ticket.approved_openid = openid
    await db.flush()
    return AdminTicketPollOut(status="approved")


@router.get("/auth/tickets/{ticket_id}", response_model=AdminTicketPollOut)
async def poll_admin_login(ticket_id: str, db: AsyncSession = Depends(get_db)):
    """浏览器轮询二维码状态；票据确认后只签发一次短期管理令牌。"""
    ticket = await db.get(AdminLoginTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="登录二维码不存在")
    if ticket.status == "pending" and ticket.expires_at < datetime.utcnow():
        ticket.status = "expired"
        await db.flush()
    if ticket.status != "approved":
        return AdminTicketPollOut(status=ticket.status)

    token = secrets.token_urlsafe(32)
    session = AdminSession(
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        openid=ticket.approved_openid,
        expires_at=datetime.utcnow() + timedelta(seconds=settings.ADMIN_SESSION_TTL_SECONDS),
    )
    db.add(session)
    ticket.status = "consumed"
    await db.flush()
    return AdminTicketPollOut(status="approved", access_token=token)


# ============================================================
# 邀请制小程序管理
# ============================================================

@router.post("/invitations", response_model=InvitationCreateOut)
async def create_invitation(request: InvitationCreate, db: AsyncSession = Depends(get_db)):
    """创建一次性邀请码。明文只在此响应返回，之后不可找回。"""
    if request.expires_at and request.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="失效时间必须晚于当前时间")

    code = secrets.token_hex(8).upper()
    invitation = Invitation(
        code_hash=_invite_code_hash(code),
        code_hint=code[-6:],
        daily_question_limit=request.daily_question_limit,
        expires_at=request.expires_at,
        note=request.note,
    )
    db.add(invitation)
    await db.flush()
    output = await _invitation_out(db, invitation)
    return InvitationCreateOut(**output.model_dump(), invite_code=code)


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invitation).order_by(Invitation.created_at.desc()))
    return [await _invitation_out(db, invitation) for invitation in result.scalars()]


@router.delete("/invitations/{invitation_id}")
async def delete_invitation(invitation_id: int, db: AsyncSession = Depends(get_db)):
    """删除未领取的邀请码；已领取的邀请码须保留记录以维持访问审计。"""
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    claim_result = await db.execute(select(InvitationClaim.id).where(InvitationClaim.invitation_id == invitation.id))
    if claim_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="邀请码已领取，不能删除；请撤销用户访问权限")
    await db.delete(invitation)
    await db.flush()
    return {"message": "邀请码已删除", "id": invitation_id}


@router.post("/invitations/{invitation_id}/revoke", response_model=InvitationOut)
async def revoke_invitation(invitation_id: int, db: AsyncSession = Depends(get_db)):
    """失效未领取的邀请码；已领取的邀请码请撤销其用户访问权限。"""
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    claim_result = await db.execute(select(InvitationClaim.id).where(InvitationClaim.invitation_id == invitation.id))
    if claim_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="邀请码已领取，请撤销对应用户访问权限")
    invitation.status = "revoked"
    await db.flush()
    return await _invitation_out(db, invitation)


@router.post("/invitations/{invitation_id}/revoke-user", response_model=InvitationOut)
async def revoke_invited_user(invitation_id: int, db: AsyncSession = Depends(get_db)):
    """撤销已领取邀请码用户的小程序访问资格。"""
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    claim_result = await db.execute(
        select(InvitationClaim).where(InvitationClaim.invitation_id == invitation.id)
    )
    claim = claim_result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=409, detail="邀请码尚未领取")
    user = await db.get(MiniAppUser, claim.user_id)
    if user:
        user.is_active = False
        user.revoked_at = datetime.utcnow()
    invitation.status = "revoked"
    await db.flush()
    return await _invitation_out(db, invitation)


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

    # 今日问答统计
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    qa_result = await db.execute(
        select(QAHistory).where(QAHistory.created_at >= today_start)
    )
    today_qas = qa_result.scalars().all()
    today_answers = len(today_qas)
    today_messages = today_answers * 2  # 估算
    # QAHistory 模型没有 confidence 字段，以有回答记录视为成功
    success_count = sum(1 for qa in today_qas if qa.answer)
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
        # 转换为 settings 中的全大写下划线格式（enable_single_flight -> ENABLE_SINGLE_FLIGHT）
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
            rerank=request.rerank,
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
