"""网页用户与管理员认证、兑换码及会话模型。"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class AdminRegistrationLock(Base):
    """管理员首次注册的一次性互斥锁。

    SQLite 没有跨请求的 ``SELECT ... FOR UPDATE``；用固定主键的插入竞争，
    让并发首次注册最多只有一个请求能继续创建管理员。
    """

    __tablename__ = "admin_registration_locks"
    id = Column(Integer, primary_key=True, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AccessCode(Base):
    __tablename__ = "access_codes"
    id = Column(Integer, primary_key=True)
    code_hash = Column(String(64), unique=True, nullable=False, index=True)
    code_hint = Column(String(12), nullable=False)
    # 用部署密钥加密保存，仅供已认证管理员重新复制；登录校验仍只使用哈希。
    code_ciphertext = Column(Text, nullable=True)
    daily_question_limit = Column(Integer, default=50, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="active", nullable=False, index=True)
    claimed_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AccessCodeAgent(Base):
    __tablename__ = "access_code_agents"
    id = Column(Integer, primary_key=True)
    access_code_id = Column(Integer, ForeignKey("access_codes.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)


class AccessCodeDailyUsage(Base):
    """兑换码每日额度；独立计数可在并发请求下原子扣减。"""

    __tablename__ = "access_code_daily_usage"
    access_code_id = Column(Integer, ForeignKey("access_codes.id", ondelete="CASCADE"), primary_key=True)
    usage_date = Column(String(10), primary_key=True)
    question_count = Column(Integer, default=0, nullable=False)


class WebUser(Base):
    __tablename__ = "web_users"
    id = Column(Integer, primary_key=True)
    # 一个激活码只能绑定一个匿名用户，数据库唯一约束是并发领取的最终防线。
    access_code_id = Column(Integer, ForeignKey("access_codes.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class CaptchaChallenge(Base):
    __tablename__ = "captcha_challenges"
    id = Column(String(48), primary_key=True)
    purpose = Column(String(20), nullable=False, index=True)
    answer_hash = Column(String(64), nullable=False)
    image_svg = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash = Column(String(64), primary_key=True)
    role = Column(String(20), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("web_users.id", ondelete="CASCADE"), nullable=True, index=True)
    admin_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(48), primary_key=True)
    owner_type = Column(String(20), nullable=False, index=True)
    owner_id = Column(Integer, nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    context_summary = Column(Text, nullable=True)
    summarized_through_history_id = Column(Integer, default=0, nullable=False)
    summary_updated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)
