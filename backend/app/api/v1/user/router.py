"""普通用户端：获授权 Agent、历史会话和流式问答。"""

import asyncio
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.api.v1.auth.router import require_user
from app.core.database import get_db
from app.models.agent import Agent
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.models.auth import AccessCode, AccessCodeAgent, AccessCodeDailyUsage, Conversation, WebUser
from app.models.knowledge import KnowledgeBase
from app.models.qa import QAHistory
from app.services.qa.generator import answer_generator

router = APIRouter(prefix="/user", tags=["用户端"])


class UserAskIn(BaseModel):
    agent_id: int
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    response_detail: Literal["concise", "detailed"] = "concise"


async def _allowed_agent_ids(user: WebUser, db: AsyncSession) -> set[int]:
    return set((await db.execute(
        select(AccessCodeAgent.agent_id)
        .join(AccessCode, AccessCode.id == AccessCodeAgent.access_code_id)
        .where(
            AccessCode.id == user.access_code_id,
            AccessCode.status == "claimed",
            or_(AccessCode.expires_at.is_(None), AccessCode.expires_at > datetime.utcnow()),
        )
    )).scalars().all())


async def _consume_daily_quota(user: WebUser, db: AsyncSession) -> None:
    """原子消耗一次兑换码日额度，避免并发请求绕过限制。"""
    code = await db.get(AccessCode, user.access_code_id)
    if code is None or code.status != "claimed" or (code.expires_at and code.expires_at <= datetime.utcnow()):
        raise HTTPException(status_code=403, detail="访问资格已失效")
    today = datetime.utcnow().date().isoformat()
    statement = sqlite_insert(AccessCodeDailyUsage).values(
        access_code_id=code.id, usage_date=today, question_count=1,
    ).on_conflict_do_update(
        index_elements=["access_code_id", "usage_date"],
        set_={"question_count": AccessCodeDailyUsage.question_count + 1},
        where=AccessCodeDailyUsage.question_count < code.daily_question_limit,
    )
    result = await db.execute(statement)
    if result.rowcount != 1:
        raise HTTPException(status_code=429, detail="今日问答额度已用完，请明天再试")
    await db.commit()


async def _remaining_daily_quota(user: WebUser, db: AsyncSession) -> int:
    """返回当前兑换码今日剩余额度，供用户端展示。"""
    code = await db.get(AccessCode, user.access_code_id)
    if code is None or code.status != "claimed" or (code.expires_at and code.expires_at <= datetime.utcnow()):
        return 0
    usage = await db.get(AccessCodeDailyUsage, (code.id, datetime.utcnow().date().isoformat()))
    return max(code.daily_question_limit - (usage.question_count if usage else 0), 0)


async def _refund_daily_quota(user: WebUser, db: AsyncSession) -> None:
    """归还未完成流式问答的一次已预留额度，保证计数不会为负。"""
    today = datetime.utcnow().date().isoformat()
    result = await db.execute(
        update(AccessCodeDailyUsage)
        .where(
            AccessCodeDailyUsage.access_code_id == user.access_code_id,
            AccessCodeDailyUsage.usage_date == today,
            AccessCodeDailyUsage.question_count > 0,
        )
        .values(question_count=AccessCodeDailyUsage.question_count - 1)
    )
    if result.rowcount != 1:
        logger.warning(f"用户 {user.id} 的问答额度退款未命中")
    await db.commit()


def _answer_options(response_detail: str) -> dict:
    if response_detail == "detailed":
        return {"top_k": 8, "max_tokens": 4096, "temperature": 0.55}
    return {"top_k": 4, "max_tokens": 1000, "temperature": 0.5}


async def _conversation_history(db: AsyncSession, conversation_id: str | None, user_id: int) -> list[dict[str, str]]:
    if not conversation_id:
        return []
    rows = (await db.execute(
        select(QAHistory).where(
            QAHistory.conversation_id == conversation_id,
            QAHistory.owner_type == "user",
            QAHistory.owner_id == user_id,
        ).order_by(QAHistory.created_at.desc()).limit(6)
    )).scalars().all()
    history: list[dict[str, str]] = []
    for record in reversed(rows):
        history.extend([{"role": "user", "content": record.question}, {"role": "assistant", "content": record.answer or ""}])
    return history


@router.get("/agents")
async def list_agents(user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    ids = await _allowed_agent_ids(user, db)
    if not ids:
        return {"items": []}
    agents = (await db.execute(select(Agent).where(Agent.id.in_(ids), Agent.is_active == True).order_by(Agent.name))).scalars().all()  # noqa: E712
    return {"items": [{"id": agent.id, "name": agent.name, "description": agent.description, "avatar": agent.avatar} for agent in agents]}


@router.get("/me")
async def get_user_profile(user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    """用户端的轻量账户信息，不返回兑换码或其他敏感信息。"""
    return {"remaining_today": await _remaining_daily_quota(user, db)}


@router.get("/conversations")
async def list_conversations(user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    conversations = (await db.execute(select(Conversation).where(
        Conversation.owner_type == "user", Conversation.owner_id == user.id,
    ).order_by(Conversation.updated_at.desc()))).scalars().all()
    return {"items": [{"id": item.id, "agent_id": item.agent_id, "title": item.title or "未命名对话", "updated_at": item.updated_at} for item in conversations]}


@router.get("/conversations/{conversation_id}")
async def conversation_messages(conversation_id: str, user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.owner_type != "user" or conversation.owner_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    records = (await db.execute(select(QAHistory).where(QAHistory.conversation_id == conversation_id).order_by(QAHistory.created_at))).scalars().all()
    return {"conversation": {"id": conversation.id, "agent_id": conversation.agent_id, "title": conversation.title}, "items": [{"id": record.id, "question": record.question, "answer": record.answer, "sources": json.loads(record.sources or "[]"), "created_at": record.created_at} for record in records]}


@router.post("/chat/stream")
async def stream_chat(payload: UserAskIn, user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    if payload.agent_id not in await _allowed_agent_ids(user, db):
        raise HTTPException(status_code=403, detail="没有该 Agent 的访问权限")
    agent = await db.get(Agent, payload.agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent 不存在或未启用")
    conversation = await db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if conversation and (conversation.owner_type != "user" or conversation.owner_id != user.id or conversation.agent_id != agent.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")
    if conversation is None:
        conversation = Conversation(id=str(uuid.uuid4()), owner_type="user", owner_id=user.id, agent_id=agent.id, title=payload.question[:40])
        db.add(conversation)
        await db.flush()
    conversation_history = await _conversation_history(db, conversation.id, user.id)
    kb_ids = [str(item) for item in (await db.execute(
        select(KnowledgeBase.id).join(AgentKnowledgeBase, AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id)
        .where(AgentKnowledgeBase.agent_id == agent.id, KnowledgeBase.is_active == True)  # noqa: E712
    )).scalars().all()]
    # 所有权限、会话与知识库前置校验都通过后才预留额度；流式中断会在
    # events() 内退款，因此不会因校验失败让用户损失次数。
    await _consume_daily_quota(user, db)

    async def events():
        started, parts, completed = time.time(), [], None
        answer_completed = False
        def capture(result):
            nonlocal completed
            completed = result
        try:
            async for chunk in answer_generator.generate_stream(
                kb_ids, payload.question, agent_id=agent.id, user_id=f"user:{user.id}",
                on_complete=capture, conversation_history=conversation_history,
                persona_preset=agent.persona_preset, persona_custom_instruction=agent.persona_custom_instruction or "",
                response_detail=payload.response_detail,
                **_answer_options(payload.response_detail),
            ):
                parts.append(chunk)
                yield f"event: delta\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            answer_completed = True
            sources = completed.sources if completed else []
            db.add(QAHistory(agent_id=agent.id, question=payload.question, answer="".join(parts), sources=json.dumps(sources, ensure_ascii=False), total_time_ms=(time.time()-started)*1000, channel="web", chat_id=conversation.id, user_id=f"user:{user.id}", conversation_id=conversation.id, owner_type="user", owner_id=user.id, is_degraded=bool(completed and completed.degraded), web_search_count=completed.web_search_count if completed else 0))
            conversation.updated_at = datetime.utcnow()
            await db.commit()
            yield f"event: done\ndata: {json.dumps({'conversation_id': conversation.id, 'sources': sources, 'remaining_today': await _remaining_daily_quota(user, db)}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            await db.rollback()
            if not answer_completed:
                try:
                    await _refund_daily_quota(user, db)
                except Exception:
                    logger.exception("用户端流式问答取消后的额度退款失败")
            raise
        except Exception as exc:
            await db.rollback()
            if not answer_completed:
                try:
                    await _refund_daily_quota(user, db)
                except Exception:
                    logger.exception("用户端流式问答失败后的额度退款失败")
            logger.exception("用户端流式问答失败")
            yield f"event: error\ndata: {json.dumps({'detail': '回答生成失败，请稍后重试'}, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
