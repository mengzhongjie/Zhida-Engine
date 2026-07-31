"""
智答引擎（ZhiDa Engine）—— 向量化服务

默认使用 BAAI/bge-large-zh-v1.5 本地模型（1024 维），
支持切换云端 Embedding API。

抽象 EmbeddingService 接口，方便切换不同实现。
"""

import time
from abc import ABC, abstractmethod

from loguru import logger

from app.core.config import settings


BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


def _prepare_query(model_name: str, query: str) -> str:
    """BGE v1.5 仅查询侧需要检索指令，文档侧保持原文。"""
    normalized_name = model_name.strip().lower()
    if normalized_name == "baai/bge-large-zh-v1.5" or normalized_name.endswith("/bge-large-zh-v1.5"):
        return f"{BGE_QUERY_INSTRUCTION}{query}"
    return query


class EmbeddingService(ABC):
    """
    Embedding 服务抽象接口 —— 支持本地和云端实现

    所有 Embedding 实现必须继承此接口。
    """

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        ...

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量"""
        ...

    async def embed_query(self, query: str) -> list[float]:
        """向量化查询；特定模型可覆盖查询侧预处理。"""
        return await self.embed_text(_prepare_query(self.model_name, query))

    @abstractmethod
    async def is_ready(self) -> bool:
        """检查服务是否就绪"""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """向量维度"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """模型名称"""
        ...


class LocalBGEEmbedding(EmbeddingService):
    """
    本地 BGE Embedding 服务 —— 使用 sentence-transformers

    优点：
    - 完全免费，无需 API Key
    - 数据不出机器
    - 中文嵌入 SOTA

    缺点：
    - 首次加载模型需要下载（约 1.3GB）
    - 需要 CPU/GPU 资源
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-zh-v1.5",
        device: str = "cpu",
    ):
        self._model_name = model_name
        self._device = device
        self._model = None
        self._dimension = 1024  # BGE-large-zh 输出 1024 维

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def _load_model(self):
        """延迟加载模型"""
        if self._model is not None:
            return

        logger.info(f"正在加载 Embedding 模型: {self._model_name} (device={self._device})")

        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name, device=self._device)
            logger.info(f"Embedding 模型加载完成，维度: {self._model.get_sentence_embedding_dimension()}")
        except Exception as e:
            logger.error(f"Embedding 模型加载失败: {e}")
            raise

    async def is_ready(self) -> bool:
        """检查模型是否已加载"""
        return self._model is not None

    async def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        await self._load_model()

        # sentence-transformers 的 encode 是同步的
        embedding = self._model.encode(
            text,
            normalize_embeddings=True,  # 归一化，便于余弦相似度计算
            show_progress_bar=False,
        )

        return embedding.tolist()

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量"""
        if not texts:
            return []

        await self._load_model()

        start_time = time.time()

        embeddings = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,  # 批量处理
        )

        elapsed = time.time() - start_time
        logger.debug(f"批量向量化: {len(texts)} 条文本, 耗时 {elapsed:.2f}s")

        return embeddings.tolist()

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(_prepare_query(self.model_name, query))


class CloudEmbedding(EmbeddingService):
    """
    云端 Embedding 服务 —— 使用 OpenAI 兼容 API

    优点：
    - 无需本地 GPU
    - 速度快

    缺点：
    - 需要 API Key
    - 数据上传到云端
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str = "text-embedding-3-small",
        dimension: int = 1536,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._model_name = model_name
        self._dimension = dimension
        self._client = None

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def _get_client(self):
        """延迟初始化 OpenAI 客户端"""
        if self._client is not None:
            return self._client

        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout=30.0,
        )
        logger.info(f"CloudEmbedding 客户端初始化完成: base_url={self._base_url}, model={self._model_name}")
        return self._client

    async def is_ready(self) -> bool:
        """测试服务是否可用"""
        try:
            await self.embed_text("test")
            return True
        except Exception as e:
            logger.warning(f"CloudEmbedding 不可用: {e}")
            return False

    async def embed_text(self, text: str) -> list[float]:
        """
        向量化单个文本

        Raises:
            ValueError: API 配置错误或请求失败时抛出，包含详细错误信息
        """
        client = await self._get_client()

        try:
            response = await client.embeddings.create(
                model=self._model_name,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"CloudEmbedding 请求失败: base_url={self._base_url}, "
                f"model={self._model_name}, error={error_msg}"
            )
            raise ValueError(f"向量化请求失败: {self._format_error(e)}") from e

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量向量化文本

        Raises:
            ValueError: API 配置错误或请求失败时抛出，包含详细错误信息
        """
        if not texts:
            return []

        client = await self._get_client()

        try:
            response = await client.embeddings.create(
                model=self._model_name,
                input=texts,
            )

            embeddings = sorted(response.data, key=lambda x: x.index)
            return [e.embedding for e in embeddings]
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"CloudEmbedding 批量请求失败: base_url={self._base_url}, "
                f"model={self._model_name}, count={len(texts)}, error={error_msg}"
            )
            raise ValueError(f"向量化请求失败: {self._format_error(e)}") from e

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(_prepare_query(self.model_name, query))

    def _format_error(self, e: Exception) -> str:
        """
        格式化错误信息，提取用户友好的错误消息

        Args:
            e: 原始异常

        Returns:
            格式化后的错误消息
        """
        error_str = str(e)

        try:
            from openai import APIStatusError, APIConnectionError, AuthenticationError

            if isinstance(e, AuthenticationError):
                return "API Key 无效或已过期，请检查 API Key 是否正确"
            elif isinstance(e, APIStatusError):
                status_code = e.status_code
                if status_code == 404:
                    return f"API 地址不存在 (404)，请检查 Base URL 是否正确（应以 /v1 结尾）"
                elif status_code == 429:
                    return "请求过于频繁，请稍后重试 (429)"
                elif status_code >= 500:
                    return f"服务器错误 ({status_code})，请稍后重试或联系服务商"
                else:
                    # 尝试从错误响应中提取 message
                    try:
                        if hasattr(e, 'response') and e.response is not None:
                            body = e.response.json()
                            if 'error' in body and 'message' in body['error']:
                                return f"错误 {status_code}: {body['error']['message']}"
                    except Exception:
                        pass
                    return f"API 请求失败 (状态码 {status_code})"
            elif isinstance(e, APIConnectionError):
                return "无法连接到 API 服务器，请检查网络连接和 Base URL"
        except ImportError:
            pass

        # 默认返回原始错误消息
        if len(error_str) > 200:
            return error_str[:200] + "..."
        return error_str


def create_embedding_service() -> EmbeddingService:
    """
    创建 Embedding 服务实例 —— 根据配置选择本地或云端

    读取 settings 中的 EMBEDDING_MODE 配置：
    - local: 使用本地 BGE 模型（sentence-transformers）
    - cloud: 使用云端 OpenAI 兼容 API
    """
    mode = getattr(settings, "EMBEDDING_MODE", "local")

    if mode == "cloud":
        base_url = getattr(settings, "EMBEDDING_CLOUD_BASE_URL", "")
        api_key = getattr(settings, "EMBEDDING_CLOUD_API_KEY", "")
        model = getattr(settings, "EMBEDDING_CLOUD_MODEL", "text-embedding-3-small")
        dimension = getattr(settings, "EMBEDDING_CLOUD_DIMENSION", 1536)

        if base_url and api_key and model:
            logger.info(f"创建云端 Embedding 服务: {model} @ {base_url}")
            return CloudEmbedding(
                base_url=base_url,
                api_key=api_key,
                model_name=model,
                dimension=dimension,
            )
        else:
            logger.warning("云端 Embedding 配置不完整，回退到本地模型")
            return LocalBGEEmbedding(
                model_name=settings.EMBEDDING_MODEL,
                device=settings.EMBEDDING_DEVICE,
            )
    else:
        logger.info(f"创建本地 Embedding 服务: {settings.EMBEDDING_MODEL}")
        return LocalBGEEmbedding(
            model_name=settings.EMBEDDING_MODEL,
            device=settings.EMBEDDING_DEVICE,
        )


class EmbeddingServiceProxy(EmbeddingService):
    """
    Embedding 服务代理 —— 支持运行时动态切换内部实现

    使用代理模式解决全局单例引用更新问题：
    - 所有模块导入的是同一个 Proxy 实例
    - 配置变更时只替换 Proxy 内部的 _impl
    - 所有已导入的地方自动使用新的实现

    这避免了 Python 中 from x import y 后重新赋值不生效的问题。
    """

    def __init__(self, initial_impl: EmbeddingService):
        self._impl = initial_impl
        logger.info(f"EmbeddingServiceProxy 初始化完成: {initial_impl.model_name}")

    def switch_to(self, new_impl: EmbeddingService):
        """
        切换到新的 Embedding 服务实现

        Args:
            new_impl: 新的 Embedding 服务实例
        """
        old_name = self._impl.model_name
        self._impl = new_impl
        logger.info(f"已切换 Embedding 服务: {old_name} -> {new_impl.model_name}")

    @property
    def impl(self) -> EmbeddingService:
        """获取当前内部实现（用于需要访问具体实现方法的场景）"""
        return self._impl

    async def embed_text(self, text: str) -> list[float]:
        """将单段文本转为向量"""
        return await self._impl.embed_text(text)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转为向量"""
        return await self._impl.embed_texts(texts)

    async def embed_query(self, query: str) -> list[float]:
        """使用当前实现的查询向量化规则。"""
        return await self._impl.embed_query(query)

    async def is_ready(self) -> bool:
        """检查服务是否就绪"""
        return await self._impl.is_ready()

    @property
    def dimension(self) -> int:
        """向量维度"""
        return self._impl.dimension

    @property
    def model_name(self) -> str:
        """模型名称"""
        return self._impl.model_name


# 全局 Embedding 服务实例（使用代理模式，支持运行时切换）
embedding_service = EmbeddingServiceProxy(create_embedding_service())
