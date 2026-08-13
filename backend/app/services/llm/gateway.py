"""
智答引擎（ZhiDa Engine）—— LLM 统一网关

配置驱动的 LLM 调用层，支持：
- 多厂商模板自动填充（8 个内置厂商 + 自定义）
- 主模型 + 降级模型自动切换
- 测试连接功能
- 流式输出
- 完全从数据库配置读取，不使用硬编码模型列表
"""

import asyncio
import time
from typing import Optional, AsyncIterator, Any, Literal, Callable
from dataclasses import dataclass

from loguru import logger
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.security import decrypt_api_key
from app.models.llm_config import LLMConfig
from app.services.llm.provider_templates import (
    ProviderTemplate,
    get_provider_by_id,
    ProviderCategory,
)


@dataclass
class ModelClient:
    """单个模型客户端 —— 封装 OpenAI 兼容的 API 调用"""
    config: LLMConfig
    client: AsyncOpenAI
    provider: Optional[ProviderTemplate] = None


@dataclass
class ChatResult:
    """LLM 调用结果"""
    text: str
    model_used: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


class LLMGateway:
    """
    LLM 统一网关 —— 管理所有已配置的 LLM 模型

    配置驱动：从数据库读取全局模型配置，不使用硬编码模型列表。
    所有 Agent 共用同一套主模型、降级模型和上下文模型配置。

    Usage:
        gateway = LLMGateway()
        await gateway.initialize()

        # 普通调用
        response = await gateway.chat("你好，请介绍一下自己")

        # 流式调用
        async for chunk in gateway.chat_stream("你好"):
            print(chunk, end="")
    """

    def __init__(self):
        # 当前全局模型配置对应的客户端
        self._primary_client: Optional[ModelClient] = None     # 主模型
        self._fallback_clients: list[ModelClient] = []          # 降级模型列表
        self._context_client: Optional[ModelClient] = None      # 问题重写 / 会话压缩

    # ================================================================
    # 初始化
    # ================================================================

    async def initialize(self):
        """
        初始化网关 —— 从数据库加载全局 LLM 配置。
        """
        self._primary_client = None
        self._fallback_clients = []
        self._context_client = None

        # 从数据库加载配置
        configs = await self._load_configs()

        # 构建模型客户端
        for config in configs:
            client = self._build_client(config)
            if config.is_context_model:
                self._context_client = client
            if config.is_primary:
                self._primary_client = client
            elif config.is_fallback:
                self._fallback_clients.append(client)

        # 兼容早期配置：用户完成连接测试但未勾选“主模型”时，实际问答仍应使用唯一的启用配置。
        answer_configs = [config for config in configs if not config.is_context_model]
        if self._primary_client is None and answer_configs:
            self._primary_client = self._build_client(answer_configs[0])
            logger.warning(
                f"全局 LLM 配置没有标记主模型，临时使用 {answer_configs[0].model_name}；"
                "请在设置中将其设为主模型"
            )

        # 如果没有配置主模型，记录警告
        if self._primary_client is None:
            logger.warning("未配置全局主模型，LLM 功能不可用")

        logger.info(
            "LLM 网关初始化完成: 全局配置, "
            f"主模型={self._primary_client.config.model_name if self._primary_client else '无'}, "
            f"降级模型={len(self._fallback_clients)} 个"
        )

    async def chat_context(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        task: Literal["rewrite", "compaction"] = "rewrite",
    ) -> ChatResult:
        """调用上下文模型；两个任务各自有短超时，避免占满单机模型锁。"""
        client = self._context_client or self._primary_client
        if client is None:
            raise RuntimeError("没有可用的重写/压缩模型或主模型")
        messages = [{"role": "user", "content": prompt}]
        timeout = (
            client.config.context_compaction_timeout_seconds
            if task == "compaction"
            else client.config.context_rewrite_timeout_seconds
        )
        return await asyncio.wait_for(
            self._call_model(client, messages, temperature, max_tokens),
            timeout=max(int(timeout or 0), 1),
        )

    async def _load_configs(self) -> list[LLMConfig]:
        """仅从数据库加载启用的全局 LLM 配置。"""
        from app.core.database import async_session_factory
        from sqlalchemy import select

        async with async_session_factory() as session:
            query = select(LLMConfig).where(
                LLMConfig.is_active == True,  # noqa: E712
            )
            result = await session.execute(
                query.where(LLMConfig.agent_id.is_(None)).order_by(LLMConfig.is_primary.desc())
            )
            return list(result.scalars().all())

    def _build_client(self, config: LLMConfig) -> ModelClient:
        """根据配置构建 OpenAI 兼容客户端"""
        base_url = config.base_url
        # 解密 API Key 后使用（加密存储，运行时解密）
        api_key = decrypt_api_key(config.api_key)

        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0,  # 60 秒超时
        )

        # 查找对应的厂商模板
        provider = get_provider_by_id(config.provider_id)

        return ModelClient(
            config=config,
            client=client,
            provider=provider,
        )

    # ================================================================
    # 对话接口
    # ================================================================

    async def chat(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        extra_body: Optional[dict] = None,
    ) -> ChatResult:
        """
        发送对话请求 —— 主模型失败时自动降级

        Args:
            prompt: 用户消息
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            ChatResult 包含回复文本和 token 用量

        Raises:
            RuntimeError: 所有模型（主模型 + 降级模型）都不可用时
        """
        # 构建消息列表
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # 尝试主模型
        if self._primary_client:
            try:
                return await self._call_model(self._primary_client, messages, temperature, max_tokens, extra_body)
            except Exception as e:
                logger.warning(f"主模型 {self._primary_client.config.model_name} 调用失败: {e}，尝试降级模型")

        # 降级：依次尝试降级模型
        for fallback in self._fallback_clients:
            try:
                logger.info(f"使用降级模型: {fallback.config.model_name}")
                return await self._call_model(fallback, messages, temperature, max_tokens, extra_body)
            except Exception as e:
                logger.warning(f"降级模型 {fallback.config.model_name} 也失败: {e}")
                continue

        # 所有模型都不可用
        raise RuntimeError("所有 LLM 模型均不可用，请检查配置和网络连接")

    async def chat_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        on_usage: Optional[Callable[[int, int, int], None]] = None,
    ) -> AsyncIterator[str]:
        """
        流式对话 —— 逐 token 返回模型回复

        Usage:
            async for chunk in gateway.chat_stream("你好"):
                yield chunk  # 每段是一个 token 或 token 片段
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        clients = ([self._primary_client] if self._primary_client else []) + self._fallback_clients
        if not clients:
            raise RuntimeError("没有可用的 LLM 模型")

        # 仅在尚未向用户输出任何内容时允许切换。若已输出再换模型，回答会从头
        # 重复，反而破坏对话；这时将错误交给上层保持流式结果一致。
        for index, client in enumerate(clients):
            emitted = False
            try:
                async for chunk in self._call_model_stream(client, messages, temperature, max_tokens, on_usage):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:
                if emitted or index == len(clients) - 1:
                    logger.error(f"流式调用失败: {exc}")
                    raise
                logger.warning(
                    f"流式主模型 {client.config.model_name} 在输出前失败: {exc}，尝试降级模型"
                )

    # ================================================================
    # 底层调用
    # ================================================================

    async def _call_model(
        self,
        model_client: ModelClient,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        extra_body: Optional[dict] = None,
    ) -> ChatResult:
        """调用单个模型（非流式），返回包含 token 用量的结果"""
        start_time = time.time()

        request_kwargs = dict(
            model=model_client.config.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if extra_body:
            request_kwargs["extra_body"] = extra_body
        try:
            response = await model_client.client.chat.completions.create(**request_kwargs)
        except Exception:
            # 不同 OpenAI 兼容厂商对扩展参数的支持并不一致；拒绝时无参数重试，
            # 不让一个优化项影响原有问答可用性。
            if not extra_body:
                raise
            logger.info(f"模型 {model_client.config.model_name} 不支持扩展参数，回退普通调用")
            request_kwargs.pop("extra_body", None)
            response = await model_client.client.chat.completions.create(**request_kwargs)

        elapsed = (time.time() - start_time) * 1000
        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage
        finish_reason = choice.finish_reason or "unknown"
        reasoning_content = getattr(choice.message, "reasoning_content", None) or ""

        logger.debug(
            f"模型 {model_client.config.model_name} 响应: "
            f"{len(content)} 字符, {elapsed:.0f}ms, finish_reason={finish_reason}, "
            f"reasoning={len(reasoning_content)} 字符"
        )
        # 空正文不是有效回答。将其视为调用失败，才能触发已有降级模型策略，
        # 而不是把空字符串交给上层业务在很晚的阶段才报错。
        if not content.strip():
            raise RuntimeError(
                f"模型返回空正文（finish_reason={finish_reason}, reasoning={len(reasoning_content)} 字符）"
            )

        # OpenAI 兼容厂商的缓存 usage 字段并不统一：OpenAI/部分网关放在
        # prompt_tokens_details.cached_tokens，DeepSeek 等常见 prompt_cache_hit_tokens。
        # 仅采集响应明确返回的数字，未知厂商保持 0，绝不估算。
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        cached_input_tokens = (
            getattr(prompt_details, "cached_tokens", None)
            or getattr(usage, "prompt_cache_hit_tokens", None)
            or getattr(usage, "cached_tokens", None)
            or 0
        )
        try:
            cached_input_tokens = max(0, min(int(cached_input_tokens), int(usage.prompt_tokens if usage else 0)))
        except (TypeError, ValueError):
            cached_input_tokens = 0
        return ChatResult(
            text=content,
            model_used=model_client.config.model_name,
            input_tokens=usage.prompt_tokens if usage else 0,
            cached_input_tokens=cached_input_tokens,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    async def _call_model_stream(
        self,
        model_client: ModelClient,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        on_usage: Optional[Callable[[int, int, int], None]] = None,
    ) -> AsyncIterator[str]:
        """调用单个模型（流式）"""
        stream = await model_client.client.chat.completions.create(
            model=model_client.config.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        # 流式 SDK 会在最后一个 chunk 给出 finish_reason。此前该信息被静默
        # 丢弃，排查“详细模式是否被模型长度上限截断”时没有证据。
        finish_reason: str | None = None
        content_emitted = False
        reasoning_characters = 0
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage and on_usage:
                prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                details = getattr(usage, "prompt_tokens_details", None)
                cached_tokens = (
                    getattr(details, "cached_tokens", None)
                    or getattr(usage, "prompt_cache_hit_tokens", None)
                    or getattr(usage, "cached_tokens", None)
                    or 0
                )
                try:
                    on_usage(prompt_tokens, min(max(0, int(cached_tokens)), prompt_tokens), completion_tokens)
                except (TypeError, ValueError):
                    on_usage(prompt_tokens, 0, completion_tokens)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            # reasoning_content 是部分推理模型在 OpenAI 兼容流中返回的隐藏
            # 思考过程。它不能直接展示给用户，但必须被计数：若模型把 token
            # 全用在推理而没有正文，不能把空答案当作一次成功回答。
            reasoning = (
                getattr(choice.delta, "reasoning_content", None)
                or getattr(choice.delta, "reasoning", None)
                or ""
            )
            reasoning_characters += len(reasoning)
            if choice.delta.content:
                content_emitted = True
                yield choice.delta.content
        logger.info(
            "流式模型输出结束：model={}, finish_reason={}, requested_max_tokens={}, reasoning_chars={}, content_emitted={}",
            model_client.config.model_name,
            finish_reason or "unknown",
            max_tokens,
            reasoning_characters,
            content_emitted,
        )
        if not content_emitted:
            raise RuntimeError(
                f"模型未返回可展示正文（finish_reason={finish_reason or 'unknown'}，"
                f"推理内容={reasoning_characters} 字符）"
            )

    # ================================================================
    # 测试连接
    # ================================================================

    async def test_connection(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
    ) -> dict:
        """
        测试 LLM 连接 —— 发送测试消息验证连通性

        Args:
            base_url: API 基础地址
            api_key: API Key
            model_name: 模型名称

        Returns:
            {"success": True/False, "message": "...", "latency_ms": ...}
        """
        start_time = time.time()

        try:
            client = AsyncOpenAI(
                base_url=base_url,
                api_key=api_key or "not-needed",
                timeout=15.0,  # 测试连接用较短超时
            )

            response = await client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "你好，请回复'连接测试成功'"}],
                max_tokens=20,
                temperature=0.0,
            )

            elapsed = (time.time() - start_time) * 1000
            reply = response.choices[0].message.content or ""

            return {
                "success": True,
                "message": f"连接成功！模型回复: {reply[:50]}",
                "latency_ms": round(elapsed, 0),
                "model": model_name,
            }

        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            logger.warning(f"连接测试失败: {model_name} @ {base_url}: {e}")

            return {
                "success": False,
                "message": f"连接失败: {str(e)[:200]}",
                "latency_ms": round(elapsed, 0),
                "model": model_name,
            }

    async def test_configured_model(self, config: LLMConfig) -> dict:
        """测试已配置的模型连接"""
        return await self.test_connection(
            base_url=config.base_url,
            api_key=config.api_key,
            model_name=config.model_name,
        )

    # ================================================================
    # 状态查询
    # ================================================================

    @property
    def is_ready(self) -> bool:
        """网关是否就绪（至少有一个可用模型）"""
        return self._primary_client is not None or len(self._fallback_clients) > 0

    @property
    def primary_model_name(self) -> Optional[str]:
        """获取主模型名称"""
        if self._primary_client:
            return self._primary_client.config.model_name
        return None

    def get_available_models(self) -> list[dict]:
        """获取所有可用模型信息"""
        models = []
        if self._primary_client:
            models.append({
                "role": "primary",
                "model": self._primary_client.config.model_name,
                "provider": self._primary_client.config.provider_name,
            })
        for client in self._fallback_clients:
            models.append({
                "role": "fallback",
                "model": client.config.model_name,
                "provider": client.config.provider_name,
            })
        return models


# 全局网关实例
# 注意：需要在 Agent 切换时重新初始化
llm_gateway = LLMGateway()
