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
from app.core.config import settings
from app.core.time import as_beijing, beijing_today
from app.models.agent import Agent
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.models.auth import AccessCode, AccessCodeAgent, AccessCodeDailyUsage, Conversation, WebUser
from app.models.knowledge import KnowledgeBase
from app.models.qa import QAHistory
from app.services.qa.generator import AnswerLengthLimitError, answer_generator
from app.services.qa.concurrency import qa_stream_concurrency, per_user_stream_guard
from app.services.cache.rate_limiter import rate_limiter, RateLimitResult

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
    today = beijing_today().isoformat()
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
    usage = await db.get(AccessCodeDailyUsage, (code.id, beijing_today().isoformat()))
    return max(code.daily_question_limit - (usage.question_count if usage else 0), 0)


async def _refund_daily_quota(user: WebUser, db: AsyncSession) -> None:
    """归还未完成流式问答的一次已预留额度，保证计数不会为负。"""
    today = beijing_today().isoformat()
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


def _answer_options(response_detail: str, agent: Agent) -> dict:
    if response_detail == "detailed":
        # 与管理端保持一致：推理型主模型需要给详细模式预留正文 token。
        return {"top_k": agent.detailed_top_k or 8, "rewrite_count": agent.detailed_rewrite_count if agent.detailed_rewrite_count is not None else 3, "max_tokens": 8192, "temperature": 0.55}
    return {"top_k": agent.concise_top_k or 4, "rewrite_count": agent.concise_rewrite_count if agent.concise_rewrite_count is not None else 3, "max_tokens": 4096, "temperature": 0.5}


async def _unsummarized_records(db: AsyncSession, conversation: Conversation, user_id: int) -> list[QAHistory]:
    """只读取尚未进入摘要的本用户记录，摘要游标防止同一内容被重复压缩。"""
    return list((await db.execute(
        select(QAHistory).where(
            QAHistory.conversation_id == conversation.id,
            QAHistory.owner_type == "user",
            QAHistory.owner_id == user_id,
            QAHistory.id > (conversation.summarized_through_history_id or 0),
        ).order_by(QAHistory.id.asc())
    )).scalars().all())


def _records_to_history(records: list[QAHistory], summary: str = "") -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    if summary:
        history.append({"role": "summary", "content": summary})
    for record in records:
        history.extend([
            {"role": "user", "content": record.question},
            {"role": "assistant", "content": record.answer or ""},
        ])
    return history


def _context_usage_ratio(
    *, conversation: Conversation, records: list[QAHistory], question: str,
    context_window_k: int, output_reserve: int = 12000,
) -> float:
    """预估完整请求占用；额外预留 RAG、记忆和系统提示，避免到模型端才溢出。"""
    historical = (conversation.context_summary or "") + "\n" + "\n".join(
        f"{record.question}\n{record.answer or ''}" for record in records
    )
    input_tokens = answer_generator.estimate_tokens(historical + "\n" + question)
    anticipated_retrieval_and_rules = 8000
    return (input_tokens + anticipated_retrieval_and_rules + output_reserve) / max(context_window_k * 1000, 1)


def _context_policy(usage_ratio: float, record_count: int) -> tuple[bool, int]:
    """返回（是否压缩、保留最近原文轮数）；阈值是系统固定策略。"""
    should_compact = usage_ratio >= 0.95 and record_count > 4
    raw_limit = 4 if usage_ratio >= 0.80 else 6 if usage_ratio >= 0.60 else 12
    return should_compact, raw_limit


def _trim_records_to_budget(
    *, conversation: Conversation, records: list[QAHistory], question: str,
    context_window_k: int, max_records: int, target_ratio: float = 0.55,
    output_reserve: int = 12000,
) -> list[QAHistory]:
    """从最新轮次向前保留完整问答，把裁剪后的请求压回安全水位。"""
    candidates = records[-max_records:]
    if not candidates:
        return []
    fixed_tokens = answer_generator.estimate_tokens(
        (conversation.context_summary or "") + "\n" + question
    ) + 8000 + output_reserve
    remaining = max(int(context_window_k * 1000 * target_ratio) - fixed_tokens, 0)
    selected: list[QAHistory] = []
    for record in reversed(candidates):
        record_tokens = answer_generator.estimate_tokens(
            f"{record.question}\n{record.answer or ''}"
        )
        # 至少保留最新一轮；超长单轮仍受回答输出上限和 Prompt 预留保护。
        if not selected or record_tokens <= remaining:
            selected.append(record)
            remaining = max(remaining - record_tokens, 0)
    selected.reverse()
    return selected


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
    return {"remaining_today": await _remaining_daily_quota(user, db), "development_mode": settings.DEVELOPMENT_MODE}


@router.get("/conversations")
async def list_conversations(user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    conversations = (await db.execute(select(Conversation).where(
        Conversation.owner_type == "user", Conversation.owner_id == user.id,
    ).order_by(Conversation.updated_at.desc()))).scalars().all()
    return {"items": [{"id": item.id, "agent_id": item.agent_id, "title": item.title or "未命名对话", "updated_at": as_beijing(item.updated_at)} for item in conversations]}


@router.get("/conversations/{conversation_id}")
async def conversation_messages(conversation_id: str, user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.owner_type != "user" or conversation.owner_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    records = (await db.execute(select(QAHistory).where(QAHistory.conversation_id == conversation_id).order_by(QAHistory.created_at))).scalars().all()
    return {"conversation": {"id": conversation.id, "agent_id": conversation.agent_id, "title": conversation.title}, "items": [{"id": record.id, "question": record.question, "answer": record.answer, "sources": json.loads(record.sources or "[]"), "created_at": as_beijing(record.created_at)} for record in records]}


@router.post("/chat/stream")
async def stream_chat(payload: UserAskIn, user: WebUser = Depends(require_user), db: AsyncSession = Depends(get_db)):
    if settings.DEVELOPMENT_MODE:
        raise HTTPException(status_code=503, detail="系统正在开发维护中，暂时无法发起问答，请稍后再试")
    if payload.agent_id not in await _allowed_agent_ids(user, db):
        raise HTTPException(status_code=403, detail="没有该 Agent 的访问权限")
    agent = await db.get(Agent, payload.agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent 不存在或未启用")
    # 用户已认证后按身份限速，而不是让共享公网 IP 的多个用户共用一个桶。
    if rate_limiter.check(f"user:{user.id}", "", is_private=True) == RateLimitResult.RATE_LIMITED:
        raise HTTPException(status_code=429, detail="提问过于频繁，请稍后再试")
    conversation = await db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if conversation and (conversation.owner_type != "user" or conversation.owner_id != user.id or conversation.agent_id != agent.id):
        raise HTTPException(status_code=403, detail="无权访问该会话")
    kb_ids = [str(item) for item in (await db.execute(
        select(KnowledgeBase.id).join(AgentKnowledgeBase, AgentKnowledgeBase.knowledge_base_id == KnowledgeBase.id)
        .where(AgentKnowledgeBase.agent_id == agent.id, KnowledgeBase.is_active == True)  # noqa: E712
    )).scalars().all()]
    async def events():
        nonlocal conversation
        if not await per_user_stream_guard.acquire(user.id):
            yield f"event: error\ndata: {json.dumps({'detail': '当前会话仍在生成，请等待完成后再提问'}, ensure_ascii=False)}\n\n"
            return
        started, parts, completed = time.time(), [], None
        answer_completed = False
        quota_consumed = False
        try:
            admission = await qa_stream_concurrency.acquire()
        except BaseException:
            await per_user_stream_guard.release(user.id)
            raise
        if not admission.acquired:
            detail = "当前排队已满，请稍后重试" if admission.queue_full else "当前问答较多，请稍后重试"
            yield f"event: error\ndata: {json.dumps({'detail': detail}, ensure_ascii=False)}\n\n"
            await per_user_stream_guard.release(user.id)
            return
        if admission.queued:
            yield f"event: status\ndata: {json.dumps({'detail': '正在排队处理'}, ensure_ascii=False)}\n\n"
        def capture(result):
            nonlocal completed
            completed = result
        try:
            # 入队期间不持有 SQLite 写事务，也不预扣用户额度。
            if conversation is None:
                conversation = Conversation(id=str(uuid.uuid4()), owner_type="user", owner_id=user.id, agent_id=agent.id, title=payload.question[:40])
                db.add(conversation)
                await db.flush()
            records = await _unsummarized_records(db, conversation, user.id)
            usage_ratio = _context_usage_ratio(
                conversation=conversation, records=records, question=payload.question,
                context_window_k=agent.context_window_k or 64,
            )
            should_compact, raw_limit = _context_policy(usage_ratio, len(records))
            if should_compact:
                compressible = records[:-4]
                yield f"event: status\ndata: {json.dumps({'detail': '正在整理此前对话…', 'stage': 'compacting'}, ensure_ascii=False)}\n\n"
                try:
                    new_summary = await answer_generator.compact_conversation(
                        conversation.context_summary or "",
                        _records_to_history(compressible), agent.id,
                    )
                except Exception as exc:
                    # 模型调用失败没有改动数据库事务，不 rollback，避免 ORM 对象过期。
                    logger.warning(f"会话压缩失败，使用强裁剪继续回答: {type(exc).__name__}")
                    records = records[-4:]
                else:
                    conversation.context_summary = new_summary
                    conversation.summarized_through_history_id = compressible[-1].id
                    conversation.summary_updated_at = datetime.utcnow()
                    try:
                        await db.commit()
                    except Exception as exc:
                        await db.rollback()
                        logger.error(f"会话摘要保存失败: {type(exc).__name__}")
                        raise RuntimeError("会话状态保存失败") from None
                    records = records[-4:]
                    usage_ratio = _context_usage_ratio(
                        conversation=conversation, records=records, question=payload.question,
                        context_window_k=agent.context_window_k or 64,
                    )
            # 固定比例策略：60% 开始保留最近 6 轮，80% 起只保留最近 4 轮。
            _, raw_limit = _context_policy(usage_ratio, len(records))
            if usage_ratio >= 0.60:
                records = _trim_records_to_budget(
                    conversation=conversation,
                    records=records,
                    question=payload.question,
                    context_window_k=agent.context_window_k or 64,
                    max_records=raw_limit,
                )
            else:
                records = records[-raw_limit:]
            usage_ratio = _context_usage_ratio(
                conversation=conversation, records=records, question=payload.question,
                context_window_k=agent.context_window_k or 64,
            )
            conversation_history = _records_to_history(records, conversation.context_summary or "")
            await _consume_daily_quota(user, db)
            quota_consumed = True
            async for chunk in answer_generator.generate_stream(
                kb_ids, payload.question, agent_id=agent.id, user_id=f"user:{user.id}",
                on_complete=capture, conversation_history=conversation_history,
                persona_preset=agent.persona_preset, persona_custom_instruction=agent.persona_custom_instruction or "",
                response_detail=payload.response_detail,
                context_pressure=usage_ratio,
                **_answer_options(payload.response_detail, agent),
            ):
                parts.append(chunk)
                yield f"event: delta\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            answer_completed = True
            sources = completed.sources if completed else []
            db.add(QAHistory(agent_id=agent.id, question=payload.question, answer="".join(parts), sources=json.dumps(sources, ensure_ascii=False), total_time_ms=(time.time()-started)*1000, channel="web", chat_id=conversation.id, user_id=f"user:{user.id}", conversation_id=conversation.id, owner_type="user", owner_id=user.id, input_tokens=completed.input_tokens if completed else 0, cached_input_tokens=completed.cached_input_tokens if completed else 0, output_tokens=completed.output_tokens if completed else 0, is_degraded=bool(completed and completed.degraded), web_search_count=completed.web_search_count if completed else 0))
            conversation.updated_at = datetime.utcnow()
            await db.commit()
            yield f"event: done\ndata: {json.dumps({'conversation_id': conversation.id, 'sources': sources, 'remaining_today': await _remaining_daily_quota(user, db)}, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            await db.rollback()
            if quota_consumed and not answer_completed:
                try:
                    await _refund_daily_quota(user, db)
                except Exception:
                    logger.exception("用户端流式问答取消后的额度退款失败")
            raise
        except AnswerLengthLimitError as exc:
            await db.rollback()
            if quota_consumed and not answer_completed:
                try:
                    await _refund_daily_quota(user, db)
                except Exception:
                    logger.exception("用户端长度上限问答退款失败")
            logger.warning("用户端流式问答超过输出长度上限")
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            await db.rollback()
            if quota_consumed and not answer_completed:
                try:
                    await _refund_daily_quota(user, db)
                except Exception:
                    logger.exception("用户端流式问答失败后的额度退款失败")
            logger.exception("用户端流式问答失败")
            yield f"event: error\ndata: {json.dumps({'detail': '回答生成失败，请稍后重试'}, ensure_ascii=False)}\n\n"
        finally:
            await qa_stream_concurrency.release()
            await per_user_stream_guard.release(user.id)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
