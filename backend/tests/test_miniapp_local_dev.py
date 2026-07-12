from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.miniapp.router import _validate_gateway_signature
from app.core.config import settings


def test_local_dev_openid_is_accepted_only_when_debug(monkeypatch):
    request = SimpleNamespace(headers={"X-Miniapp-Dev-Openid": "local-user"})
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "MINIPROGRAM_DEV_OPENID", "local-user")

    assert _validate_gateway_signature(request) == "local-user"


def test_local_dev_header_is_rejected_outside_debug(monkeypatch):
    request = SimpleNamespace(headers={"X-Miniapp-Dev-Openid": "local-user"})
    monkeypatch.setattr(settings, "DEBUG", False)
    monkeypatch.setattr(settings, "MINIPROGRAM_DEV_OPENID", "local-user")
    monkeypatch.setattr(settings, "MINIPROGRAM_GATEWAY_SECRET", "")

    with pytest.raises(HTTPException) as exc_info:
        _validate_gateway_signature(request)
    assert exc_info.value.status_code == 503
