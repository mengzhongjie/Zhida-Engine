"""
智答引擎（ZhiDa Engine）—— 混合检索器

三路检索策略：
1. 向量检索（语义相似）—— ChromaDB 向量相似度匹配
2. 关键词检索（精确匹配）—— BM25 / jieba 分词匹配
3. 图检索（知识图谱）—— 实体关系检索（可选，模块开关控制）

混合检索 = 向量检索 + 关键词检索，去重合并后交给重排序。
"""

import re
from typing import Optional
from collections import Counter

import jieba
from loguru import logger

from app.core.config import settings
from app.services.knowledge.indexer import index_manager, IndexResult


class KeywordRetriever:
    """
    关键词检索器 —— 基于 jieba 分词的精确匹配

    弥补向量检索对专有名词、数字、代码等精确匹配的不足。

    Usage:
        kr = KeywordRetriever()
        results = kr.search(chunks, "退换货政策")
    """

    def __init__(self):
        # 加载自定义词典
        self._stop_words = self._load_stop_words()

    @staticmethod
    def _load_stop_words() -> set:
        """加载停用词（常见无意义词）"""
        return {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
            "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
            "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "during",
        }

    def extract_keywords(self, query: str, top_k: int = 10) -> list[str]:
        """
        从查询中提取关键词

        Args:
            query: 查询文本
            top_k: 返回关键词数量

        Returns:
            关键词列表（按权重降序）
        """
        # 分词
        words = jieba.cut(query)

        # 过滤停用词和单字
        keywords = []
        for word in words:
            word = word.strip()
            if len(word) >= 2 and word.lower() not in self._stop_words:
                keywords.append(word)

        # 去重
        return list(dict.fromkeys(keywords))[:top_k]

    def search(
        self,
        chunks: list[dict],  # [{"text": ..., "metadata": ...}, ...]
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        关键词检索 —— 计算每个 chunk 与查询的关键词匹配度

        Args:
            chunks: 文本块列表
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            匹配结果列表（含 BM25 分数）
        """
        keywords = self.extract_keywords(query)

        if not keywords:
            return []

        scored = []
        for chunk in chunks:
            text = chunk.get("text", "")
            score = 0

            # 关键词匹配计分
            for kw in keywords:
                # 精确匹配加分
                count = text.lower().count(kw.lower())
                score += count * 2

                # 部分匹配（如"退换货"匹配"退换货政策"）
                if kw in text:
                    score += 5

            if score > 0:
                scored.append({
                    **chunk,
                    "keyword_score": score,
                })

        # 按分数排序
        scored.sort(key=lambda x: x["keyword_score"], reverse=True)

        return scored[:top_k]


class HybridRetriever:
    """
    混合检索器 —— 融合向量检索和关键词检索

    三路检索：
    1. 向量检索（语义相似）
    2. 关键词检索（精确匹配）
    3. 结果融合去重 + 重排序

    模块开关：settings.ENABLE_GRAPH_RETRIEVAL（图检索）

    Usage:
        retriever = HybridRetriever()

        results = await retriever.retrieve(
            knowledge_base_ids=["kb_1"],
            query="退换货政策是什么？",
            top_k=5,
        )
    """

    def __init__(self):
        self._keyword_retriever = KeywordRetriever()

    async def retrieve(
        self,
        knowledge_base_ids: list[str],
        query: str,
        top_k: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[IndexResult]:
        """
        混合检索 —— 融合向量和关键词结果

        Args:
            knowledge_base_ids: 知识库 ID 列表
            query: 查询文本
            top_k: 返回结果数量
            vector_weight: 向量检索权重（0-1）
            keyword_weight: 关键词检索权重（0-1）

        Returns:
            融合后的检索结果
        """
        # 1. 向量检索
        vector_results = await index_manager.search_multi(
            knowledge_base_ids=knowledge_base_ids,
            query=query,
            top_k=top_k * 2,  # 多取一些用于融合
        )

        # 2. 关键词检索
        # 获取所有 chunk 文本
        all_chunks = [
            {"text": r.text, "metadata": r.metadata, "chunk_id": r.chunk_id}
            for r in vector_results
        ]
        keyword_results = self._keyword_retriever.search(all_chunks, query, top_k=top_k * 2)

        # 3. 融合去重
        merged = self._merge_results(
            vector_results=vector_results,
            keyword_results=keyword_results,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )

        # 4. 截取 top_k
        return merged[:top_k]

    def _merge_results(
        self,
        vector_results: list[IndexResult],
        keyword_results: list[dict],
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> list[IndexResult]:
        """
        融合向量检索和关键词检索结果 —— 加权合并去重

        Args:
            vector_results: 向量检索结果
            keyword_results: 关键词检索结果
            vector_weight: 向量检索权重
            keyword_weight: 关键词检索权重

        Returns:
            融合后的结果（按综合分数降序）
        """
        # 构建 chunk_id → 结果 的映射
        result_map: dict[str, IndexResult] = {}

        # 向量检索结果
        for r in vector_results:
            result_map[r.chunk_id] = IndexResult(
                chunk_id=r.chunk_id,
                text=r.text,
                metadata=r.metadata,
                score=r.score * vector_weight,
            )

        # 关键词检索结果 —— 归一化分数后合并
        if keyword_results:
            # 归一化关键词分数（0-1）
            max_kw_score = max(r["keyword_score"] for r in keyword_results) if keyword_results else 1
            max_kw_score = max(max_kw_score, 1)

            for r in keyword_results:
                chunk_id = r.get("chunk_id", "")
                normalized_score = r["keyword_score"] / max_kw_score

                if chunk_id in result_map:
                    # 已存在，加权合并
                    result_map[chunk_id].score += normalized_score * keyword_weight
                else:
                    # 新结果
                    result_map[chunk_id] = IndexResult(
                        chunk_id=chunk_id,
                        text=r["text"],
                        metadata=r.get("metadata", {}),
                        score=normalized_score * keyword_weight,
                    )

        # 按综合分数排序
        merged = sorted(result_map.values(), key=lambda x: x.score, reverse=True)

        # 对分数四舍五入
        for r in merged:
            r.score = round(r.score, 4)

        logger.debug(
            f"混合检索融合: 向量={len(vector_results)}, "
            f"关键词={len(keyword_results)}, 合并={len(merged)}"
        )

        return merged

    async def retrieve_with_graph(
        self,
        knowledge_base_ids: list[str],
        query: str,
        top_k: int = 5,
    ) -> list[IndexResult]:
        """
        带图检索的混合检索 —— 三路融合

        如果模块开关 ENABLE_GRAPH_RETRIEVAL 关闭，等同于普通混合检索。
        """
        # 基础混合检索
        results = await self.retrieve(knowledge_base_ids, query, top_k=top_k)

        # 图检索（可选）
        if settings.ENABLE_GRAPH_RETRIEVAL:
            # TODO: 实现图检索
            # graph_results = await self._graph_retrieve(query, top_k)
            # results = self._merge_results(results, graph_results)
            pass

        return results


# 全局混合检索器实例
hybrid_retriever = HybridRetriever()