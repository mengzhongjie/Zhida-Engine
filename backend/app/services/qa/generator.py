"""
智答引擎（ZhiDa Engine）—— 回答生成器

组合检索、重排序、Prompt 构建和 LLM 调用，生成最终回答。
支持流式输出和普通输出。

模块开关：
- ENABLE_RERANK: 是否启用重排序
- ENABLE_STREAMING: 是否启用流式输出
- ENABLE_SOURCE_CITATION: 是否附带来源引用
- ENABLE_AUTO_MENTION: 回答不了时是否 @ 指定用户
"""

import time
import asyncio
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field

from loguru import logger

from app.core.config import settings
from app.services.qa.retriever import hybrid_retriever
from app.services.qa.reranker import reranker
from app.services.qa.prompt import prompt_template
from app.services.llm.gateway import llm_gateway
from app.services.cache.query_cache import query_cache
from app.services.cache.idempotency import single_flight
from app.services.cache.degradation import degradation_manager
from app.services.knowledge.indexer import IndexResult
from app.services.memory.memory_service import memory_service


@dataclass
class AnswerResult:
    """回答结果"""
    answer: str
    sources: list[dict] = field(default_factory=list)  # 引用来源
    is_cache_hit: bool = False
    retrieval_time_ms: float = 0.0
    generation_time_ms: float = 0.0
    model_used: str = ""
    degraded: bool = False  # 是否使用了降级策略


class AnswerGenerator:
    """
    回答生成器 —— 端到端的问答流程

    Usage:
        generator = AnswerGenerator()

        # 普通回答
        result = await generator.generate(
            knowledge_base_ids=["kb_1"],
            question="退换货政策是什么？",
        )

        # 流式回答
        async for chunk in generator.generate_stream(
            knowledge_base_ids=["kb_1"],
            question="退换货政策是什么？",
        ):
            yield chunk
    """

    def __init__(self):
        # LLMGateway 当前维护可变的 Agent 配置。低成本单机部署下串行化模型调用，
        # 能避免两个不同 Agent 的并发请求串用模型或 API Key。
        self._llm_lock = asyncio.Lock()

    async def generate(
        self,
        knowledge_base_ids: list[str],
        question: str,
        top_k: int = 5,
        system_prompt: Optional[str] = None,
        include_sources: bool = True,
        auto_mention_users: Optional[str] = None,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
        agent_id: Optional[int] = None,
        enable_memory: bool = True,
    ) -> AnswerResult:
        """
        生成回答 —— 端到端流程

        流程：
        1. 查询缓存
        2. 检索相关记忆（记忆层）
        3. 混合检索
        4. 重排序
        5. 构建 Prompt（含记忆上下文）
        6. LLM 生成
        7. 写入缓存
        8. 写入记忆（对话记忆）
        """
        total_start = time.time()

        # 缓存必须按 Agent 和用户隔离，避免不同知识库或记忆上下文互相泄漏。
        cache_query = f"agent:{agent_id if agent_id is not None else 'global'}:user:{user_id or 'shared'}:{question}"
        if cached := await query_cache.get(cache_query):
            return AnswerResult(
                answer=cached,
                is_cache_hit=True,
                retrieval_time_ms=0,
                generation_time_ms=0,
            )

        # 2. 检索相关记忆
        memory_context = ""
        if enable_memory and memory_service.is_available:
            try:
                agent_str = str(agent_id) if agent_id else None
                memory_text = await memory_service.get_relevant_memories(
                    query=question,
                    user_id=user_id,
                    agent_id=agent_str,
                    limit=5,
                )
                if memory_text:
                    memory_context = f"\n\n【用户相关记忆】\n{memory_text}"
                    logger.debug(f"[Memory] 检索到 {len(memory_text.splitlines())} 条相关记忆")
            except Exception as e:
                logger.debug(f"[Memory] 记忆检索失败: {e}")

        retrieval_start = time.time()

        # 2. 混合检索（含降级）
        try:
            results = await hybrid_retriever.retrieve_with_graph(
                knowledge_base_ids=knowledge_base_ids,
                query=question,
                top_k=top_k * 2,  # 多取一些给重排序
            )
        except Exception as e:
            logger.warning(f"混合检索失败: {e}，使用降级策略")
            results = []

        retrieval_time = (time.time() - retrieval_start) * 1000

        # 3. 重排序
        if results and settings.ENABLE_RERANK:
            results = await reranker.rerank(question, results, top_k=top_k)

        # 4. 构建上下文
        source_info = ""
        if results:
            context = prompt_template.build_context_from_results(results)
            # 构建来源信息
            source_list = []
            for r in results[:3]:
                source_list.append({
                    "text": r.text[:100],
                    "score": r.score,
                    "metadata": r.metadata,
                })
            source_info = "; ".join(
                r.metadata.get("section_title", r.metadata.get("filename", "未知来源"))
                for r in results[:3]
                if r.metadata
            )
        else:
            context = "知识库中暂无相关内容"

        # 5. 构建 Prompt（注入记忆上下文）
        full_context = context + memory_context if memory_context else context

        if system_prompt:
            prompt = system_prompt.format(context=full_context, question=question)
        else:
            prompt = prompt_template.build_qa_prompt(
                question=question,
                context=full_context,
                source_info=source_info,
                include_sources=include_sources and settings.ENABLE_SOURCE_CITATION,
            )

        generation_start = time.time()

        # 6. LLM 生成（含降级）
        try:
            async with self._llm_lock:
                await llm_gateway.initialize(agent_id)
                answer = await llm_gateway.chat(
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=2048,
                )
                model_used = llm_gateway.primary_model_name or "unknown"
            degraded = False
        except Exception as e:
            logger.warning(f"LLM 生成失败: {e}")

            # 如果配置了自动 @，返回 @ 消息
            if auto_mention_users and settings.ENABLE_AUTO_MENTION:
                answer = prompt_template.build_auto_mention(
                    question=question,
                    mention_users=auto_mention_users,
                    source_info=source_info,
                    failed_attempt=True,
                )
            else:
                answer = degradation_manager.get_llm_offline_response()

            model_used = "offline"
            degraded = True

        generation_time = (time.time() - generation_start) * 1000

        # 7. 写入缓存
        if not degraded:
            await query_cache.set(cache_query, answer)

        # 8. 写入记忆（异步，不阻塞返回）
        if enable_memory and memory_service.is_available and not degraded:
            try:
                import asyncio
                agent_str = str(agent_id) if agent_id else None
                messages = [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ]
                # 后台任务写入记忆，不阻塞主流程
                asyncio.create_task(
                    memory_service.add(
                        messages,
                        user_id=user_id,
                        agent_id=agent_str,
                    )
                )
            except Exception as e:
                logger.debug(f"[Memory] 异步写入记忆失败: {e}")

        total_time = (time.time() - total_start) * 1000
        logger.info(
            f"问答完成: 检索={retrieval_time:.0f}ms, "
            f"生成={generation_time:.0f}ms, "
            f"总计={total_time:.0f}ms, "
            f"模型={model_used}"
        )

        return AnswerResult(
            answer=answer,
            sources=[
                {"text": r.text[:100], "score": r.score, "metadata": r.metadata}
                for r in results[:3]
            ] if results else [],
            retrieval_time_ms=retrieval_time,
            generation_time_ms=generation_time,
            model_used=model_used,
            degraded=degraded,
        )

    async def generate_stream(
        self,
        knowledge_base_ids: list[str],
        question: str,
        top_k: int = 5,
        include_sources: bool = True,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        流式生成回答 —— 逐 token 返回

        Usage:
            async for chunk in generator.generate_stream(["kb_1"], "问题"):
                yield chunk
        """
        if not settings.ENABLE_STREAMING:
            # 非流式模式：直接返回完整结果
            result = await self.generate(
                knowledge_base_ids=knowledge_base_ids,
                question=question,
                top_k=top_k,
                include_sources=include_sources,
                temperature=temperature,
            )
            yield result.answer
            return

        # 检索
        try:
            results = await hybrid_retriever.retrieve_with_graph(
                knowledge_base_ids=knowledge_base_ids,
                query=question,
                top_k=top_k * 2,
            )
        except Exception:
            results = []

        # 重排序
        if results and settings.ENABLE_RERANK:
            results = await reranker.rerank(question, results, top_k=top_k)

        # 构建上下文
        context = prompt_template.build_context_from_results(results) if results else "知识库中暂无相关内容"

        # 构建 Prompt
        prompt = prompt_template.build_qa_prompt(
            question=question,
            context=context,
            include_sources=include_sources and settings.ENABLE_SOURCE_CITATION,
        )

        # 流式调用 LLM
        try:
            async for chunk in llm_gateway.chat_stream(
                prompt=prompt,
                temperature=temperature,
            ):
                yield chunk
        except Exception as e:
            logger.error(f"流式生成失败: {e}")
            yield degradation_manager.get_llm_offline_response()


# 全局回答生成器实例
answer_generator = AnswerGenerator()
