"""
智答引擎（ZhiDa Engine）—— 向量化服务

默认使用 BAAI/bge-large-zh-v1.5 本地模型（1024 维），
支持切换云端 Embedding API。

抽象 EmbeddingService 接口，方便切换不同实现。
"""

import time
from typing import Optional, Protocol
from abc import ABC, abstractmethod

from loguru import logger

from app.core.config import settings


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
        )
        return self._client

    async def is_ready(self) -> bool:
        try:
            client = await self._get_client()
            # 发送测试请求
            await client.embeddings.create(
                model=self._model_name,
                input="test",
            )
            return True
        except Exception:
            return False

    async def embed_text(self, text: str) -> list[float]:
        client = await self._get_client()

        response = await client.embeddings.create(
            model=self._model_name,
            input=text,
        )

        return response.data[0].embedding

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        client = await self._get_client()

        response = await client.embeddings.create(
            model=self._model_name,
            input=texts,
        )

        # 按索引排序
        embeddings = sorted(response.data, key=lambda x: x.index)
        return [e.embedding for e in embeddings]


def create_embedding_service() -> EmbeddingService:
    """
    创建 Embedding 服务实例 —— 根据配置选择本地或云端

    默认使用本地 BGE 模型，如果配置了云端 API 则使用云端。
    """
    # 默认使用本地 BGE 模型
    return LocalBGEEmbedding(
        model_name=settings.EMBEDDING_MODEL,
        device=settings.EMBEDDING_DEVICE,
    )


# 全局 Embedding 服务实例
embedding_service = create_embedding_service()