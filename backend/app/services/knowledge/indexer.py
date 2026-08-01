"""
智答引擎（ZhiDa Engine）—— 索引管理器

使用 ChromaDB 作为向量存储，管理文档切片的索引和检索。
每个知识库对应一个 ChromaDB Collection。
"""

import uuid
import re
from typing import Optional
from dataclasses import dataclass

from loguru import logger
import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.services.knowledge.embedder import embedding_service
from app.services.knowledge.splitter import TextChunk


@dataclass
class IndexResult:
    """索引结果"""
    chunk_id: str
    text: str
    metadata: dict
    score: float = 0.0  # 相似度分数


class IndexManager:
    INDEX_VERSION = "rag-index-v2"
    INDEX_SPACE = "cosine"
    """
    索引管理器 —— 管理 ChromaDB 向量存储

    每个知识库对应一个 Collection，支持：
    - 文档切片索引
    - 向量检索
    - 索引删除

    Usage:
        indexer = IndexManager()

        # 索引切片
        await indexer.index_chunks("kb_1", chunks)

        # 检索
        results = await indexer.search("kb_1", "问题文本", top_k=5)
    """

    def __init__(self):
        # 初始化 ChromaDB 客户端（持久化模式）
        self._client = chromadb.PersistentClient(
            path=settings.chroma_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,  # 关闭遥测
                allow_reset=True,
            ),
        )
        self._collections: dict[str, chromadb.Collection] = {}

    @staticmethod
    def normalize_knowledge_base_id(knowledge_base_id: str | int) -> str:
        """接受 ``5``/``kb_5``，拒绝嵌套前缀和任意集合名。"""
        raw_id = str(knowledge_base_id).strip()
        if raw_id.startswith("kb_"):
            raw_id = raw_id[3:]
        if not re.fullmatch(r"[1-9]\d*", raw_id):
            raise ValueError(f"无效的知识库 ID: {knowledge_base_id}")
        return raw_id

    def _get_collection(self, knowledge_base_id: str | int) -> chromadb.Collection:
        """
        获取或创建 Collection

        Args:
            knowledge_base_id: 知识库 ID（作为 Collection 名称）

        Returns:
            ChromaDB Collection
        """
        canonical_id = self.normalize_knowledge_base_id(knowledge_base_id)
        if canonical_id not in self._collections:
            safe_name = f"kb_{canonical_id}"

            try:
                collection = self._client.get_collection(name=safe_name)
            except Exception:
                fingerprint = self.current_fingerprint()
                collection = self._client.create_collection(
                    name=safe_name,
                    metadata={
                        "kb_id": canonical_id,
                        "hnsw:space": self.INDEX_SPACE,
                        "hnsw:M": 16,
                        "hnsw:construction_ef": 200,
                        "hnsw:search_ef": 64,
                        **fingerprint,
                    },
                )

            self._collections[canonical_id] = collection

        return self._collections[canonical_id]

    def current_fingerprint(self) -> dict:
        """当前嵌入服务对应的不可混用索引参数。"""
        return {
            "embedding_model": embedding_service.model_name,
            "embedding_dimension": embedding_service.dimension,
            "index_space": self.INDEX_SPACE,
            "index_version": self.INDEX_VERSION,
        }

    def get_document_chunk_count(self, knowledge_base_id: str | int, document_id: str | int) -> int:
        """按文档核验 Chroma 中仍存在的向量数。异常必须向上抛出。"""
        collection = self._get_collection(knowledge_base_id)
        result = collection.get(where={"document_id": int(document_id)}, include=[])
        return len(result.get("ids", []))

    # ================================================================
    # 索引操作
    # ================================================================

    async def index_chunks(
        self,
        knowledge_base_id: str,
        chunks: list[TextChunk],
        batch_size: int = 32,
    ) -> int:
        """
        索引文本切片 —— 向量化后写入 ChromaDB

        Args:
            knowledge_base_id: 知识库 ID
            chunks: 切片列表
            batch_size: 批量大小

        Returns:
            成功索引的切片数量
        """
        if not chunks:
            return 0

        collection = self._get_collection(knowledge_base_id)
        indexed_count = 0

        # 分批处理
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]

            # 向量化
            texts = [c.text for c in batch]
            embeddings = await embedding_service.embed_texts(texts)

            # 生成 ID
            ids = [f"chunk_{uuid.uuid4().hex[:12]}" for _ in batch]

            # 元数据（ChromaDB 只支持 str/int/float/bool）
            metadatas = []
            for c in batch:
                meta = {}
                for k, v in c.metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        meta[k] = v
                    else:
                        meta[k] = str(v)
                metadatas.append(meta)

            # 写入 ChromaDB
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

            indexed_count += len(batch)
            logger.debug(f"索引进度: {knowledge_base_id}: {indexed_count}/{len(chunks)}")

        logger.info(f"索引完成: {knowledge_base_id}: {indexed_count} 个切片")
        return indexed_count

    async def remove_document_chunks(
        self,
        knowledge_base_id: str,
        document_id: str | int,
    ) -> int:
        """
        删除文档的所有切片

        Args:
            knowledge_base_id: 知识库 ID
            document_id: 文档 ID
        """
        collection = self._get_collection(knowledge_base_id)

        before = self.get_document_chunk_count(knowledge_base_id, document_id)
        collection.delete(where={"document_id": int(document_id)})
        remaining = self.get_document_chunk_count(knowledge_base_id, document_id)
        if remaining:
            raise RuntimeError(f"向量删除核验失败：仍有 {remaining} 个切片")
        logger.info(f"已删除文档切片: {knowledge_base_id}/{document_id} ({before} 个)")
        return before

    async def clear_knowledge_base(self, knowledge_base_id: str):
        """清空知识库的所有索引"""
        try:
            collection = self._get_collection(knowledge_base_id)
            self._client.delete_collection(name=collection.name)
            canonical_id = self.normalize_knowledge_base_id(knowledge_base_id)
            self._collections.pop(canonical_id, None)
            logger.info(f"已清空知识库索引: {knowledge_base_id}")
        except Exception as e:
            logger.warning(f"清空知识库索引失败: {e}")

    # ================================================================
    # 检索操作
    # ================================================================

    async def search(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[IndexResult]:
        """
        向量检索 —— 查询最相似的切片

        Args:
            knowledge_base_id: 知识库 ID
            query: 查询文本
            top_k: 返回结果数量
            score_threshold: 最低相似度阈值（0-1），低于此值的过滤掉

        Returns:
            检索结果列表（按相似度降序）
        """
        collection = self._get_collection(knowledge_base_id)

        # 向量化查询文本
        query_embedding = await embedding_service.embed_query(query)

        # ChromaDB 检索
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        # 构建结果
        search_results = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else 0.0
                # 新索引使用 cosine；兼容旧 L2 索引中已归一化的向量。
                space = (collection.metadata or {}).get("hnsw:space", "l2")
                score = 1.0 - distance if space == "cosine" else 1.0 - (distance / 2.0)
                score = max(-1.0, min(1.0, score))

                if score_threshold is not None and score < score_threshold:
                    continue

                search_results.append(IndexResult(
                    chunk_id=chunk_id,
                    text=results["documents"][0][i] if results["documents"] else "",
                    metadata=results["metadatas"][0][i] if results["metadatas"] else {},
                    score=round(score, 4),
                ))

        return search_results

    async def search_multi(
        self,
        knowledge_base_ids: list[str],
        query: str,
        top_k: int = 5,
    ) -> list[IndexResult]:
        """
        多知识库检索 —— 在多个知识库中搜索，合并结果

        Args:
            knowledge_base_ids: 知识库 ID 列表
            query: 查询文本
            top_k: 每个知识库返回结果数量

        Returns:
            合并后的检索结果（按相似度降序）
        """
        all_results = []

        for kb_id in knowledge_base_ids:
            try:
                results = await self.search(kb_id, query, top_k=top_k)
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"知识库 {kb_id} 检索失败: {e}")
                continue

        # 按分数降序排序
        all_results.sort(key=lambda x: x.score, reverse=True)

        return all_results[:top_k]

    # ================================================================
    # 统计
    # ================================================================

    def get_kb_stats(self, knowledge_base_id: str) -> dict:
        """
        获取知识库统计信息

        Returns:
            {"chunk_count": ..., "collection_name": ...}
        """
        try:
            collection = self._get_collection(knowledge_base_id)
            return {
                "chunk_count": collection.count(),
                "collection_name": collection.name,
            }
        except Exception as e:
            logger.warning(f"获取知识库统计失败: {e}")
            return {"chunk_count": 0, "collection_name": knowledge_base_id}

    def list_knowledge_bases(self) -> list[str]:
        """列出所有知识库"""
        collections = self._client.list_collections()
        return [c.name for c in collections]


# 全局索引管理器实例
index_manager = IndexManager()
