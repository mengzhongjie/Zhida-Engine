from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VisionConfigOut(BaseModel):
    id: Optional[int] = None
    name: str = "视觉模型"
    is_primary: bool = False
    is_fallback: bool = False
    enabled: bool = False
    base_url: str = ""
    model_name: str = ""
    api_key: str = ""
    last_test_at: Optional[datetime] = None
    last_test_success: Optional[bool] = None
    last_error: Optional[str] = None


class VisionConfigUpdate(BaseModel):
    name: str = Field("视觉模型", min_length=1, max_length=100)
    is_primary: bool = False
    is_fallback: bool = False
    enabled: bool = False
    base_url: str = Field("", max_length=500)
    model_name: str = Field("", max_length=200)
    api_key: Optional[str] = Field(None, max_length=1000)
