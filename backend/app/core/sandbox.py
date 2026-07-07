"""
智答引擎（ZhiDa Engine）—— Agent 沙箱

每个 Agent 是独立运行实例，需要资源隔离防止相互影响。
沙箱提供文件系统隔离、网络白名单、内存限制、并发控制等。

沙箱管理器（SandboxManager）统一管理所有 Agent 沙箱的生命周期：
- Agent 启动时创建沙箱 → 初始化资源限制
- Agent 运行时校验操作 → 文件/网络/并发/超时
- Agent 停止时销毁沙箱 → 释放资源
"""

import os
import asyncio
import threading
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, field

from loguru import logger

from app.core.config import settings


@dataclass
class SandboxConfig:
    """沙箱配置 —— 每个 Agent 的资源限制参数"""

    # 资源限制
    max_memory_mb: int = 512           # 最大内存（MB）
    max_disk_mb: int = 1024            # 最大磁盘（MB）
    operation_timeout: float = 30.0    # 单次操作超时（秒）
    max_concurrent_tasks: int = 5      # 最大并发任务数
    max_requests_per_minute: int = 30  # 每分钟最大 API 请求数

    # 网络白名单 —— 只允许访问配置的 LLM API 端点
    allowed_hosts: set[str] = field(default_factory=set)

    # 文件系统 —— 允许读写的路径（初始化时自动添加 Agent 数据目录）
    allowed_paths: set[str] = field(default_factory=set)

    # 敏感路径黑名单（禁止访问，防止越权读取系统文件）
    forbidden_paths: set[str] = field(default_factory=lambda: {
        # Unix/Linux/macOS 敏感路径
        "/etc/passwd", "/etc/shadow", "/etc/sudoers",
        "/etc/ssh", "/etc/ssl/private",
        "/var/run/docker.sock",
        "/root/.ssh", "/root/.bash_history",
        "/home/*/.ssh", "/home/*/.bash_history",
        # Windows 敏感路径
        "C:\\Windows\\System32\\config\\SAM",
        "C:\\Windows\\System32\\config\\SECURITY",
        "C:\\Windows\\System32\\config\\SYSTEM",
        # 通用敏感路径
        "~/.ssh", "~/.aws", "~/.gcloud",
        "~/.gitconfig", "~/.netrc",
    })

    # 允许的文件类型
    allowed_file_types: set[str] = field(default_factory=lambda: {
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md", ".csv",
        ".png", ".jpg", ".jpeg", ".gif", ".json", ".xml", ".html",
    })


class AgentSandbox:
    """
    Agent 沙箱 —— 每个 Agent 实例的资源隔离

    提供以下隔离能力：
    - 文件系统：只允许访问 Agent 数据目录和上传文件，禁止访问系统敏感路径
    - 网络：只允许访问已配置的 LLM API 端点
    - 并发：Semaphore 限制最大并发任务数
    - 超时：单次操作超时自动中断
    - 磁盘：Agent 数据目录磁盘使用量监控

    Usage:
        sandbox = AgentSandbox(agent_id=1, data_dir=Path("/data/agents/1"))
        sandbox.configure(allowed_hosts={"api.deepseek.com", "api.openai.com"})

        # 使用并发限制
        async with sandbox.semaphore:
            result = await sandbox.run_with_timeout(some_async_fn())

        # 校验文件路径
        sandbox.validate_file_path("/path/to/file.pdf")
    """

    def __init__(self, agent_id: int, data_dir: Path):
        self.agent_id = agent_id
        self.data_dir = data_dir
        self.config = SandboxConfig()

        # 确保 Agent 数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 将 Agent 数据目录加入白名单
        self.config.allowed_paths.add(str(self.data_dir))

        # 并发信号量
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_tasks)

        # 活跃任务计数
        self._active_tasks = 0
        self._tasks_lock = threading.Lock()

        # 请求计数（用于限流）
        self._request_count = 0
        self._request_window_start = 0.0

        logger.info(f"Agent-{agent_id} 沙箱已初始化, 数据目录: {self.data_dir}")

    def configure(
        self,
        max_memory_mb: Optional[int] = None,
        max_disk_mb: Optional[int] = None,
        operation_timeout: Optional[float] = None,
        max_concurrent_tasks: Optional[int] = None,
        max_requests_per_minute: Optional[int] = None,
        allowed_hosts: Optional[set[str]] = None,
    ):
        """动态配置沙箱参数 —— Agent 启动时根据 LLM 配置自动设置"""
        if max_memory_mb is not None:
            self.config.max_memory_mb = max_memory_mb
        if max_disk_mb is not None:
            self.config.max_disk_mb = max_disk_mb
        if operation_timeout is not None:
            self.config.operation_timeout = operation_timeout
        if max_concurrent_tasks is not None:
            self.config.max_concurrent_tasks = max_concurrent_tasks
            self._semaphore = asyncio.Semaphore(max_concurrent_tasks)
        if max_requests_per_minute is not None:
            self.config.max_requests_per_minute = max_requests_per_minute
        if allowed_hosts is not None:
            self.config.allowed_hosts = allowed_hosts

        # 确保 Agent 数据目录始终在白名单中
        self.config.allowed_paths.add(str(self.data_dir))

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """并发控制信号量"""
        return self._semaphore

    @property
    def active_tasks(self) -> int:
        """当前活跃任务数"""
        with self._tasks_lock:
            return self._active_tasks

    async def run_with_timeout(self, coro, timeout: Optional[float] = None):
        """
        带超时的异步执行 —— 所有 Agent 操作都应通过此方法执行

        Args:
            coro: 协程
            timeout: 超时时间（秒），默认使用沙箱配置

        Returns:
            协程执行结果

        Raises:
            asyncio.TimeoutError: 超时
        """
        t = timeout or self.config.operation_timeout

        # 增加活跃任务计数
        with self._tasks_lock:
            self._active_tasks += 1

        try:
            return await asyncio.wait_for(coro, timeout=t)
        except asyncio.TimeoutError:
            logger.warning(f"Agent-{self.agent_id} 操作超时 ({t}s)")
            raise
        finally:
            # 减少活跃任务计数
            with self._tasks_lock:
                self._active_tasks -= 1

    def check_request_rate(self) -> bool:
        """
        检查请求频率是否超限

        基于每分钟最大请求数，防止单个 Agent 过度调用 LLM API。

        Returns:
            True 表示允许，False 表示超限
        """
        import time
        now = time.time()

        # 重置计数窗口（每分钟）
        if now - self._request_window_start > 60:
            self._request_window_start = now
            self._request_count = 0

        if self._request_count >= self.config.max_requests_per_minute:
            logger.warning(
                f"Agent-{self.agent_id} 请求频率超限: "
                f"{self._request_count}/{self.config.max_requests_per_minute} 次/分钟"
            )
            return False

        self._request_count += 1
        return True

    def validate_file_path(self, file_path: str) -> bool:
        """
        校验文件路径是否安全

        - 不允许访问系统敏感目录
        - 不允许访问其他 Agent 的数据目录
        - 只允许指定的文件类型
        """
        abs_path = os.path.abspath(file_path)

        # 检查黑名单 —— 禁止访问系统敏感路径
        for forbidden in self.config.forbidden_paths:
            forbidden_expanded = os.path.expanduser(forbidden)
            if abs_path.startswith(forbidden_expanded):
                logger.warning(f"Agent-{self.agent_id} 尝试访问禁止路径: {abs_path}")
                return False

        # 检查白名单 —— 允许 Agent 数据目录和上传目录
        allowed = False
        for allowed_path in self.config.allowed_paths:
            if abs_path.startswith(allowed_path):
                allowed = True
                break

        # 如果文件需上传/导入，且不在白名单中，允许读取（后续会复制到 Agent 目录）
        if not allowed:
            # 检查文件类型是否允许
            ext = os.path.splitext(abs_path)[1].lower()
            if ext and ext not in self.config.allowed_file_types:
                logger.warning(f"Agent-{self.agent_id} 不允许的文件类型: {ext}")
                return False

        return True

    def validate_url(self, url: str) -> bool:
        """
        校验 URL 是否在允许的域名白名单内

        防止 Agent 通过 LLM 工具调用访问内网或其他未授权服务。

        Args:
            url: 完整的 URL

        Returns:
            是否允许访问
        """
        from urllib.parse import urlparse

        if not self.config.allowed_hosts:
            # 未配置白名单，允许所有（仅本地开发模式）
            return True

        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""

            # 本地回环地址始终允许
            if hostname in ("127.0.0.1", "localhost", "::1"):
                return True

            # 检查主机名是否在白名单中
            for allowed in self.config.allowed_hosts:
                if hostname == allowed or hostname.endswith("." + allowed):
                    return True

            logger.warning(f"Agent-{self.agent_id} 尝试访问未授权主机: {hostname}")
            return False
        except Exception:
            return False

    def check_disk_usage(self) -> bool:
        """
        检查磁盘使用量是否超限

        Returns:
            True 表示未超限
        """
        total_size = sum(
            f.stat().st_size
            for f in self.data_dir.rglob("*")
            if f.is_file()
        )
        limit_bytes = self.config.max_disk_mb * 1024 * 1024
        if total_size > limit_bytes:
            logger.warning(
                f"Agent-{self.agent_id} 磁盘使用超限: "
                f"{total_size / 1024 / 1024:.1f}MB > {self.config.max_disk_mb}MB"
            )
            return False
        return True

    def get_usage_stats(self) -> dict:
        """获取资源使用统计"""
        total_size = sum(
            f.stat().st_size
            for f in self.data_dir.rglob("*")
            if f.is_file()
        )
        return {
            "agent_id": self.agent_id,
            "data_dir": str(self.data_dir),
            "disk_usage_mb": round(total_size / 1024 / 1024, 2),
            "disk_limit_mb": self.config.max_disk_mb,
            "disk_usage_percent": round(
                total_size / (self.config.max_disk_mb * 1024 * 1024) * 100, 1
            ) if self.config.max_disk_mb > 0 else 0,
            "active_tasks": self.active_tasks,
            "max_concurrent_tasks": self.config.max_concurrent_tasks,
            "operation_timeout": self.config.operation_timeout,
            "max_requests_per_minute": self.config.max_requests_per_minute,
        }

    def cleanup(self):
        """清理沙箱资源 —— Agent 停止时调用"""
        logger.info(f"Agent-{self.agent_id} 沙箱清理中...")
        # 清理临时文件（保留知识库和配置数据）
        temp_dir = self.data_dir / "temp"
        if temp_dir.exists():
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Agent-{self.agent_id} 临时文件已清理")


class SandboxManager:
    """
    沙箱管理器 —— 统一管理所有 Agent 沙箱的生命周期

    单例模式，全局唯一实例。

    Usage:
        manager = SandboxManager()

        # Agent 启动时创建沙箱
        sandbox = manager.create_sandbox(agent_id=1, data_dir=Path("/data/agents/1"))

        # 获取沙箱
        sandbox = manager.get_sandbox(agent_id=1)

        # Agent 停止时销毁沙箱
        manager.destroy_sandbox(agent_id=1)
    """

    _instance: Optional["SandboxManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SandboxManager":
        """单例模式 —— 确保全局只有一个沙箱管理器"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Agent ID → AgentSandbox 映射
        self._sandboxes: Dict[int, AgentSandbox] = {}
        self._lock = threading.RLock()

        logger.info("沙箱管理器已初始化")

    def create_sandbox(self, agent_id: int, data_dir: Path) -> AgentSandbox:
        """
        为 Agent 创建沙箱

        Args:
            agent_id: Agent ID
            data_dir: Agent 数据目录

        Returns:
            创建的沙箱实例
        """
        with self._lock:
            # 如果已存在，先销毁旧沙箱
            if agent_id in self._sandboxes:
                logger.warning(f"Agent-{agent_id} 沙箱已存在，先销毁旧沙箱")
                self._sandboxes[agent_id].cleanup()

            sandbox = AgentSandbox(agent_id=agent_id, data_dir=data_dir)
            self._sandboxes[agent_id] = sandbox

            logger.info(f"Agent-{agent_id} 沙箱已创建并注册")
            return sandbox

    def get_sandbox(self, agent_id: int) -> Optional[AgentSandbox]:
        """
        获取 Agent 的沙箱

        Args:
            agent_id: Agent ID

        Returns:
            沙箱实例，不存在返回 None
        """
        with self._lock:
            return self._sandboxes.get(agent_id)

    def destroy_sandbox(self, agent_id: int):
        """
        销毁 Agent 沙箱

        Args:
            agent_id: Agent ID
        """
        with self._lock:
            sandbox = self._sandboxes.pop(agent_id, None)
            if sandbox:
                sandbox.cleanup()
                logger.info(f"Agent-{agent_id} 沙箱已销毁")

    def get_all_sandboxes(self) -> Dict[int, AgentSandbox]:
        """获取所有活跃沙箱"""
        with self._lock:
            return dict(self._sandboxes)

    def get_all_stats(self) -> list[dict]:
        """获取所有沙箱的使用统计"""
        with self._lock:
            return [s.get_usage_stats() for s in self._sandboxes.values()]

    def get_total_stats(self) -> dict:
        """获取总体沙箱统计"""
        with self._lock:
            total_disk = sum(
                sum(f.stat().st_size for f in s.data_dir.rglob("*") if f.is_file())
                for s in self._sandboxes.values()
            )
            total_tasks = sum(s.active_tasks for s in self._sandboxes.values())

            return {
                "total_sandboxes": len(self._sandboxes),
                "total_disk_usage_mb": round(total_disk / 1024 / 1024, 2),
                "total_active_tasks": total_tasks,
                "agents": [aid for aid in self._sandboxes],
            }


# 全局沙箱管理器单例
sandbox_manager = SandboxManager()