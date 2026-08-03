"""邀请码和小程序 API 的输入输出结构。"""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class InvitationCreate(BaseModel):
    daily_question_limit: int = Field(..., ge=1, le=1000)
    expires_at: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=500)

    @field_validator("expires_at")
    @classmethod
    def normalize_expiry_to_utc_naive(cls, value: Optional[datetime]) -> Optional[datetime]:
        """SQLite 存储无时区时间，统一把 ISO 8601 的时区时间转为 UTC。"""
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)


class InvitationDailyLimitUpdate(BaseModel):
    daily_question_limit: int = Field(..., ge=1, le=1000)


class InvitationOut(BaseModel):
    id: int
    code_hint: str
    daily_question_limit: int
    expires_at: Optional[datetime]
    note: Optional[str]
    status: str
    claimed_at: Optional[datetime]
    claimed_by_user_id: Optional[int]
    created_at: datetime
    usage_today: int = 0
    model_config = {"from_attributes": True}


class InvitationCreateOut(InvitationOut):
    invite_code: str = Field(..., description="只在创建时返回一次的邀请码明文")


class InviteClaimRequest(BaseModel):
    invite_code: str = Field(..., min_length=8, max_length=128)


class MiniAppAgentOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    avatar: Optional[str] = None


class MiniAppSessionCreate(BaseModel):
    agent_id: int
    title: Optional[str] = Field(None, max_length=200)


class MiniAppSessionOut(BaseModel):
    id: str
    agent_id: int
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class MiniAppAskRequest(BaseModel):
    agent_id: int
    question: str = Field(..., min_length=1, max_length=1000)
    session_id: Optional[str] = None
    request_id: Optional[str] = Field(None, min_length=12, max_length=80, description="同一次发送及其网络重试共用的幂等 ID")


class MiniAppUserOut(BaseModel):
    id: int
    daily_question_limit: int
    usage_today: int
    remaining_today: int


class AdminTicketOut(BaseModel):
    ticket_id: str
    qr_payload: str
    expires_at: datetime


class AdminTicketPollOut(BaseModel):
    status: str
    access_token: Optional[str] = None


class AdminTicketConfirm(BaseModel):
    ticket_id: str = Field(..., min_length=16, max_length=64)
