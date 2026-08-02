"""CloudBase 云函数专用的小程序 API。

这些接口不接受客户端声明的 user_id；云函数使用共享密钥签名 OpenID 后再转发。
"""

import hashlib
import hmac
import ast
import json
import secrets
import time
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.models.miniapp import Invitation, InvitationClaim, InvitationDailyUsage, MiniAppSession, MiniAppUser
from app.models.qa import QAHistory
from app.schemas.miniapp import (
    InviteClaimRequest,
    MiniAppAgentOut,
    MiniAppAskRequest,
    MiniAppSessionCreate,
    MiniAppSessionOut,
    MiniAppUserOut,
)
from app.services.qa.generator import answer_generator

router = APIRouter(prefix="/miniapp", tags=["小程序"])


def _decode_sources(value: Optional[str]) -> list[dict]:
    """兼容新 JSON 数据和旧版本写入的 Python 字面量字符串。"""
    if not value:
        return []
    for loader in (json.loads, ast.literal_eval):
        try:
            parsed = loader(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError, SyntaxError, json.JSONDecodeError):
            continue
    return []


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def _validate_gateway_signature(request: Request) -> str:
    """验证 CloudBase 网关签名；仅 DEBUG 模式允许固定测试 OpenID 直连。"""
    dev_openid = request.headers.get("X-Miniapp-Dev-Openid", "").strip()
    if settings.DEBUG and settings.MINIPROGRAM_DEV_OPENID and hmac.compare_digest(
        dev_openid, settings.MINIPROGRAM_DEV_OPENID
    ):
        return dev_openid

    secret = settings.MINIPROGRAM_GATEWAY_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="小程序网关未配置")

    openid = request.headers.get("X-Miniapp-Openid", "").strip()
    timestamp = request.headers.get("X-Miniapp-Timestamp", "")
    signature = request.headers.get("X-Miniapp-Signature", "")
    if not openid or not timestamp or not signature:
        raise HTTPException(status_code=401, detail="缺少小程序网关签名")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="无效的小程序网关时间戳") from exc
    if abs(time.time() - timestamp_int) > settings.MINIPROGRAM_SIGNATURE_TTL_SECONDS:
        raise HTTPException(status_code=401, detail="小程序网关签名已过期")
    payload = f"{timestamp}.{openid}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="无效的小程序网关签名")
    return openid


async def _get_signed_openid(request: Request) -> str:
    return _validate_gateway_signature(request)


async def _get_user_or_reject(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MiniAppUser:
    openid = _validate_gateway_signature(request)
    result = await db.execute(select(MiniAppUser).where(MiniAppUser.openid == openid))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=403, detail="请先使用邀请码激活")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="邀请资格已被撤销")
    if not await _active_claims(db, user.id):
        raise HTTPException(status_code=403, detail="没有可用的邀请码额度")
    return user


async def _active_claims(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(InvitationClaim, Invitation)
        .join(Invitation, Invitation.id == InvitationClaim.invitation_id)
        .where(
            InvitationClaim.user_id == user_id,
            InvitationClaim.is_active == True,  # noqa: E712
            Invitation.status == "claimed",
        )
        .order_by(Invitation.daily_question_limit.asc(), InvitationClaim.claimed_at.asc())
    )
    return result.all()


async def _claim_usage(db: AsyncSession, claim_id: int):
    return (await db.execute(
        select(InvitationDailyUsage).where(
            InvitationDailyUsage.claim_id == claim_id,
            InvitationDailyUsage.usage_date == date.today(),
        )
    )).scalar_one_or_none()


async def _consume_invitation_quota(db: AsyncSession, claim_id: int, daily_limit: int) -> bool:
    """原子消耗单张邀请码额度，避免并发请求超额。"""
    today = date.today()
    await db.execute(
        text(
            "INSERT OR IGNORE INTO invitation_daily_usage "
            "(claim_id, usage_date, question_count) VALUES (:claim_id, :usage_date, 0)"
        ),
        {"claim_id": claim_id, "usage_date": today},
    )
    result = await db.execute(
        text(
            "UPDATE invitation_daily_usage SET question_count = question_count + 1 "
            "WHERE claim_id = :claim_id AND usage_date = :usage_date "
            "AND question_count < :daily_limit"
        ),
        {"claim_id": claim_id, "usage_date": today, "daily_limit": daily_limit},
    )
    return result.rowcount == 1


async def _user_out(db: AsyncSession, user: MiniAppUser) -> MiniAppUserOut:
    limits, used = 0, 0
    for claim, invitation in await _active_claims(db, user.id):
        limits += invitation.daily_question_limit
        usage = await _claim_usage(db, claim.id)
        used += usage.question_count if usage else 0
    return MiniAppUserOut(
        id=user.id,
        daily_question_limit=limits,
        usage_today=used,
        remaining_today=max(limits - used, 0),
    )


async def _get_public_agent(db: AsyncSession, agent_id: int) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.is_active == True,  # noqa: E712
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在或未启用")
    return agent


@router.post("/invite/claim", response_model=MiniAppUserOut)
async def claim_invitation(
    payload: InviteClaimRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """领取一次性邀请码；同一用户可领取多张码，每张码独立计算额度。"""
    openid = _validate_gateway_signature(request)
    user_result = await db.execute(select(MiniAppUser).where(MiniAppUser.openid == openid))
    existing_user = user_result.scalar_one_or_none()
    code = payload.invite_code.strip().upper()
    invite_result = await db.execute(select(Invitation).where(Invitation.code_hash == _code_hash(code)))
    invitation = invite_result.scalar_one_or_none()
    if invitation is None:
        raise HTTPException(status_code=400, detail="邀请码无效")
    if invitation.status != "active":
        raise HTTPException(status_code=400, detail="邀请码已失效或已被领取")
    claim_result = await db.execute(select(InvitationClaim).where(InvitationClaim.invitation_id == invitation.id))
    if claim_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="邀请码已失效或已被领取")
    if invitation.expires_at and invitation.expires_at < datetime.utcnow():
        invitation.status = "expired"
        await db.flush()
        raise HTTPException(status_code=400, detail="邀请码已过期")

    user = existing_user or MiniAppUser(openid=openid)
    if existing_user is None:
        db.add(user)
        await db.flush()

    user.is_active = True
    user.revoked_at = None
    db.add(InvitationClaim(invitation_id=invitation.id, user_id=user.id))
    invitation.claimed_at = datetime.utcnow()
    invitation.status = "claimed"
    await db.flush()
    return await _user_out(db, user)


@router.get("/me", response_model=MiniAppUserOut)
async def get_me(user: MiniAppUser = Depends(_get_user_or_reject), db: AsyncSession = Depends(get_db)):
    return await _user_out(db, user)


@router.get("/agents", response_model=list[MiniAppAgentOut])
async def list_public_agents(
    user: MiniAppUser = Depends(_get_user_or_reject),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Agent).where(Agent.is_active == True).order_by(Agent.created_at.desc())  # noqa: E712
    )
    return [MiniAppAgentOut(id=a.id, name=a.name, description=a.description, avatar=a.avatar) for a in result.scalars()]


@router.post("/sessions", response_model=MiniAppSessionOut)
async def create_session(
    payload: MiniAppSessionCreate,
    user: MiniAppUser = Depends(_get_user_or_reject),
    db: AsyncSession = Depends(get_db),
):
    await _get_public_agent(db, payload.agent_id)
    session = MiniAppSession(id=str(uuid.uuid4()), user_id=user.id, agent_id=payload.agent_id, title=payload.title)
    db.add(session)
    await db.flush()
    return MiniAppSessionOut.model_validate(session)


@router.get("/sessions", response_model=list[MiniAppSessionOut])
async def list_sessions(user: MiniAppUser = Depends(_get_user_or_reject), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MiniAppSession).where(MiniAppSession.user_id == user.id, MiniAppSession.is_active == True)  # noqa: E712
        .order_by(MiniAppSession.updated_at.desc())
    )
    return [MiniAppSessionOut.model_validate(item) for item in result.scalars()]


@router.get("/sessions/{session_id}/messages")
async def list_session_messages(
    session_id: str,
    user: MiniAppUser = Depends(_get_user_or_reject),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(MiniAppSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    result = await db.execute(
        select(QAHistory).where(
            QAHistory.channel == "miniprogram",
            QAHistory.chat_id == session_id,
            QAHistory.user_id == user.openid,
        ).order_by(QAHistory.created_at.asc())
    )
    return [
        {
            "id": item.id,
            "question": item.question,
            "answer": item.answer,
            "sources": _decode_sources(item.sources),
            "created_at": item.created_at,
        }
        for item in result.scalars()
    ]


@router.post("/ask")
async def ask(
    payload: MiniAppAskRequest,
    user: MiniAppUser = Depends(_get_user_or_reject),
    db: AsyncSession = Depends(get_db),
):
    await _get_public_agent(db, payload.agent_id)
    session_id = payload.session_id
    if session_id:
        session = await db.get(MiniAppSession, session_id)
        if session is None or session.user_id != user.id or session.agent_id != payload.agent_id:
            raise HTTPException(status_code=404, detail="会话不存在")
    else:
        session = MiniAppSession(
            id=str(uuid.uuid4()), user_id=user.id, agent_id=payload.agent_id, title=payload.question[:40]
        )
        db.add(session)
        await db.flush()
        session_id = session.id

    quota_consumed = False
    for claim, invitation in await _active_claims(db, user.id):
        if await _consume_invitation_quota(db, claim.id, invitation.daily_question_limit):
            quota_consumed = True
            break
    if not quota_consumed:
        raise HTTPException(status_code=429, detail="今日问答次数已用完")

    kb_result = await db.execute(
        select(KnowledgeBase.id).join(AgentKnowledgeBase, AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id).where(AgentKnowledgeBase.agent_id == payload.agent_id, KnowledgeBase.is_active == True)  # noqa: E712
    )
    knowledge_base_ids = [str(kb_id) for kb_id in kb_result.scalars()]
    # 允许无知识库问答（RAG 降级策略：reply_mode=auto/hybrid 时 LLM 自行回答）

    # 查询 Agent 回复模式（用于 RAG 无结果降级策略）
    agent_result = await db.execute(select(Agent.reply_mode).where(Agent.id == payload.agent_id))
    agent_mode = agent_result.scalar_one_or_none() or "auto"

    # 在真正调用模型前原子落库计数，确保并发请求不会突破邀请码额度。
    await db.flush()
    recent_result = await db.execute(
        select(QAHistory).where(
            QAHistory.channel == "miniprogram",
            QAHistory.chat_id == session_id,
            QAHistory.user_id == user.openid,
        ).order_by(QAHistory.created_at.desc()).limit(6)
    )
    recent_history = list(reversed(recent_result.scalars().all()))
    conversation_history = [
        {"role": role, "content": content}
        for item in recent_history
        for role, content in (("user", item.question), ("assistant", item.answer or ""))
    ]
    answer = await answer_generator.generate(
        knowledge_base_ids=knowledge_base_ids,
        question=payload.question,
        user_id=user.openid,
        agent_id=payload.agent_id,
        reply_mode=agent_mode,
        conversation_history=conversation_history,
    )
    session.updated_at = datetime.utcnow()
    history = QAHistory(
        agent_id=payload.agent_id,
        question=payload.question,
        answer=answer.answer,
        sources=json.dumps(answer.sources, ensure_ascii=False),
        total_time_ms=answer.retrieval_time_ms + answer.generation_time_ms,
        channel="miniprogram",
        chat_id=session_id,
        user_id=user.openid,
        is_cache_hit=answer.is_cache_hit,
        input_tokens=answer.input_tokens,
        output_tokens=answer.output_tokens,
        is_degraded=answer.degraded,
        web_search_count=answer.web_search_count,
    )
    db.add(history)
    await db.flush()
    return {
        "session_id": session_id,
        "question": payload.question,
        "answer": answer.answer,
        "sources": answer.sources,
        "from_cache": answer.is_cache_hit,
        "remaining_today": (await _user_out(db, user)).remaining_today,
    }
