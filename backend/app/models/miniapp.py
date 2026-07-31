"""小程序邀请制访问控制相关模型。"""

from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, UniqueConstraint

from app.core.database import Base


class MiniAppUser(Base):
    __tablename__ = "miniapp_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # OpenID 仅在服务端保存，绝不由客户端提交或返回给普通用户。
    openid = Column(String(128), nullable=False, unique=True, index=True)
    # 旧版本的首次邀请码，仅用于兼容已有数据；新领取记录见 InvitationClaim。
    invitation_id = Column(Integer, ForeignKey("invitations.id", ondelete="SET NULL"), nullable=True, unique=True)
    daily_question_limit = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    code_hint = Column(String(8), nullable=False, comment="仅用于后台识别的邀请码尾部")
    daily_question_limit = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    status = Column(String(20), default="active", nullable=False, index=True)  # active/revoked/claimed/expired
    # 旧版本字段；新领取关系使用 invitation_claims，允许同一用户领取多个邀请码。
    claimed_by_user_id = Column(Integer, ForeignKey("miniapp_users.id", ondelete="SET NULL"), nullable=True, unique=True)
    claimed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class InvitationClaim(Base):
    """邀请码的不可复用领取记录：一个邀请码只能领取一次，用户可领取多个。"""

    __tablename__ = "invitation_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invitation_id = Column(Integer, ForeignKey("invitations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("miniapp_users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    claimed_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class InvitationDailyUsage(Base):
    """每张已领取邀请码当天独立的问答消耗。"""

    __tablename__ = "invitation_daily_usage"
    __table_args__ = (UniqueConstraint("claim_id", "usage_date", name="uq_invitation_usage_claim_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("invitation_claims.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_date = Column(Date, nullable=False)
    question_count = Column(Integer, default=0, nullable=False)


class MiniAppSession(Base):
    __tablename__ = "miniapp_sessions"

    id = Column(String(36), primary_key=True)
    user_id = Column(Integer, ForeignKey("miniapp_users.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MiniAppDailyUsage(Base):
    __tablename__ = "miniapp_daily_usage"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_miniapp_usage_user_date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("miniapp_users.id", ondelete="CASCADE"), nullable=False, index=True)
    usage_date = Column(Date, nullable=False)
    question_count = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AdminLoginTicket(Base):
    __tablename__ = "admin_login_tickets"

    id = Column(String(48), primary_key=True)
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending/approved/expired
    approved_openid = Column(String(128), nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    token_hash = Column(String(64), primary_key=True)
    openid = Column(String(128), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
