"""
智答引擎（ZhiDa Engine）—— 回答生成器

组合检索、Prompt 构建和 LLM 调用，生成最终回答。
支持流式输出和普通输出。

模块开关：
- ENABLE_STREAMING: 是否启用流式输出
- ENABLE_SOURCE_CITATION: 是否附带来源引用
"""

import time
import asyncio
import hashlib
import re
from pathlib import Path
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field

from loguru import logger

from app.core.config import settings
from app.services.qa.retriever import hybrid_retriever
from app.services.qa.prompt import prompt_template
from app.services.llm.gateway import llm_gateway
from app.services.cache.query_cache import query_cache
from app.services.cache.idempotency import single_flight
from app.services.cache.degradation import degradation_manager
from app.services.knowledge.indexer import IndexResult
from app.services.memory.memory_service import memory_service
from app.services.qa.web_search import web_search_service
from app.services.qa.langfuse_observer import observe_qa


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
    input_tokens: int = 0   # 请求 Token 数
    output_tokens: int = 0  # 回答 Token 数
    web_search_count: int = 0  # 实际发起网络检索次数（不等同于返回结果数）


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

    @staticmethod
    def _unique_sources(results: list[IndexResult], limit: int = 3) -> list[dict]:
        """按文档与章节去重，避免同一文档的相邻切片重复显示为多个来源。"""
        sources: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for result in results:
            metadata = result.metadata or {}
            filename = str(metadata.get("filename", "未知来源"))
            section = str(metadata.get("section_title", ""))
            key = (filename, section)
            if key in seen:
                continue
            seen.add(key)
            sources.append({
                "text": result.text[:100],
                "score": result.score,
                "metadata": metadata,
            })
            if len(sources) >= limit:
                break
        return sources

    @staticmethod
    def _explicitly_requests_web(question: str) -> bool:
        """用户明确要求联网时，不能因本地已有命中而跳过网络检索。"""
        return bool(re.search(
            r"(上网|联网|网络|网上|网页|互联网).{0,8}(搜|搜索|查|检索|查一下|查查)|"
            r"(搜一下|搜索一下|查一下|帮我查|帮忙查).{0,8}(网上|网络|网页|互联网)|"
            r"\b(web\s*search|search\s*(the\s*)?web)\b",
            question,
            flags=re.IGNORECASE,
        ))

    @staticmethod
    def _local_information_gap(question: str, results: list[IndexResult]) -> bool:
        """用可解释的轻量规则判断本地证据是否覆盖问题，而非仅看是否命中。"""
        if not results:
            return True
        cleaned = re.sub(r"请|帮我|帮忙|上网|联网|网络|网上|网页|互联网|搜索|搜一下|搜|查一下|查|检索", " ", question)
        english_entities = re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{1,30}\b", cleaned)
        chinese_entities = re.findall(r"[\u4e00-\u9fff]{2,}", re.sub(r"[的和与及跟有关于、，,。？！?：:]", " ", cleaned))
        ignored = {"什么", "怎么", "如何", "有关", "关系", "什么关系", "一下", "信息", "资料", "相关", "这个", "那个", "是否", "什么特点", "有什么特点", "怎么样", "好不好", "看法", "感想", "特点"}
        entities = list(dict.fromkeys(
            term for term in [*english_entities, *chinese_entities]
            if term.lower() not in ignored
        ))
        corpus = "\n".join(result.text for result in results).lower()
        if any(entity.lower() not in corpus for entity in entities):
            return True

        # 关系问题必须有一条证据同时提到所有实体；分别命中 Tim 与潘天鸿并不能证明二者有关联。
        relation_question = bool(re.search(r"(关系|关联|联系|认识|合作|同事|同学|搭档)", question))
        if relation_question and len(entities) >= 2:
            return not any(all(entity.lower() in result.text.lower() for entity in entities) for result in results)

        # 用户明确授权联网时，单一资料来源通常不足以补全人物/事件背景，允许网络进行交叉补充。
        source_keys = {
            str((result.metadata or {}).get("document_id") or (result.metadata or {}).get("filename") or result.chunk_id)
            for result in results
        }
        return AnswerGenerator._explicitly_requests_web(question) and len(source_keys) < 2

    @staticmethod
    def _needs_web_supplement(question: str, results: list[IndexResult]) -> bool:
        """联网仅用于补足本地证据缺口；明确指令代表授权，而不是无条件搜索。"""
        return AnswerGenerator._local_information_gap(question, results)

    @staticmethod
    def _build_web_search_query(question: str, results: list[IndexResult]) -> str:
        """从本地上下文提取消歧词，避免直接搜索 Tim 等歧义短词。"""
        # 指令不是实体，不应污染实际搜索词；保留用户问题的其余部分。
        cleaned_question = re.sub(
            r"(?:请|帮我|帮忙)?(?:上网|联网|网络|网上|网页|互联网)?(?:搜(?:索)?|查(?:一下|查)?|检索)(?:一下)?(?:相关)?(?:信息|资料)?[：:，,\s]*",
            "", question, flags=re.IGNORECASE,
        ).strip() or question
        if not results:
            return cleaned_question

        identity_match = re.match(
            r"\s*(.+?)(?:是谁|是什么人|是哪位|的?全名|的?真名|的?真实姓名|的?本名|的?身份)",
            cleaned_question,
            flags=re.IGNORECASE,
        )
        exact_terms: list[str] = []
        subject = ""
        if identity_match:
            subject = identity_match.group(1).strip(" ，。？！?：:")
            if subject:
                exact_terms.append(f'"{subject}"')

        ranked_results = list(results)
        if subject:
            lowered_subject = subject.lower()

            def subject_relevance(result: IndexResult) -> tuple[int, float]:
                filename = str((result.metadata or {}).get("filename", "")).lower()
                text = result.text.lower()
                if re.fullmatch(r"[a-z0-9_-]+", lowered_subject):
                    exact_count = len(re.findall(
                        rf"(?<![a-z0-9_-]){re.escape(lowered_subject)}(?![a-z0-9_-])",
                        text,
                    ))
                else:
                    exact_count = text.count(lowered_subject)
                return (
                    (10 if lowered_subject in filename else 0) + exact_count,
                    result.score,
                )

            ranked_results.sort(key=subject_relevance, reverse=True)

        context = "\n".join(result.text[:800] for result in ranked_results[:2])

        # 常见机构复合名容易被分词拆开，保留原始短语用于实体消歧。
        exact_terms.extend(
            f'"{term}"'
            for term in re.findall(r"影视[\u4e00-\u9fff]{2}", context)
            if f'"{term}"' not in exact_terms
        )
        candidates: list[str] = []
        try:
            import jieba.analyse
            candidates.extend(jieba.analyse.extract_tags(context, topK=12))
        except Exception:
            pass

        for result in ranked_results[:2]:
            filename = str((result.metadata or {}).get("filename", ""))
            if filename:
                candidates.append(Path(filename).stem)

        # 连续英文名通常是有效消歧词，例如 Tim、Links。
        candidates.extend(re.findall(r"\b[A-Za-z][A-Za-z0-9_-]{1,30}\b", context))
        ignored = {"一个", "这个", "就是", "如果", "可以", "没有", "关于", "正文", "前言"}
        selected: list[str] = []
        for candidate in candidates:
            term = candidate.strip()
            if len(term) < 2 or term.lower() in ignored or term in selected:
                continue
            selected.append(term)
            if len(selected) >= 10:
                break
        if len(exact_terms) >= 2:
            return " ".join(exact_terms[:3])[:240]
        if exact_terms:
            return " ".join([*exact_terms, *selected[:4]])[:240]
        return " ".join([cleaned_question, *selected])[:240]

    @staticmethod
    def _web_context_and_sources(web_results) -> tuple[str, list[dict]]:
        if not web_results:
            return "", []
        context = "【网络补充资料】\n" + "\n\n".join(
            f"---\n来源：{item.title}\n链接：{item.url}\n内容：{item.content[:1200]}"
            for item in web_results
        )
        sources = [{
            "text": item.content[:100],
            "score": 0.0,
            "metadata": {
                "filename": item.title,
                "url": item.url,
                "source_type": "web",
            },
        } for item in web_results]
        return context, sources

    async def generate(
        self,
        knowledge_base_ids: list[str],
        question: str,
        top_k: int = 5,
        system_prompt: Optional[str] = None,
        include_sources: bool = True,
        temperature: float = 0.7,
        user_id: Optional[str] = None,
        agent_id: Optional[int] = None,
        enable_memory: bool = True,
        reply_mode: str = "auto",
        conversation_history: Optional[list[dict[str, str]]] = None,
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
        history_text = "\n".join(
            f"{item.get('role', '')}:{item.get('content', '')}"
            for item in (conversation_history or [])[-12:]
        )
        history_key = hashlib.sha256(history_text.encode("utf-8")).hexdigest()[:16] if history_text else "none"
        cache_query = (
            f"pipeline:web-intent-v5:agent:{agent_id if agent_id is not None else 'global'}:"
            f"user:{user_id or 'shared'}:history:{history_key}:{question}"
        )
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
            results = await hybrid_retriever.retrieve(
                knowledge_base_ids=knowledge_base_ids,
                query=question,
                top_k=top_k,
            )
        except Exception as e:
            logger.warning(f"混合检索失败: {e}，使用降级策略")
            results = []

        retrieval_time = (time.time() - retrieval_start) * 1000

        # 3. 构建上下文 + RAG 无结果降级策略
        source_info = ""
        supplemental_sources: list[dict] = []
        web_search_count = 0
        if results:
            context = prompt_template.build_context_from_results(results)
            source_list = self._unique_sources(results)
            source_info = "; ".join(
                item["metadata"].get("section_title") or item["metadata"].get("filename", "未知来源")
                for item in source_list
            )

            if self._needs_web_supplement(question, results):
                search_query = self._build_web_search_query(question, results)
                logger.info(f"本地信息存在缺口，触发联网补充（显式授权={self._explicitly_requests_web(question)}）: {search_query}")
                web_search_count += 1
                web_results = await web_search_service.search(search_query)
                web_context, supplemental_sources = self._web_context_and_sources(web_results)
                if web_context:
                    context = f"{context}\n\n{web_context}"
                    source_info = "; ".join([
                        source_info,
                        *(item.title for item in web_results),
                    ]).strip("; ")
                    logger.info(
                        f"本地答案存在身份信息缺口，联网补充 {len(web_results)} 条: {search_query}"
                    )
        else:
            # 手动模式：直接返回无结果，不调用 LLM
            if reply_mode == "manual":
                logger.info(f"RAG 无结果，reply_mode=manual，跳过 LLM")
                return AnswerResult(
                    answer="知识库中未找到相关信息，请尝试换个问法或上传相关文档。",
                    sources=[],
                    retrieval_time_ms=retrieval_time,
                    generation_time_ms=0,
                )
            # 自动/混合模式：让 LLM 用自身知识回答
            web_search_count += 1
            web_results = await web_search_service.search(self._build_web_search_query(question, results))
            if web_results:
                context, supplemental_sources = self._web_context_and_sources(web_results)
                source_info = "; ".join(item.title for item in web_results)
                logger.info(f"RAG 无结果，已补充 {len(web_results)} 条网络检索结果")
            else:
                context = (
                    "知识库中未找到与问题直接相关的内容。\n\n"
                    "请根据自身知识回答，并在开头注明「以下内容基于模型自身知识，可能不完全准确」。"
                )
                logger.info(f"RAG 无结果，reply_mode={reply_mode}，允许 LLM 自行回答")

        # 5. 构建 Prompt（注入记忆上下文）
        full_context = context + memory_context if memory_context else context
        conversation_context = "\n".join(
            f"{'用户' if item.get('role') == 'user' else '助手'}：{item.get('content', '')[:1000]}"
            for item in (conversation_history or [])[-12:]
            if item.get("content")
        )

        if system_prompt:
            prompt = system_prompt.format(context=full_context, question=question)
        else:
            prompt = prompt_template.build_qa_prompt(
                question=question,
                context=full_context,
                source_info=source_info,
                include_sources=include_sources and settings.ENABLE_SOURCE_CITATION,
                conversation_context=conversation_context,
            )

        generation_start = time.time()

        # 6. LLM 生成（含降级）
        input_tokens = 0
        output_tokens = 0
        try:
            async with self._llm_lock:
                await llm_gateway.initialize(agent_id)
                chat_result = await llm_gateway.chat(
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=2048,
                )
                answer_text = chat_result.text
                model_used = chat_result.model_used or llm_gateway.primary_model_name or "unknown"
                input_tokens = chat_result.input_tokens
                output_tokens = chat_result.output_tokens
            degraded = False
        except Exception as e:
            logger.warning(f"LLM 生成失败: {e}")

            answer_text = degradation_manager.get_llm_offline_response()

            model_used = "offline"
            degraded = True

        generation_time = (time.time() - generation_start) * 1000

        # 7. 写入缓存
        if not degraded:
            await query_cache.set(cache_query, answer_text)

        # 8. 写入记忆（异步，不阻塞返回）
        if enable_memory and memory_service.is_available and not degraded:
            try:
                import asyncio
                agent_str = str(agent_id) if agent_id else None
                messages = [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer_text},
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

        # 观测异步上报，Langfuse 网络异常不会阻塞或影响用户回答。
        asyncio.create_task(observe_qa(
            question=question, answer=answer_text, user_id=user_id,
            model=model_used, input_tokens=input_tokens, output_tokens=output_tokens,
            metadata={"agent_id": agent_id, "retrieval_time_ms": round(retrieval_time), "generation_time_ms": round(generation_time), "web_search_count": web_search_count, "degraded": degraded},
        ))

        return AnswerResult(
            answer=answer_text,
            sources=(self._unique_sources(results) if results else []) + supplemental_sources,
            retrieval_time_ms=retrieval_time,
            generation_time_ms=generation_time,
            model_used=model_used,
            degraded=degraded,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            web_search_count=web_search_count,
        )

    async def generate_stream(
        self,
        knowledge_base_ids: list[str],
        question: str,
        top_k: int = 5,
        include_sources: bool = True,
        temperature: float = 0.7,
        agent_id: Optional[int] = None,
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
            results = await hybrid_retriever.retrieve(
                knowledge_base_ids=knowledge_base_ids,
                query=question,
                top_k=top_k,
            )
        except Exception:
            results = []

        # 构建上下文；无结果或身份类问题信息不完整时补充网络资料。
        context = prompt_template.build_context_from_results(results) if results else "知识库中暂无相关内容"
        if self._needs_web_supplement(question, results):
            search_query = self._build_web_search_query(question, results)
            logger.info(f"流式回答本地信息存在缺口，触发联网补充（显式授权={self._explicitly_requests_web(question)}）: {search_query}")
            web_results = await web_search_service.search(search_query)
            web_context, _ = self._web_context_and_sources(web_results)
            if web_context:
                context = f"{context}\n\n{web_context}"

        # 构建 Prompt
        prompt = prompt_template.build_qa_prompt(
            question=question,
            context=context,
            include_sources=include_sources and settings.ENABLE_SOURCE_CITATION,
        )

        # 流式调用 LLM
        try:
            async with self._llm_lock:
                await llm_gateway.initialize(agent_id)
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
