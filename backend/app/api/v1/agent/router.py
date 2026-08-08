"""
智答引擎（ZhiDa Engine）—— Agent API 路由

提供 Agent 的 CRUD、启动/停止、统计等接口。
Agent 启动/停止时自动管理沙箱生命周期。
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from loguru import logger

from app.core.database import get_db
from app.core.config import settings
from app.core.time import as_beijing, beijing_today, utc_day_start
from app.core.sandbox import sandbox_manager
from app.models.agent import Agent
from app.models.agent_knowledge_base import AgentKnowledgeBase
from app.models.qa import QAHistory
from app.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentOut,
    AgentListOut,
    AgentStatsOut,
)

router = APIRouter(prefix="/agents", tags=["Agent 管理"])


# ============================================================
# 辅助函数
# ============================================================

def _agent_to_out(agent: Agent) -> AgentOut:
    """将数据库模型转为输出 Schema"""
    return AgentOut(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        avatar=agent.avatar,
        is_active=agent.is_active,
        status=agent.status,
        persona_preset=agent.persona_preset or "professional",
        persona_custom_instruction=agent.persona_custom_instruction,
        context_window_k=agent.context_window_k or 64,
        created_at=as_beijing(agent.created_at),
        updated_at=as_beijing(agent.updated_at),
    )


# ============================================================
# Agent CRUD
# ============================================================

@router.get("", response_model=AgentListOut)
async def list_agents(
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有 Agent 列表

    返回每个 Agent 的基本信息和问答统计摘要。
    """
    result = await db.execute(
        select(Agent).order_by(Agent.created_at.desc())
    )
    agents = result.scalars().all()

    items = []
    for agent in agents:
        out = _agent_to_out(agent)

        # 今日统计
        today_start = utc_day_start(beijing_today())
        qa_result = await db.execute(
            select(QAHistory).where(
                QAHistory.agent_id == agent.id,
                QAHistory.created_at >= today_start,
            )
        )
        today_qas = qa_result.scalars().all()
        out.today_answers = len(today_qas)
        out.today_messages = len(today_qas) * 2  # 估算
        real_answers = sum(1 for qa in today_qas if qa.answer and not qa.is_degraded)
        out.success_rate = round((real_answers / len(today_qas) * 100) if today_qas else 0.0, 1)

        items.append(out)

    return AgentListOut(total=len(items), items=items)


@router.post("", response_model=AgentOut)
async def create_agent(
    request: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建新 Agent

    Agent 创建后默认为 stopped 状态，需要手动启动。
    """
    if request.persona_preset == "custom" and not (request.persona_custom_instruction or "").strip():
        raise HTTPException(status_code=422, detail="自定义人格需要填写提示词")
    agent = Agent(
        name=request.name,
        description=request.description or "",
        avatar=request.avatar or "",
        reply_mode="ai",
        persona_preset=request.persona_preset,
        persona_custom_instruction=request.persona_custom_instruction if request.persona_preset == "custom" else None,
        context_window_k=request.context_window_k,
        is_active=False,
        status="stopped",
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)

    return _agent_to_out(agent)


# ============================================================
# 沙箱管理（独立路由，必须在 /{agent_id} 之前，防止被 agent_id 捕获）
# ============================================================

@router.get("/sandboxes", response_model=dict)
async def get_all_sandboxes():
    """
    获取所有 Agent 沙箱的总体统计

    用于管理后台监控所有 Agent 的资源使用情况。
    """
    return sandbox_manager.get_total_stats()


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取 Agent 详情"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    out = _agent_to_out(agent)

    # 今日统计
    today_start = utc_day_start(beijing_today())
    qa_result = await db.execute(
        select(QAHistory).where(
            QAHistory.agent_id == agent.id,
            QAHistory.created_at >= today_start,
        )
    )
    today_qas = qa_result.scalars().all()
    out.today_answers = len(today_qas)
    out.today_messages = len(today_qas) * 2
    real_answers = sum(1 for qa in today_qas if qa.answer and not qa.is_degraded)
    out.success_rate = round((real_answers / len(today_qas) * 100) if today_qas else 0.0, 1)

    return out


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: int,
    request: AgentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Agent 配置"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    update_data = request.model_dump(exclude_unset=True)
    if update_data.get("persona_preset") == "custom" and not (update_data.get("persona_custom_instruction") or agent.persona_custom_instruction or "").strip():
        raise HTTPException(status_code=422, detail="自定义人格需要填写提示词")
    if update_data.get("persona_preset") and update_data["persona_preset"] != "custom":
        update_data["persona_custom_instruction"] = None
    for key, value in update_data.items():
        setattr(agent, key, value)

    await db.flush()
    await db.refresh(agent)

    return _agent_to_out(agent)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    删除 Agent

    同时删除关联的知识库、LLM 配置等。
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    await db.execute(AgentKnowledgeBase.__table__.delete().where(AgentKnowledgeBase.agent_id == agent_id))

    await db.delete(agent)
    await db.flush()

    return {"message": "删除成功", "id": agent_id}


# ============================================================
# Agent 控制
# ============================================================

@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    启动 Agent —— 准备管理台与 API 问答所需的运行环境

    启动时自动创建沙箱：
    - 初始化 Agent 独立数据目录（DATA_DIR/agents/{agent_id}/）
    - 设置资源限制（并发/超时/磁盘/请求频率）
    - 配置网络白名单（基于 Agent 的 LLM 配置）
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    # 创建 Agent 沙箱 —— 隔离资源
    agent_data_dir = settings.DATA_DIR / "agents" / str(agent_id)
    sandbox = sandbox_manager.create_sandbox(agent_id=agent_id, data_dir=agent_data_dir)

    # 根据 Agent 的 LLM 配置自动设置网络白名单
    from app.models.llm_config import LLMConfig
    from urllib.parse import urlparse

    llm_result = await db.execute(
        select(LLMConfig).where(
            LLMConfig.agent_id == agent_id,
            LLMConfig.is_active == True,  # noqa: E712
        )
    )
    llm_configs = llm_result.scalars().all()

    # 提取 LLM API 域名作为网络白名单
    allowed_hosts = set()
    for config in llm_configs:
        if config.base_url:
            try:
                hostname = urlparse(config.base_url).hostname
                if hostname:
                    allowed_hosts.add(hostname)
            except Exception:
                pass

    # 配置沙箱参数
    sandbox.configure(allowed_hosts=allowed_hosts)

    # 设置目录权限（仅当前用户可读写）
    try:
        import os
        os.chmod(agent_data_dir, 0o700)
    except Exception:
        pass  # Windows 下 chmod 可能无意义

    agent.status = "running"
    agent.is_active = True
    await db.flush()

    logger.info(f"Agent-{agent_id} 已启动，沙箱已就绪，允许的 API 端点: {allowed_hosts}")
    return {
        "message": f"Agent '{agent.name}' 已启动",
        "status": "running",
        "sandbox": sandbox.get_usage_stats(),
    }


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    停止 Agent —— 释放运行资源

    停止时自动销毁沙箱：
    - 清理临时文件
    - 释放信号量
    - 从沙箱管理器注销
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    # 销毁 Agent 沙箱 —— 释放资源
    sandbox_manager.destroy_sandbox(agent_id)

    agent.status = "stopped"
    agent.is_active = False
    await db.flush()

    return {"message": f"Agent '{agent.name}' 已停止", "status": "stopped"}


# ============================================================
# Agent 统计
# ============================================================

@router.get("/{agent_id}/sandbox", response_model=dict)
async def get_agent_sandbox(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    获取 Agent 沙箱状态 —— 资源使用统计

    返回沙箱的磁盘使用、并发任务、超时配置等信息。
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    sandbox = sandbox_manager.get_sandbox(agent_id)
    if sandbox is None:
        return {"agent_id": agent_id, "status": "no_sandbox", "message": "Agent 未启动，无沙箱"}

    return sandbox.get_usage_stats()


@router.get("/{agent_id}/stats", response_model=AgentStatsOut)
async def get_agent_stats(
    agent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取 Agent 详细统计"""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")

    # 今日统计
    today_start = utc_day_start(beijing_today())
    qa_result = await db.execute(
        select(QAHistory).where(
            QAHistory.agent_id == agent.id,
            QAHistory.created_at >= today_start,
        )
    )
    today_qas = qa_result.scalars().all()

    today_answers = len(today_qas)
    real_answers = sum(1 for qa in today_qas if qa.answer and not qa.is_degraded)
    success_rate = (real_answers / today_answers * 100) if today_answers > 0 else 0.0
    avg_response_time = (
        sum(qa.total_time_ms or 0 for qa in today_qas) / today_answers
        if today_answers > 0 else 0.0
    )

    return AgentStatsOut(
        agent_id=agent.id,
        agent_name=agent.name,
        status=agent.status,
        today_messages=today_answers * 2,  # 估算：每条回答对应约 2 条消息
        today_answers=today_answers,
        today_learned=0,
        success_rate=round(success_rate, 1),
        avg_response_time_ms=round(avg_response_time, 1),
        total_knowledge_chunks=0,
        last_active_at=agent.updated_at,
    )
