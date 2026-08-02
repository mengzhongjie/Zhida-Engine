"""
智答引擎（ZhiDa Engine）—— 安全工具集

本地桌面应用的安全防护：
- API Key 加密存储（AES，密钥派生自机器指纹）
- 输入清洗（防注入/XSS）
- 请求来源校验
- 日志脱敏
- 进程单实例锁（防止多开导致数据竞争）
- 数据目录权限加固
- 端口自动选择（避免冲突）
"""

import os
import sys
import re
import uuid
import fcntl
import hashlib
import base64
import socket
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.config import settings


# ============================================================
# API Key 加密/解密
# ============================================================

def _get_machine_id() -> str:
    """
    获取稳定机器标识。

    组合机器唯一标识符生成 32 字节密钥：
    - macOS: 硬件 UUID + 主机名
    - Windows: 机器 GUID + 主机名
    - Linux: machine-id + 主机名
    """
    import platform
    import socket

    machine_id = ""
    if sys.platform == "darwin":
        # macOS: 使用硬件 UUID
        import subprocess
        try:
            result = subprocess.run(
                ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True,
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    machine_id = line.split('"')[-2]
                    break
        except Exception:
            pass
    elif sys.platform == "win32":
        # Windows: 使用注册表 MachineGuid
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            machine_id = winreg.QueryValueEx(key, "MachineGuid")[0]
        except Exception:
            pass
    else:
        # Linux: 使用 machine-id
        try:
            with open("/etc/machine-id", "r") as f:
                machine_id = f.read().strip()
        except Exception:
            pass

    # 兜底：UUID + 主机名
    if not machine_id:
        machine_id = str(uuid.getnode()) + socket.gethostname()

    return machine_id


def _get_or_create_encryption_salt() -> bytes:
    """在应用数据目录保存随机盐，避免网络/DHCP 改变主机名导致密钥失效。"""
    salt_file = settings.DATA_DIR / ".encryption_salt"
    try:
        salt = salt_file.read_bytes()
        if len(salt) >= 32:
            return salt
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning(f"读取本地加密盐失败: {exc}")

    salt = os.urandom(32)
    try:
        # O_EXCL 防止多个启动进程同时覆盖同一个盐。
        descriptor = os.open(salt_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as file:
            file.write(salt)
            file.flush()
            os.fsync(file.fileno())
        return salt
    except FileExistsError:
        return salt_file.read_bytes()
    except OSError as exc:
        # 仅作为最后兜底；正常桌面数据目录可写时不会走到这里。
        logger.warning(f"创建本地加密盐失败，将使用机器标识兜底: {exc}")
        return b""


def _get_machine_fingerprint() -> bytes:
    """新格式密钥：稳定硬件标识 + 持久随机盐，不依赖可变主机名。"""
    raw = _get_machine_id().encode() + b":" + _get_or_create_encryption_salt() + b":ZhidaEngine"
    return hashlib.sha256(raw).digest()


def _get_legacy_machine_fingerprint() -> bytes:
    """兼容旧版“硬件 UUID + 主机名”格式，供尚未重新保存的旧密钥过渡。"""
    raw = f"{_get_machine_id()}:{socket.gethostname()}:ZhidaEngine"
    return hashlib.sha256(raw.encode()).digest()


def encrypt_api_key(api_key: str) -> str:
    """
    加密 API Key —— 使用 AES-256-GCM

    加密后的格式: base64(iv + ciphertext + tag)
    密钥派生自机器指纹，仅当前机器可解密。
    """
    if not api_key or not settings.API_KEY_ENCRYPT_ENABLED:
        return api_key

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import os as crypto_os

        aesgcm = AESGCM(_get_machine_fingerprint())

        # 生成随机 nonce（12 字节）
        nonce = crypto_os.urandom(12)

        # 加密
        ciphertext = aesgcm.encrypt(nonce, api_key.encode(), None)

        # 组合: nonce + ciphertext
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode()

    except ImportError:
        # cryptography 未安装，使用简单 Base64 编码（非安全，仅防明文暴露）
        logger.warning("cryptography 未安装，API Key 使用 Base64 编码存储")
        return base64.b64encode(api_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """
    解密 API Key

    如果是未加密的明文（不以加密前缀开头），直接返回。
    """
    if not encrypted or not settings.API_KEY_ENCRYPT_ENABLED:
        return encrypted

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        combined = base64.b64decode(encrypted)

        # 分离 nonce 和 ciphertext
        nonce = combined[:12]
        ciphertext = combined[12:]

        # 先使用稳定新格式；若失败，再尝试当前环境的旧格式以兼容历史配置。
        for key in (_get_machine_fingerprint(), _get_legacy_machine_fingerprint()):
            try:
                return AESGCM(key).decrypt(nonce, ciphertext, None).decode()
            except Exception:
                continue
        raise ValueError("无法使用当前或旧格式密钥解密")

    except ImportError:
        try:
            return base64.b64decode(encrypted).decode()
        except Exception:
            return encrypted
    except Exception:
        # 解密失败（可能换了机器），返回原始值
        logger.warning("API Key 解密失败，可能更换了机器")
        return encrypted


def mask_api_key(api_key: str) -> str:
    """
    脱敏 API Key —— 用于前端展示和日志

    示例: sk-abc123...xyz789 → sk-abc1****z789
    """
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]


# ============================================================
# 输入清洗
# ============================================================

# 危险字符模式（SQL 注入/XSS）
_DANGEROUS_PATTERNS = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),  # XSS
    re.compile(r"javascript:", re.IGNORECASE),  # XSS
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # XSS 事件
    re.compile(r"'\s*OR\s+'1'\s*=\s*'1", re.IGNORECASE),  # SQL 注入
    re.compile(r"'\s*;\s*DROP\s+TABLE", re.IGNORECASE),  # SQL 注入
    re.compile(r"'\s*;\s*DELETE\s+FROM", re.IGNORECASE),  # SQL 注入
    re.compile(r"'\s*UNION\s+SELECT", re.IGNORECASE),  # SQL 注入
]


def sanitize_input(text: str, max_length: int = 2000) -> str:
    """
    输入清洗 —— 去除危险字符，防注入/XSS

    Args:
        text: 原始输入
        max_length: 最大长度，超出截断

    Returns:
        清洗后的文本
    """
    if not text:
        return ""

    # 限制长度
    if len(text) > max_length:
        text = text[:max_length]

    # 去除危险模式
    for pattern in _DANGEROUS_PATTERNS:
        text = pattern.sub("", text)

    # 去除控制字符（保留换行、制表符）
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

    return text.strip()


# ============================================================
# 日志脱敏 Filter
# ============================================================

def log_sanitize_filter(record: dict) -> bool:
    """
    Loguru 日志脱敏 Filter

    自动脱敏日志中的 API Key 和敏感信息。
    """
    message = str(record.get("message", ""))

    # 脱敏 API Key 格式: sk-xxx / ak-xxx / api-key-xxx
    message = re.sub(
        r'(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+([a-zA-Z0-9]{4})',
        r'\1****\2',
        message,
    )
    message = re.sub(
        r'(api[-_]?key[=:]\s*["\']?)[a-zA-Z0-9\-_]+',
        r'\1****',
        message,
        flags=re.IGNORECASE,
    )

    record["message"] = message
    return True


# ============================================================
# 进程单实例锁
# ============================================================

_instance_lock_fd: Optional[int] = None


def acquire_instance_lock() -> bool:
    """
    获取进程单实例锁 —— 防止多开导致端口冲突和数据竞争

    使用文件锁（fcntl.flock），确保同一时间只有一个进程实例运行。
    锁文件位置: DATA_DIR/zhida.lock

    Returns:
        True 表示获取锁成功（首次启动），False 表示已有实例运行
    """
    global _instance_lock_fd

    lock_file = settings.DATA_DIR / "zhida.lock"

    try:
        _instance_lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o644)

        # 非阻塞获取排他锁
        fcntl.flock(_instance_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # 写入当前进程 PID
        os.write(_instance_lock_fd, str(os.getpid()).encode())
        os.fsync(_instance_lock_fd)

        logger.info(f"进程锁已获取, PID={os.getpid()}, lock_file={lock_file}")
        return True

    except (IOError, OSError):
        # 锁已被其他进程持有
        logger.warning(f"无法获取进程锁，可能已有实例在运行: {lock_file}")
        if _instance_lock_fd is not None:
            os.close(_instance_lock_fd)
            _instance_lock_fd = None
        return False


def release_instance_lock():
    """
    释放进程单实例锁

    应用退出时调用，释放锁文件允许下次启动。
    """
    global _instance_lock_fd

    if _instance_lock_fd is not None:
        try:
            fcntl.flock(_instance_lock_fd, fcntl.LOCK_UN)
            os.close(_instance_lock_fd)
        except Exception:
            pass
        finally:
            _instance_lock_fd = None

        # 尝试删除锁文件
        lock_file = settings.DATA_DIR / "zhida.lock"
        try:
            os.remove(lock_file)
        except Exception:
            pass

        logger.info("进程锁已释放")


# ============================================================
# 数据目录权限加固
# ============================================================

def secure_data_directory():
    """
    加固数据目录权限 —— 仅当前用户可读写

    - Unix/macOS: chmod 0o700
    - Windows: 通过 ACL 限制（使用 icacls）
    """
    data_dir = str(settings.DATA_DIR)
    log_dir = settings.log_dir

    if sys.platform == "win32":
        # Windows: 使用 icacls 限制权限
        try:
            import subprocess
            # 仅授予当前用户完全控制权限，移除其他用户
            subprocess.run(
                ["icacls", data_dir, "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', 'Everyone')}:(OI)(CI)F"],
                capture_output=True, check=False,
            )
            subprocess.run(
                ["icacls", log_dir, "/inheritance:r", "/grant:r",
                 f"{os.environ.get('USERNAME', 'Everyone')}:(OI)(CI)F"],
                capture_output=True, check=False,
            )
            logger.info(f"Windows 数据目录权限已加固: {data_dir}")
        except Exception as e:
            logger.warning(f"Windows 数据目录权限加固失败: {e}")
    else:
        # Unix/Linux/macOS: chmod 0o700
        try:
            os.chmod(data_dir, 0o700)
            os.chmod(log_dir, 0o700)
            logger.info(f"数据目录权限已加固 (0o700): {data_dir}")
        except Exception as e:
            logger.warning(f"数据目录权限加固失败: {e}")


# ============================================================
# 端口自动选择
# ============================================================

def find_available_port(
    start_port: int = 18900,
    max_attempts: int = 100,
    host: str = "127.0.0.1",
) -> int:
    """
    自动查找可用端口 —— 避免端口冲突

    从 start_port 开始逐个尝试，找到第一个可用的端口。

    Args:
        start_port: 起始端口号
        max_attempts: 最大尝试次数
        host: 绑定的主机地址

    Returns:
        可用端口号

    Raises:
        RuntimeError: 所有端口都被占用
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                logger.info(f"找到可用端口: {port}")
                return port
        except OSError:
            continue

    raise RuntimeError(f"无法找到可用端口 ({start_port}-{start_port + max_attempts})")


# ============================================================
# 安全文件删除
# ============================================================

def secure_delete(file_path: str, passes: int = 1):
    """
    安全删除文件 —— 覆写后删除

    适用于删除包含敏感信息的临时文件（如 API Key 缓存、日志片段）。

    Args:
        file_path: 文件路径
        passes: 覆写次数（默认 1 次，高安全场景可设为 3 次）
    """
    path = Path(file_path)
    if not path.exists():
        return

    try:
        file_size = path.stat().st_size

        if file_size > 0:
            # 多次覆写随机数据
            for _ in range(passes):
                with open(path, "wb") as f:
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())

        # 删除文件
        path.unlink()
        logger.debug(f"安全删除文件: {file_path}")

    except Exception as e:
        logger.warning(f"安全删除文件失败: {file_path}, {e}")
        # 兜底：普通删除
        try:
            path.unlink()
        except Exception:
            pass
