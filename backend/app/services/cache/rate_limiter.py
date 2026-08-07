"""
智答引擎（ZhiDa Engine）—— 多层限流器

防止群聊刷屏，多层限流策略：
1. 令牌桶 —— 控制回复频率（QPS）
2. 滑动窗口 —— 控制短时间窗口内的回复次数
3. 问题冷却 —— 相同问题在冷却期内不重复回复
4. 静默时段 —— 指定时段内不自动回复

所有限流策略适用于群聊场景，私聊可放宽限制。
"""

import time
import threading
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

from loguru import logger

from app.core.config import settings


class RateLimitResult(str, Enum):
    """限流检查结果"""
    ALLOW = "allow"              # 允许回复
    RATE_LIMITED = "rate_limited"  # 频率限制
    COOLDOWN = "cooldown"         # 问题冷却中
    SILENT_PERIOD = "silent_period"  # 静默时段


@dataclass
class RateLimitConfig:
    """限流配置 —— 可针对不同渠道独立配置"""

    # 令牌桶配置
    tokens_per_minute: int = 10       # 每分钟最多回复次数
    burst_size: int = 3               # 突发允许的最大回复数

    # 滑动窗口配置
    window_size: int = 60             # 窗口大小（秒）
    max_replies_per_window: int = 5   # 窗口内最多回复次数

    # 问题冷却配置
    cooldown_seconds: int = 300       # 相同问题冷却时间（秒），默认 5 分钟

    # 静默时段配置
    silent_start_hour: int = 0        # 静默开始时间（小时），0 表示不启用
    silent_end_hour: int = 0          # 静默结束时间（小时），0 表示不启用

    # 私聊限流（相对宽松）
    private_chat_multiplier: float = 3.0  # 私聊限流倍数


class TokenBucket:
    """
    令牌桶限流器 —— 平滑控制回复频率

    令牌以固定速率生成，每次回复消耗一个令牌。
    桶满时丢弃多余令牌，桶空时拒绝请求。
    """

    def __init__(self, rate: int, capacity: int):
        """
        Args:
            rate: 令牌生成速率（个/分钟）
            capacity: 桶容量（最大令牌数）
        """
        self._rate = rate / 60.0  # 转为每秒速率
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """
        尝试消费令牌

        Returns:
            True 表示消费成功（允许请求），False 表示令牌不足（拒绝请求）
        """
        with self._lock:
            self._refill()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _refill(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数"""
        with self._lock:
            self._refill()
            return self._tokens


class SlidingWindow:
    """
    滑动窗口限流器 —— 控制短时间窗口内的请求次数

    记录每次请求的时间戳，检查窗口内的请求数是否超过阈值。
    """

    def __init__(self, window_size: int, max_requests: int):
        """
        Args:
            window_size: 窗口大小（秒）
            max_requests: 窗口内最大请求数
        """
        self._window_size = window_size
        self._max_requests = max_requests
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """
        检查是否允许请求

        Returns:
            True 表示允许，False 表示超出窗口限制
        """
        now = time.time()
        cutoff = now - self._window_size

        with self._lock:
            # 移除过期的请求记录
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            # 检查是否超出限制
            if len(self._timestamps) >= self._max_requests:
                return False

            # 记录本次请求
            self._timestamps.append(now)
            return True

    @property
    def current_count(self) -> int:
        """当前窗口内的请求数"""
        now = time.time()
        cutoff = now - self._window_size
        with self._lock:
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            return len(self._timestamps)


class QuestionCooldown:
    """
    问题冷却器 —— 相同问题在冷却期内不重复回复

    防止群内多人同时问同一个问题时，机器人重复回答。
    """

    def __init__(self, cooldown_seconds: int = 300):
        self._cooldown = cooldown_seconds
        self._recent_questions: dict[str, float] = {}  # 问题哈希 → 最后回复时间
        self._lock = threading.Lock()

    def is_cooling_down(self, question_hash: str) -> bool:
        """
        检查问题是否在冷却中

        Args:
            question_hash: 问题文本的哈希值

        Returns:
            True 表示冷却中（不应回复），False 表示可以回复
        """
        with self._lock:
            last_time = self._recent_questions.get(question_hash)
            if last_time is None:
                return False

            elapsed = time.time() - last_time
            return elapsed < self._cooldown

    def mark_answered(self, question_hash: str):
        """标记问题已回复，开始冷却"""
        with self._lock:
            self._recent_questions[question_hash] = time.time()

            # 清理过期记录（超过冷却时间 2 倍的记录）
            cutoff = time.time() - self._cooldown * 2
            self._recent_questions = {
                k: v for k, v in self._recent_questions.items()
                if v > cutoff
            }


class RateLimiter:
    """
    多层限流器 —— 组合令牌桶 + 滑动窗口 + 问题冷却 + 静默时段

    用于群聊场景，防止机器人刷屏。

    Usage:
        limiter = RateLimiter(config)

        # 检查是否允许回复
        result = limiter.check("chat_123", "问题哈希", is_private=False)
        if result == RateLimitResult.ALLOW:
            # 发送回复
            limiter.record("chat_123", "问题哈希")
        else:
            logger.info(f"限流: {result.value}")
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        self._config = config or RateLimitConfig()

        # 每个群聊/私聊独立的令牌桶
        self._buckets: dict[str, TokenBucket] = {}
        self._buckets_lock = threading.Lock()

        # 每个群聊/私聊独立的滑动窗口
        self._windows: dict[str, SlidingWindow] = {}
        self._windows_lock = threading.Lock()

        # 全局问题冷却
        self._cooldown = QuestionCooldown(self._config.cooldown_seconds)

    def _get_bucket(self, chat_id: str, is_private: bool) -> TokenBucket:
        """获取或创建令牌桶"""
        with self._buckets_lock:
            if chat_id not in self._buckets:
                rate = self._config.tokens_per_minute
                capacity = self._config.burst_size

                # 私聊放宽限制
                if is_private:
                    rate = int(rate * self._config.private_chat_multiplier)
                    capacity = int(capacity * self._config.private_chat_multiplier)

                self._buckets[chat_id] = TokenBucket(rate=rate, capacity=capacity)

            return self._buckets[chat_id]

    def _get_window(self, chat_id: str, is_private: bool) -> SlidingWindow:
        """获取或创建滑动窗口"""
        with self._windows_lock:
            if chat_id not in self._windows:
                max_replies = self._config.max_replies_per_window

                # 私聊放宽限制
                if is_private:
                    max_replies = int(max_replies * self._config.private_chat_multiplier)

                self._windows[chat_id] = SlidingWindow(
                    window_size=self._config.window_size,
                    max_requests=max_replies,
                )

            return self._windows[chat_id]

    def check(self, chat_id: str, question_hash: str, is_private: bool = False) -> RateLimitResult:
        """
        检查是否允许回复 —— 多层检查

        Args:
            chat_id: 群聊/私聊 ID
            question_hash: 问题文本的哈希值
            is_private: 是否为私聊

        Returns:
            RateLimitResult 枚举值
        """
        # 1. 静默时段检查
        if self._is_silent_period():
            return RateLimitResult.SILENT_PERIOD

        # 2. 问题冷却检查（仅群聊）
        if not is_private and self._cooldown.is_cooling_down(question_hash):
            return RateLimitResult.COOLDOWN

        # 3. 令牌桶检查
        bucket = self._get_bucket(chat_id, is_private)
        if not bucket.consume():
            return RateLimitResult.RATE_LIMITED

        # 4. 滑动窗口检查
        window = self._get_window(chat_id, is_private)
        if not window.allow():
            return RateLimitResult.RATE_LIMITED

        return RateLimitResult.ALLOW

    def record(self, chat_id: str, question_hash: str):
        """记录一次回复（用于问题冷却）"""
        self._cooldown.mark_answered(question_hash)

    def _is_silent_period(self) -> bool:
        """检查是否处于静默时段"""
        if self._config.silent_start_hour == 0 and self._config.silent_end_hour == 0:
            return False

        from app.core.time import beijing_now
        current_hour = beijing_now().hour

        start = self._config.silent_start_hour
        end = self._config.silent_end_hour

        if start < end:
            return start <= current_hour < end
        else:
            # 跨天静默（如 23:00 - 07:00）
            return current_hour >= start or current_hour < end

    def get_stats(self, chat_id: str, is_private: bool = False) -> dict:
        """获取限流统计"""
        bucket = self._get_bucket(chat_id, is_private)
        window = self._get_window(chat_id, is_private)

        return {
            "chat_id": chat_id,
            "available_tokens": round(bucket.available_tokens, 1),
            "window_requests": window.current_count,
            "window_max": self._config.max_replies_per_window,
            "is_silent_period": self._is_silent_period(),
        }


# 全局限流器实例
rate_limiter = RateLimiter()
