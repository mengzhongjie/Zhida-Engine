"""
智答引擎（ZhiDa Engine）—— 混合检索器

三路检索策略：
1. 向量检索（语义相似）—— ChromaDB 向量相似度匹配
2. 关键词检索（精确匹配）—— BM25 / jieba 分词匹配
3. 图检索（知识图谱）—— 实体关系检索（可选，模块开关控制）

混合检索 = 向量检索 + 关键词检索，去重合并后交给重排序。

父子块模式：
- 子块（Child）: 200字符，用于向量化索引
- 父块（Parent）: 800字符，存入数据库
- 检索时：找到子块 → 通过 parent_id 获取父块 → 返回父块作为完整上下文
"""

import re
import json
import math
from typing import Optional

import jieba
from loguru import logger

from app.services.knowledge.indexer import index_manager, IndexResult
from app.services.knowledge.text_normalizer import normalize_text


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
            "如何", "怎么", "什么", "哪些", "是否", "可以", "进行", "对应",
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

        normalized_keywords = [keyword.lower() for keyword in keywords]
        document_frequency = {
            keyword: sum(
                1 for chunk in chunks
                if keyword in normalize_text(chunk.get("text", "")).lower()
            )
            for keyword in normalized_keywords
        }
        corpus_size = max(len(chunks), 1)
        adjacent_phrases = [
            normalized_keywords[index] + normalized_keywords[index + 1]
            for index in range(len(normalized_keywords) - 1)
        ]
        scored = []
        for chunk in chunks:
            text = normalize_text(chunk.get("text", ""))
            lowered_text = text.lower()
            score = 0.0

            # 稀有术语比“开发”等高频词更有区分度，避免词频量纲压过 RAG 等专名。
            for keyword in normalized_keywords:
                if re.fullmatch(r"[a-z0-9_-]+", keyword):
                    count = len(re.findall(
                        rf"(?<![a-z0-9_-]){re.escape(keyword)}(?![a-z0-9_-])",
                        lowered_text,
                    ))
                else:
                    count = lowered_text.count(keyword)
                if not count:
                    continue
                idf = math.log((corpus_size + 1) / (document_frequency[keyword] + 1)) + 1.0
                length_boost = 1.0 + min(len(keyword), 8) / 8.0
                score += idf * length_boost * (1.0 + math.log1p(count))

            # “Agent工程师”等相邻复合词比散落命中更能表达用户意图。
            score += sum(5.0 for phrase in adjacent_phrases if phrase in lowered_text)

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
        vector_weight: float = 0.45,
        keyword_weight: float = 0.55,
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
            融合后的检索结果（包含父块内容）
        """
        normalized_query = normalize_text(query).strip()
        if not normalized_query:
            return []

        # 两路检索相互独立：向量漏召回时，父块全文关键词检索仍能恢复结果。
        vector_children = await index_manager.search_multi(
            knowledge_base_ids=knowledge_base_ids,
            query=normalized_query,
            top_k=top_k * 4,
        )
        vector_parents = await self._expand_to_parent_chunks(vector_children, knowledge_base_ids)
        keyword_parents = await self._search_all_parent_chunks(
            knowledge_base_ids,
            normalized_query,
            top_k=top_k * 4,
        )

        merged = self._rrf_merge(
            vector_results=vector_parents,
            keyword_results=keyword_parents,
            vector_weight=vector_weight,
            keyword_weight=keyword_weight,
        )
        self._boost_identity_filename_matches(merged, normalized_query)
        return merged[:top_k]

    def _boost_identity_filename_matches(
        self,
        results: list[IndexResult],
        query: str,
    ) -> None:
        """身份问题中，标题精确包含实体名是比正文缩写更强的消歧证据。"""
        if not re.search(r"(是谁|什么人|哪位|全名|真名|真实姓名|本名|身份)", query):
            return
        keywords = self._keyword_retriever.extract_keywords(query)
        if not keywords:
            return

        boosted = False
        for result in results:
            filename = str((result.metadata or {}).get("filename", "")).lower()
            for keyword in keywords:
                lowered_keyword = keyword.lower()
                if re.fullmatch(r"[a-z0-9_-]+", lowered_keyword):
                    # 中文标题会紧贴英文名（如“忆Tim有感”），这里按标题子串匹配。
                    matched = lowered_keyword in filename
                else:
                    matched = lowered_keyword in filename
                if matched:
                    result.score += 1.0
                    boosted = True
                    break

        if boosted:
            results.sort(key=lambda item: item.score, reverse=True)
            max_score = results[0].score
            for result in results:
                result.score = round(result.score / max_score, 4)

    async def _expand_to_parent_chunks(
        self,
        results: list[IndexResult],
        knowledge_base_ids: list[str],
    ) -> list[IndexResult]:
        """
        将子块检索结果扩展为父块内容

        策略：
        - 如果子块有 parent_id，从数据库获取对应的父块
        - 相同 parent_id 的多个子块合并为一个父块结果（取最高分）
        - 没有 parent_id 的结果保持原样（兼容旧数据）
        """
        if not results:
            return []

        parent_keys: list[tuple[int, str]] = []
        for r in results:
            pid = r.metadata.get("parent_id") if r.metadata else None
            document_id = r.metadata.get("document_id") if r.metadata else None
            if pid and document_id is not None:
                key = (int(document_id), str(pid))
                if key not in parent_keys:
                    parent_keys.append(key)

        if not parent_keys:
            return results

        parent_chunks = await self._fetch_parent_chunks(parent_keys, knowledge_base_ids)

        # 构建去重的父块结果列表
        seen_parents: set[tuple[int, str]] = set()
        final_results = []

        for r in results:
            pid = r.metadata.get("parent_id") if r.metadata else None
            document_id = r.metadata.get("document_id") if r.metadata else None
            key = (int(document_id), str(pid)) if pid and document_id is not None else None

            if key and key in parent_chunks:
                if key not in seen_parents:
                    seen_parents.add(key)
                    parent = parent_chunks[key]
                    parent_result = IndexResult(
                        chunk_id=f"document_{key[0]}:{key[1]}",
                        text=parent["text"],
                        metadata={
                            **parent["metadata"],
                            **(r.metadata or {}),
                            "is_parent": True,
                            "child_chunk_id": r.chunk_id,
                            "child_score": r.score,
                        },
                        score=r.score,
                    )
                    final_results.append(parent_result)
            else:
                # 没有父块的旧数据，保留原样
                final_results.append(r)

        return final_results

    async def _fetch_parent_chunks(
        self,
        parent_keys: list[tuple[int, str]],
        knowledge_base_ids: list[str],
    ) -> dict[tuple[int, str], dict]:
        """
        从数据库批量获取父块内容

        Returns:
            {(document_id, parent_id): {text, metadata}}
        """
        if not parent_keys:
            return {}

        fetched: dict[tuple[int, str], dict] = {}
        try:
            from app.core.database import async_session_factory
            from app.models.knowledge import DocumentChunk
            from sqlalchemy import select

            kb_ids = [int(index_manager.normalize_knowledge_base_id(kb_id)) for kb_id in knowledge_base_ids]
            document_ids = list({key[0] for key in parent_keys})
            parent_ids = list({key[1] for key in parent_keys})
            wanted = set(parent_keys)
            async with async_session_factory() as db:
                result = await db.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.knowledge_base_id.in_(kb_ids),
                        DocumentChunk.document_id.in_(document_ids),
                        DocumentChunk.parent_id.in_(parent_ids),
                    )
                )
                chunks = result.scalars().all()

                for chunk in chunks:
                    key = (chunk.document_id, chunk.parent_id)
                    if key not in wanted:
                        continue
                    metadata = self._parse_metadata(chunk.metadata_json)
                    fetched[key] = {
                        "text": chunk.content,
                        "metadata": {
                            **metadata,
                            "document_id": chunk.document_id,
                            "knowledge_base_id": chunk.knowledge_base_id,
                            "parent_id": chunk.parent_id,
                        },
                    }

        except Exception as e:
            logger.warning(f"获取父块失败: {e}")

        return fetched

    async def _search_all_parent_chunks(
        self,
        knowledge_base_ids: list[str],
        query: str,
        top_k: int,
    ) -> list[IndexResult]:
        """扫描父块语料做独立关键词召回；轻量规模下无需额外搜索服务。"""
        try:
            from app.core.database import async_session_factory
            from app.models.knowledge import DocumentChunk
            from sqlalchemy import select

            kb_ids = [int(index_manager.normalize_knowledge_base_id(kb_id)) for kb_id in knowledge_base_ids]
            async with async_session_factory() as db:
                result = await db.execute(
                    select(DocumentChunk).where(DocumentChunk.knowledge_base_id.in_(kb_ids))
                )
                chunks = result.scalars().all()

            candidates = []
            for chunk in chunks:
                metadata = self._parse_metadata(chunk.metadata_json)
                candidates.append({
                    "chunk_id": f"document_{chunk.document_id}:{chunk.parent_id}",
                    "text": normalize_text(chunk.content),
                    "metadata": {
                        **metadata,
                        "document_id": chunk.document_id,
                        "knowledge_base_id": chunk.knowledge_base_id,
                        "parent_id": chunk.parent_id,
                        "is_parent": True,
                    },
                })

            matched = self._keyword_retriever.search(candidates, query, top_k=top_k)
            return [
                IndexResult(
                    chunk_id=item["chunk_id"],
                    text=item["text"],
                    metadata=item["metadata"],
                    score=float(item["keyword_score"]),
                )
                for item in matched
            ]
        except Exception as exc:
            logger.warning(f"关键词父块检索失败: {exc}")
            return []

    @staticmethod
    def _parse_metadata(raw_metadata: Optional[str]) -> dict:
        if not raw_metadata:
            return {}
        try:
            value = json.loads(raw_metadata)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _result_key(result: IndexResult) -> tuple:
        metadata = result.metadata or {}
        document_id = metadata.get("document_id")
        parent_id = metadata.get("parent_id")
        if document_id is not None and parent_id:
            return ("parent", int(document_id), str(parent_id))
        return ("chunk", result.chunk_id)

    def _rrf_merge(
        self,
        vector_results: list[IndexResult],
        keyword_results: list[IndexResult],
        vector_weight: float = 0.45,
        keyword_weight: float = 0.55,
    ) -> list[IndexResult]:
        """用 RRF 融合不同量纲的排名，避免直接混合距离与词频分数。"""
        result_map: dict[tuple, IndexResult] = {}
        scores: dict[tuple, float] = {}
        rrf_k = 60

        for ranked_results, weight in (
            (vector_results, vector_weight),
            (keyword_results, keyword_weight),
        ):
            for rank, result in enumerate(ranked_results, start=1):
                key = self._result_key(result)
                result_map.setdefault(key, result)
                scores[key] = scores.get(key, 0.0) + weight / (rrf_k + rank)

        ordered_keys = sorted(scores, key=scores.get, reverse=True)
        max_score = scores[ordered_keys[0]] if ordered_keys else 1.0
        merged = []
        for key in ordered_keys:
            result = result_map[key]
            result.score = round(scores[key] / max_score, 4)
            merged.append(result)

        logger.debug(
            f"RRF 混合检索: 向量父块={len(vector_results)}, "
            f"关键词={len(keyword_results)}, 合并={len(merged)}"
        )

        return merged

# 全局混合检索器实例
hybrid_retriever = HybridRetriever()
