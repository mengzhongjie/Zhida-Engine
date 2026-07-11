"""
智答引擎（ZhiDa Engine）—— MinerU 后端实现

提供两种部署模式：
1. EmbeddedMinerUBackend: 直接 import magic_pdf 调用 Python API（需安装 magic-pdf）
2. HttpMinerUBackend: 通过 HTTP 调用独立的 MinerU 服务（mineru-api 或 Docker）

当 magic-pdf 未安装时 EmbeddedMinerUBackend 静默降级，is_available() 返回 False。
"""

import asyncio
import inspect
import json
import os
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.services.knowledge.mineru.config import MinerUConfig


class MinerUBackend(ABC):
    """MinerU 后端抽象基类"""

    @abstractmethod
    async def parse(self, file_path: str) -> dict[str, Any]:
        """解析文件，返回 MinerU 原始输出字典

        输出格式:
        {
            "markdown": str,           # 完整 Markdown 文本
            "pages": list[str],        # 分页 Markdown 内容
            "tables": list[str],       # 表格（Markdown 格式）
            "metadata": dict,          # 解析元数据
            "images": list[str],       # 提取的图片路径
        }
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """检查后端是否可用"""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """健康检查"""
        ...

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """后端类型标识"""
        ...


class EmbeddedMinerUBackend(MinerUBackend):
    """嵌入式 MinerU 后端 —— 直接调用 magic_pdf Python API

    懒加载 magic_pdf，仅在首次调用时尝试 import。
    若未安装，is_available() 返回 False，不阻塞应用启动。
    """

    def __init__(self, config: MinerUConfig):
        self._config = config
        self._import_error: Optional[str] = None
        self._import_tried = False
        self._magic_pdf = None

    def _try_import(self) -> bool:
        """尝试导入 magic_pdf，仅尝试一次"""
        if self._import_tried:
            return self._magic_pdf is not None

        self._import_tried = True
        try:
            # 尝试导入 magic_pdf 核心模块
            import magic_pdf  # noqa: F401

            self._magic_pdf = True
            logger.info("MinerU 嵌入式后端已就绪 (magic-pdf)")
            return True
        except ImportError as e:
            self._import_error = str(e)
            logger.warning(
                "magic-pdf 未安装，MinerU 嵌入式模式不可用。"
                "如需使用，请执行: pip install 'magic-pdf>=1.3.0' 或使用 service 模式"
            )
            return False

    @property
    def backend_type(self) -> str:
        return "embedded"

    async def is_available(self) -> bool:
        return self._try_import()

    async def health_check(self) -> dict[str, Any]:
        available = await self.is_available()
        return {
            "backend": self.backend_type,
            "available": available,
            "import_error": self._import_error,
            "mode": "embedded",
            "config_backend": self._config.backend,
            "device": self._config.device,
        }

    async def parse(self, file_path: str) -> dict[str, Any]:
        """使用 magic_pdf 解析文件"""
        if not self._try_import():
            raise RuntimeError(
                f"MinerU 嵌入式后端不可用: {self._import_error or 'magic-pdf 未安装'}"
            )

        file_path = str(file_path)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        logger.info(
            f"MinerU 嵌入式解析: {Path(file_path).name} "
            f"(后端={self._config.backend}, 设备={self._config.device})"
        )

        # 创建临时输出目录
        with tempfile.TemporaryDirectory(prefix="mineru_") as tmpdir:
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(output_dir, exist_ok=True)

            try:
                # 在子线程中调用 aio_do_parse（magic_pdf 内部可能是同步操作）
                from magic_pdf.cli.common import aio_do_parse

                # MinerU 的部分版本将 aio_do_parse 实现为协程，另一些版本为
                # 同步函数。两种实现都要正确执行，不能把协程对象当成解析结果。
                if inspect.iscoroutinefunction(aio_do_parse):
                    parse_call = aio_do_parse(
                        pdf_path=file_path,
                        output_dir=output_dir,
                        backend=self._config.backend,
                        lang_list=self._config.languages,
                        return_md=True,
                    )
                    raw_result = await asyncio.wait_for(
                        parse_call,
                        timeout=self._config.service_timeout,
                    )
                else:
                    raw_result = await asyncio.wait_for(
                        asyncio.to_thread(
                            aio_do_parse,
                            pdf_path=file_path,
                            output_dir=output_dir,
                            backend=self._config.backend,
                            lang_list=self._config.languages,
                            return_md=True,
                        ),
                        timeout=self._config.service_timeout,
                    )
                raw_result = raw_result or {}

            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"MinerU 解析超时 ({self._config.service_timeout}s): {file_path}"
                )
            except Exception as e:
                logger.error(f"MinerU 解析失败: {e}")
                raise

            # 将原始输出转换为统一格式
            return self._normalize_output(raw_result, output_dir)

    def _normalize_output(self, raw: dict, output_dir: str) -> dict[str, Any]:
        """将 magic_pdf 原始输出标准化为统一格式

        不同版本的 magic_pdf 输出格式可能不同，这里做兼容处理。
        """
        result: dict[str, Any] = {
            "markdown": "",
            "pages": [],
            "tables": [],
            "metadata": {
                "parser": "mineru",
                "backend": self._config.backend,
                "mode": "embedded",
            },
            "images": [],
        }

        # 尝试多种可能的输出结构
        if isinstance(raw, dict):
            # 新版：直接包含 md_content 或 markdown 字段
            result["markdown"] = raw.get("md_content") or raw.get("markdown") or raw.get("text") or ""

            # pages
            result["pages"] = raw.get("pages") or raw.get("page_list") or raw.get("content_list") or []

            # tables - 从 markdown 中提取或直接从结果获取
            result["tables"] = raw.get("tables") or raw.get("structure", {}).get("tables") or []

            # images
            result["images"] = raw.get("images") or raw.get("image_list") or []

            # metadata
            meta = raw.get("metadata") or raw.get("page_info") or {}
            if isinstance(meta, dict):
                result["metadata"].update(meta)

        # MinerU 版本之间的输出目录结构不同：可能是 output.md，也可能位于
        # 文件名/模型名等嵌套目录。优先使用最长的 Markdown，避免只读到说明文件。
        markdown_files = list(Path(output_dir).rglob("*.md"))
        if markdown_files:
            candidates = []
            for md_path in markdown_files:
                try:
                    candidates.append(md_path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
            if candidates:
                result["markdown"] = max(candidates, key=len)

        result["pages"] = self._normalize_pages(result["pages"])
        result["tables"] = self._normalize_tables(result["tables"])

        # 收集图片
        img_dir = Path(output_dir) / "images"
        if img_dir.is_dir():
            result["images"] = [str(p) for p in img_dir.glob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]

        # 从 markdown 中提取表格
        if not result["tables"] and result["markdown"]:
            result["tables"] = self._extract_tables_from_markdown(result["markdown"])

        return result

    @staticmethod
    def _normalize_pages(pages: Any) -> list[str]:
        if not isinstance(pages, list):
            return []
        normalized = []
        for page in pages:
            if isinstance(page, str) and page.strip():
                normalized.append(page)
            elif isinstance(page, dict):
                text = page.get("md_content") or page.get("markdown") or page.get("text") or page.get("content")
                if isinstance(text, str) and text.strip():
                    normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_tables(tables: Any) -> list[str]:
        if not isinstance(tables, list):
            return []
        return [table if isinstance(table, str) else json.dumps(table, ensure_ascii=False) for table in tables]

    @staticmethod
    def _extract_tables_from_markdown(markdown: str) -> list[str]:
        """从 Markdown 文本中提取表格"""
        tables = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines):
            if "|" in lines[i] and i + 1 < len(lines) and "|" in lines[i + 1]:
                table_lines = []
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                if len(table_lines) >= 3:  # 至少表头 + 分隔行 + 一行数据
                    tables.append("\n".join(table_lines))
                continue
            i += 1
        return tables


class HttpMinerUBackend(MinerUBackend):
    """HTTP MinerU 后端 —— 通过 HTTP 调用独立的 MinerU 服务

    适用于：
    - Docker 部署的 mineru-api 服务
    - 远程 MinerU 集群
    - 避免 AGPL-3.0 传染性（进程隔离）
    """

    def __init__(self, config: MinerUConfig):
        self._config = config
        self._client: Optional[Any] = None  # httpx.AsyncClient

    async def _get_client(self):
        """惰性创建 httpx 客户端"""
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self._config.service_url,
                timeout=self._config.service_timeout,
                limits=httpx.Limits(max_keepalive_connections=2, max_connections=4),
            )
        return self._client

    @property
    def backend_type(self) -> str:
        return "http"

    async def is_available(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/health", timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    async def health_check(self) -> dict[str, Any]:
        try:
            client = await self._get_client()
            resp = await client.get("/health", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "backend": "http",
                    "available": True,
                    "service_url": self._config.service_url,
                    "service_info": data,
                }
            return {
                "backend": "http",
                "available": False,
                "service_url": self._config.service_url,
                "status_code": resp.status_code,
            }
        except Exception as e:
            return {
                "backend": "http",
                "available": False,
                "service_url": self._config.service_url,
                "error": str(e),
            }

    async def parse(self, file_path: str) -> dict[str, Any]:
        """通过 HTTP 调用 MinerU 服务解析文件

        使用 mineru-api 的异步任务接口：
        1. POST /tasks 上传文件，获得 task_id
        2. 轮询 GET /tasks/{task_id} 直到完成
        3. GET /tasks/{task_id}/result 获取结果
        """
        file_path = str(file_path)
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        logger.info(
            f"MinerU HTTP 解析: {Path(file_path).name} "
            f"(服务={self._config.service_url})"
        )

        client = await self._get_client()

        try:
            # 1. 上传文件创建任务
            with open(file_path, "rb") as f:
                resp = await client.post(
                    "/tasks",
                    files={"files": (os.path.basename(file_path), f, "application/octet-stream")},
                    data={"return_md": "true", "lang_list": ",".join(self._config.languages)},
                )
            resp.raise_for_status()
            task_data = resp.json()
            task_id = task_data.get("task_id") or task_data.get("id")
            if not task_id:
                raise RuntimeError(f"MinerU 服务返回无 task_id: {task_data}")

            # 2. 轮询等待完成
            poll_interval = 2
            max_retries = max(1, self._config.service_timeout // poll_interval)
            for attempt in range(max_retries):
                await asyncio.sleep(poll_interval)
                status_resp = await client.get(f"/tasks/{task_id}")
                status_resp.raise_for_status()
                status_data = status_resp.json()
                status = status_data.get("status", "").lower()

                if status == "completed":
                    break
                elif status in ("failed", "error"):
                    error_msg = status_data.get("error") or status_data.get("message", "未知错误")
                    raise RuntimeError(f"MinerU 解析失败: {error_msg}")
                elif status == "running" or status == "pending":
                    continue
                else:
                    logger.debug(f"MinerU 任务状态: {status}, 等待中 ({attempt + 1}/{max_retries})")
            else:
                raise TimeoutError(f"MinerU 解析超时 ({self._config.service_timeout}s): {file_path}")

            # 3. 获取结果
            result_resp = await client.get(f"/tasks/{task_id}/result")
            result_resp.raise_for_status()
            raw_result = result_resp.json()

        except asyncio.TimeoutError:
            raise TimeoutError(
                f"MinerU 服务请求超时 ({self._config.service_timeout}s): {self._config.service_url}"
            )
        except Exception as e:
            logger.error(f"MinerU HTTP 解析失败: {e}")
            # 如果是连接错误，提示服务未启动
            if "ConnectError" in str(e) or "Connection refused" in str(e):
                raise ConnectionError(
                    f"MinerU 服务不可达: {self._config.service_url}。"
                    f"请确保 MinerU 服务已启动，或设置 ZHIDA_MINERU_MODE=embedded"
                ) from e
            raise

        # 标准化输出
        return self._normalize_output(raw_result or {})

    def _normalize_output(self, raw: dict) -> dict[str, Any]:
        """将 mineru-api 输出标准化"""
        result: dict[str, Any] = {
            "markdown": "",
            "pages": [],
            "tables": [],
            "metadata": {
                "parser": "mineru",
                "backend": "http",
                "mode": "service",
            },
            "images": [],
        }

        # mineru-api 返回结构
        results = raw.get("results") or [raw]
        if results and isinstance(results, list):
            first = results[0] if isinstance(results[0], dict) else {}
            result["markdown"] = first.get("md_content") or first.get("markdown") or raw.get("md_content") or raw.get("markdown") or ""
        else:
            result["markdown"] = raw.get("md_content") or raw.get("markdown") or ""

        # 提取元数据
        if "status" in raw:
            result["metadata"]["task_status"] = raw["status"]
        if "duration" in raw:
            result["metadata"]["parse_time_ms"] = float(raw["duration"])
        if "page_count" in raw:
            result["metadata"]["total_pages"] = int(raw["page_count"])

        # 提取表格
        tables_raw = raw.get("tables") or []
        if isinstance(tables_raw, list):
            result["tables"] = [t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) for t in tables_raw]

        if not result["tables"] and result["markdown"]:
            result["tables"] = self._extract_tables_from_markdown(result["markdown"])

        return result

    @staticmethod
    def _extract_tables_from_markdown(markdown: str) -> list[str]:
        """从 Markdown 中提取表格"""
        tables = []
        lines = markdown.split("\n")
        i = 0
        while i < len(lines):
            if "|" in lines[i] and i + 1 < len(lines) and "|" in lines[i + 1]:
                table_lines = []
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i])
                    i += 1
                if len(table_lines) >= 3:
                    tables.append("\n".join(table_lines))
                continue
            i += 1
        return tables

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client:
            await self._client.aclose()
            self._client = None


def create_mineru_backend(config: MinerUConfig) -> MinerUBackend:
    """根据配置创建 MinerU 后端实例"""
    if config.mode == "service":
        logger.info("创建 MinerU HTTP 后端: {}", config.service_url)
        return HttpMinerUBackend(config)
    else:
        logger.info("创建 MinerU 嵌入式后端 (backend={}, device={})", config.backend, config.device)
        return EmbeddedMinerUBackend(config)
