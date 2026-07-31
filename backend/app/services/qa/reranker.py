"""
智答引擎（ZhiDa Engine）—— 重排序器

对检索结果进行精排，提升最相关内容的排名。

策略：
1. 交叉编码器重排序（Cross-Encoder Reranker）
2. 标题/关键词提权
3. 用户反馈调整（长期优化）

模块开关：settings.ENABLE_RERANK
"""

import asyncio
from loguru import logger

from app.core.config import settings
from app.services.knowledge.indexer import IndexResult


class Reranker:
    """
    重排序器 —— 对检索结果进行二次精排

    使用轻量级交叉编码器对检索结果重新打分。

    Usage:
        reranker = Reranker()

        results = await reranker.rerank(query, retrieved_chunks, top_k=5)
    """

    def __init__(self):
        self._model = None
        self._model_name = "BAAI/bge-reranker-v2-m3"  # 轻量级中文重排序模型

    async def _load_model(self):
        """延迟加载重排序模型（带超时，避免网络问题阻塞调用）"""
        if self._model is not None:
            return

        try:
            from sentence_transformers import CrossEncoder
            logger.info(f"正在加载重排序模型: {self._model_name}")
            self._model = await asyncio.wait_for(
                asyncio.to_thread(CrossEncoder, self._model_name),
                timeout=30,
            )
            logger.info("重排序模型加载完成")
        except asyncio.TimeoutError:
            logger.warning(f"重排序模型加载超时（30s），将使用规则排序")
            self._model = None
        except Exception as e:
            logger.warning(f"重排序模型加载失败: {e}，将使用规则排序")
            self._model = None

    async def rerank(
        self,
        query: str,
        results: list[IndexResult],
        top_k: int = 5,
    ) -> list[IndexResult]:
        """
        重排序 —— 对检索结果重新打分排序

        Args:
            query: 查询文本
            results: 检索结果列表
            top_k: 返回结果数量

        Returns:
            重排序后的结果
        """
        if not results:
            return []

        # 模块开关关闭时跳过重排序
        if not settings.ENABLE_RERANK:
            return results[:top_k]

        # 尝试使用交叉编码器重排序
        try:
            return await self._cross_encoder_rerank(query, results, top_k)
        except Exception as e:
            logger.warning(f"交叉编码器重排序失败: {e}，使用规则排序")
            return self._rule_based_rerank(query, results, top_k)

    async def _cross_encoder_rerank(
        self,
        query: str,
        results: list[IndexResult],
        top_k: int,
    ) -> list[IndexResult]:
        """使用交叉编码器重排序"""
        await self._load_model()

        if self._model is None:
            return self._rule_based_rerank(query, results, top_k)

        # 构建 (query, document) 对
        pairs = [(query, r.text) for r in results]

        # 交叉编码器打分
        scores = self._model.predict(pairs)

        # 更新分数并排序
        for i, score in enumerate(scores):
            results[i].score = round(float(score), 4)

        results.sort(key=lambda x: x.score, reverse=True)

        logger.debug(f"交叉编码器重排序: {len(results)} → {min(top_k, len(results))}")
        return results[:top_k]

    def _rule_based_rerank(
        self,
        query: str,
        results: list[IndexResult],
        top_k: int,
    ) -> list[IndexResult]:
        """
        基于规则的重排序 —— 交叉编码器不可用时的降级方案

        规则：
        1. 标题匹配提权
        2. 关键词密度提权
        3. 文本长度适中（不太短也不太长）
        """
        query_lower = query.lower()

        for r in results:
            text_lower = r.text.lower()
            bonus = 0.0

            # 标题匹配提权
            section_title = r.metadata.get("section_title", "")
            if section_title and any(kw in section_title for kw in query_lower.split()):
                bonus += 0.1

            # 关键词密度提权
            keyword_count = sum(1 for kw in query_lower.split() if kw in text_lower)
            if keyword_count > 0:
                bonus += keyword_count * 0.02

            # 文本长度适中（100-2000 字符最佳）
            text_len = len(r.text)
            if 100 <= text_len <= 2000:
                bonus += 0.05

            r.score = round(r.score + bonus, 4)

        results.sort(key=lambda x: x.score, reverse=True)

        return results[:top_k]

    @staticmethod
    def apply_user_feedback(
        results: list[IndexResult],
        feedback_history: dict,  # chunk_id → {"helpful": bool, "count": int}
    ) -> list[IndexResult]:
        """
        应用用户反馈调整 —— 长期优化检索精度

        用户标记为 "有帮助" 的结果提权，标记为 "无帮助" 的降权。

        Args:
            results: 检索结果列表
            feedback_history: 用户反馈历史

        Returns:
            调整后的结果
        """
        for r in results:
            feedback = feedback_history.get(r.chunk_id, {})
            if feedback.get("helpful"):
                # 有帮助：提权 10%
                r.score *= 1.1
            elif feedback.get("helpful") is False:
                # 无帮助：降权 10%
                r.score *= 0.9

        results.sort(key=lambda x: x.score, reverse=True)
        return results


# 全局重排序器实例
reranker = Reranker()
