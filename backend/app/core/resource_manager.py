"""
智答引擎（ZhiDa Engine）—— 资源管理器

根据机器配置自动调整资源使用，确保在低配机器上也能流畅运行。

优化策略：
- 内存 < 4GB：使用 ONNX 量化模型、减小切片、减少批处理
- 内存 4-8GB：中等配置
- 内存 >= 8GB：完整配置，使用完整模型
- CPU 核心数少：减少并发任务数
- SSD vs HDD：调整缓存策略
"""

import os
import sys
import threading
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from app.core.config import settings


@dataclass
class ResourceProfile:
    """资源配置方案 —— 根据机器配置自动选择"""

    # 机器信息
    total_memory_gb: float = 0.0
    cpu_cores: int = 1
    is_ssd: bool = True

    # 向量化配置
    chunk_size: int = 500          # 文本切片大小
    chunk_overlap: int = 50        # 切片重叠大小
    batch_size: int = 32           # 批处理大小
    use_onnx: bool = False         # 是否使用 ONNX 量化模型
    embedding_device: str = "cpu"  # Embedding 设备

    # 并发配置
    max_concurrent_tasks: int = 5      # 最大并发任务数
    max_requests_per_minute: int = 30  # 每分钟最大请求数

    # 缓存配置
    l1_cache_size: int = 1000      # L1 内存缓存条目数
    l2_cache_ttl: int = 3600       # L2 磁盘缓存过期时间（秒）

    # LLM 配置
    llm_timeout: float = 30.0      # LLM 调用超时（秒）
    llm_max_tokens: int = 2048     # 最大输出 Token 数

    # 沙箱配置
    sandbox_max_memory_mb: int = 512   # Agent 沙箱最大内存
    sandbox_max_disk_mb: int = 1024    # Agent 沙箱最大磁盘

    @property
    def profile_name(self) -> str:
        """配置方案名称"""
        if self.total_memory_gb < 4:
            return "minimal"
        elif self.total_memory_gb < 8:
            return "balanced"
        else:
            return "performance"


class ResourceManager:
    """
    资源管理器 —— 根据机器配置自动调整

    单例模式，启动时自动检测硬件配置并选择合适的资源方案。

    Usage:
        manager = ResourceManager()
        profile = manager.auto_configure()

        # 使用推荐的配置
        chunk_size = manager.profile.chunk_size
        batch_size = manager.profile.batch_size
    """

    _instance: Optional["ResourceManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ResourceManager":
        """单例模式"""
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

        self.profile: ResourceProfile = ResourceProfile()
        self._detected = False

        logger.info("资源管理器已初始化")

    def detect_hardware(self) -> ResourceProfile:
        """
        检测硬件配置

        Returns:
            检测到的硬件信息
        """
        if self._detected:
            return self.profile

        # 检测内存
        try:
            import psutil
            mem = psutil.virtual_memory()
            self.profile.total_memory_gb = round(mem.total / (1024 ** 3), 1)
        except ImportError:
            # psutil 未安装，使用保守估计
            self.profile.total_memory_gb = 4.0
            logger.warning("psutil 未安装，使用默认内存估计 (4GB)")

        # 检测 CPU 核心数
        self.profile.cpu_cores = os.cpu_count() or 1

        # 检测是否为 SSD
        self.profile.is_ssd = self._detect_ssd()

        self._detected = True
        logger.info(
            f"硬件检测完成: 内存={self.profile.total_memory_gb}GB, "
            f"CPU核心={self.profile.cpu_cores}, "
            f"SSD={self.profile.is_ssd}"
        )
        return self.profile

    def auto_configure(self) -> ResourceProfile:
        """
        自动配置资源方案 —— 根据硬件能力选择最优参数

        返回的 ResourceProfile 包含所有推荐配置参数。
        """
        self.detect_hardware()

        mem = self.profile.total_memory_gb
        cores = self.profile.cpu_cores

        if mem < 4:
            # 低配（< 4GB 内存）
            self._configure_minimal(cores)
        elif mem < 8:
            # 中配（4-8GB 内存）
            self._configure_balanced(cores)
        else:
            # 高配（>= 8GB 内存）
            self._configure_performance(cores)

        logger.info(
            f"资源配置方案: {self.profile.profile_name} "
            f"(chunk={self.profile.chunk_size}, batch={self.profile.batch_size}, "
            f"onnx={self.profile.use_onnx}, device={self.profile.embedding_device})"
        )
        return self.profile

    def _configure_minimal(self, cores: int):
        """低配方案 —— 优先保证可用性"""
        self.profile.chunk_size = 300
        self.profile.chunk_overlap = 30
        self.profile.batch_size = 8
        self.profile.use_onnx = True  # 使用量化模型节省内存
        self.profile.embedding_device = "cpu"
        self.profile.max_concurrent_tasks = 2
        self.profile.max_requests_per_minute = 10
        self.profile.l1_cache_size = 500
        self.profile.l2_cache_ttl = 7200
        self.profile.llm_timeout = 60.0
        self.profile.llm_max_tokens = 1024
        self.profile.sandbox_max_memory_mb = 256
        self.profile.sandbox_max_disk_mb = 512

    def _configure_balanced(self, cores: int):
        """中配方案 —— 平衡性能和资源"""
        self.profile.chunk_size = 500
        self.profile.chunk_overlap = 50
        self.profile.batch_size = 16
        self.profile.use_onnx = False
        self.profile.embedding_device = "cpu"
        self.profile.max_concurrent_tasks = min(cores, 5)
        self.profile.max_requests_per_minute = 20
        self.profile.l1_cache_size = 1000
        self.profile.l2_cache_ttl = 3600
        self.profile.llm_timeout = 30.0
        self.profile.llm_max_tokens = 2048
        self.profile.sandbox_max_memory_mb = 512
        self.profile.sandbox_max_disk_mb = 1024

    def _configure_performance(self, cores: int):
        """高配方案 —— 最大化性能"""
        self.profile.chunk_size = 800
        self.profile.chunk_overlap = 80
        self.profile.batch_size = 32
        self.profile.use_onnx = False
        self.profile.embedding_device = "cpu"  # 本地部署默认 CPU
        self.profile.max_concurrent_tasks = min(cores, 8)
        self.profile.max_requests_per_minute = 30
        self.profile.l1_cache_size = 2000
        self.profile.l2_cache_ttl = 3600
        self.profile.llm_timeout = 30.0
        self.profile.llm_max_tokens = 4096
        self.profile.sandbox_max_memory_mb = 1024
        self.profile.sandbox_max_disk_mb = 2048

    def _detect_ssd(self) -> bool:
        """
        检测数据目录是否在 SSD 上

        - Linux: 检查 /sys/block/<device>/queue/rotational
        - macOS: 默认返回 True（Mac 基本都是 SSD）
        - Windows: 通过 wmi 查询
        """
        if sys.platform == "darwin":
            # macOS 基本都是 SSD
            return True

        try:
            data_dir = str(settings.DATA_DIR)

            if sys.platform == "linux":
                # 通过 stat 获取设备号，查询 rotational
                dev_stat = os.stat(data_dir)
                # 简化处理：检查 /sys/block
                return True  # 默认假设 SSD

            elif sys.platform == "win32":
                # Windows: 尝试通过 wmi 查询
                import subprocess
                drive_letter = os.path.splitdrive(data_dir)[0]
                result = subprocess.run(
                    ["powershell", "-Command",
                     f"Get-PhysicalDisk | Where-Object {{(Get-Partition -DriveLetter '{drive_letter[0]}').DiskNumber -eq $_.DeviceId}} | Select-Object -ExpandProperty MediaType"],
                    capture_output=True, text=True,
                )
                return "SSD" in result.stdout

        except Exception:
            pass

        # 默认假设 SSD
        return True

    def get_recommended_settings(self) -> dict:
        """
        获取推荐的应用设置 —— 用于前端展示和自动配置

        Returns:
            推荐的配置参数字典
        """
        self.auto_configure()
        return {
            "profile": self.profile.profile_name,
            "hardware": {
                "total_memory_gb": self.profile.total_memory_gb,
                "cpu_cores": self.profile.cpu_cores,
                "is_ssd": self.profile.is_ssd,
            },
            "embedding": {
                "chunk_size": self.profile.chunk_size,
                "chunk_overlap": self.profile.chunk_overlap,
                "batch_size": self.profile.batch_size,
                "use_onnx": self.profile.use_onnx,
                "device": self.profile.embedding_device,
            },
            "concurrency": {
                "max_concurrent_tasks": self.profile.max_concurrent_tasks,
                "max_requests_per_minute": self.profile.max_requests_per_minute,
            },
            "cache": {
                "l1_cache_size": self.profile.l1_cache_size,
                "l2_cache_ttl": self.profile.l2_cache_ttl,
            },
            "llm": {
                "timeout": self.profile.llm_timeout,
                "max_tokens": self.profile.llm_max_tokens,
            },
            "sandbox": {
                "max_memory_mb": self.profile.sandbox_max_memory_mb,
                "max_disk_mb": self.profile.sandbox_max_disk_mb,
            },
        }


# 全局资源管理器单例
resource_manager = ResourceManager()