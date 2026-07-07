"""
智答引擎（ZhiDa Engine）—— 查询缓存服务

三层缓存策略：
1. L1: 内存缓存（最快，进程内 dict + TTL）
2. L2: diskcache 持久化缓存（SQLite 后端，支持 TTL）
3. L3: 实际 LLM 调用（最慢，但保证准确）

缓存键 = 归一化问题文本的哈希，相同/相似问题命中缓存，不重复消耗 Token。
"""

import re
import hashlib
import time
import threading
from typing import Optional, Any
from dataclasses import dataclass, field

from loguru import logger
from diskcache import Cache

from app.core.config import settings


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl: int = 3600  # 默认 1 小时过期


class QueryCache:
    """
    三层查询缓存 —— 减少重复 Token 消耗

    相同或相似问题直接返回缓存结果，不调用 LLM。

    Usage:
        cache = QueryCache(cache_dir=settings.cache_dir)

        # 查询缓存
        result = await cache.get("问题文本")
        if result:
            return result

        # 未命中，调用 LLM 后写入缓存
        answer = await llm_gateway.chat("问题文本")
        await cache.set("问题文本", answer)
    """

    def __init__(self, cache_dir: str):
        # L1: 内存缓存（线程安全）
        self._memory_cache: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

        # L2: diskcache 持久化缓存
        self._disk_cache = Cache(cache_dir)

        # 缓存统计
        self._hits = 0
        self._misses = 0

    def _normalize_query(self, query: str) -> str:
        """
        归一化问题文本 —— 生成缓存键

        策略：
        1. 去除首尾空白
        2. 统一标点符号
        3. 截取前 200 字符（避免超长文本）
        4. SHA256 哈希
        """
        # 去除多余空白（包括中文之间的空格）
        normalized = " ".join(query.strip().split())
        # 去除中文字符之间的空格（如 "这是  一个  测试" → "这是一个测试"）
        normalized = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', normalized)

        # 统一中文标点
        replacements = {
            "？": "?", "！": "!", "，": ",", "。": ".", "；": ";", "：": ":",
            "（": "(", "）": ")", "“": '"', "”": '"', "‘": "'", "’": "'",
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        # 截取前 200 字符
        normalized = normalized[:200]

        # 哈希
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def get(self, query: str) -> Optional[str]:
        """
        查询缓存 —— 先查内存，再查磁盘

        Returns:
            缓存的答案，未命中返回 None
        """
        key = self._normalize_query(query)

        # L1: 内存缓存
        with self._lock:
            entry = self._memory_cache.get(key)
            if entry:
                if time.time() - entry.created_at < entry.ttl:
                    self._hits += 1
                    logger.debug(f"缓存命中 (L1 内存): {query[:50]}...")
                    return entry.value
                else:
                    # 过期，删除
                    del self._memory_cache[key]

        # L2: diskcache 持久化缓存
        disk_entry = self._disk_cache.get(key)
        if disk_entry:
            self._hits += 1
            logger.debug(f"缓存命中 (L2 磁盘): {query[:50]}...")

            # 回填 L1 内存缓存
            with self._lock:
                self._memory_cache[key] = CacheEntry(
                    value=disk_entry,
                    ttl=3600,
                )

            return disk_entry

        self._misses += 1
        return None

    async def set(self, query: str, answer: str, ttl: int = 3600):
        """
        写入缓存 —— 同时写入内存和磁盘

        Args:
            query: 原始问题文本
            answer: LLM 返回的答案
            ttl: 缓存过期时间（秒），默认 1 小时
        """
        key = self._normalize_query(query)

        # L1: 写入内存缓存
        with self._lock:
            self._memory_cache[key] = CacheEntry(value=answer, ttl=ttl)

        # L2: 写入磁盘缓存
        self._disk_cache.set(key, answer, expire=ttl)

        logger.debug(f"缓存写入: {query[:50]}... (TTL={ttl}s)")

    async def invalidate(self, query: str):
        """使指定查询的缓存失效"""
        key = self._normalize_query(query)

        with self._lock:
            self._memory_cache.pop(key, None)

        self._disk_cache.delete(key)

    async def clear(self):
        """清空所有缓存"""
        with self._lock:
            self._memory_cache.clear()

        self._disk_cache.clear()
        self._hits = 0
        self._misses = 0

        logger.info("缓存已清空")

    @property
    def stats(self) -> dict:
        """获取缓存统计"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": round(hit_rate * 100, 1),
            "memory_entries": len(self._memory_cache),
            "disk_entries": len(self._disk_cache),
        }


# 全局查询缓存实例
query_cache = QueryCache(cache_dir=settings.cache_dir)