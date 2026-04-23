"""
Refactored FastAPI routes.
Replaces the 1200+ line monolithic api_routes.py.

Improvements:
- Dependency injection for auth and DB
- Pydantic v2 models
- Structured responses
- Async route handlers where beneficial
- No circular imports
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import AppConfig, get_config
from models.database import db
from services.engine import EngineState, RegEngine
from utils.logger import get_logger, get_recent_logs

logger = get_logger("api")
router = APIRouter()

# In-memory token store (production: use Redis or JWT)
_authorized_tokens: set[str] = set()


class LoginReq(BaseModel):
    password: str = Field(..., min_length=1)


class LoginResp(BaseModel):
    status: str
    token: str | None = None
    message: str | None = None


class StartResp(BaseModel):
    status: str
    message: str | None = None


class StatusResp(BaseModel):
    is_running: bool
    state: str
    stats: dict[str, Any] | None = None


class AccountsPageResp(BaseModel):
    total: int
    data: list[dict[str, Any]]


class ExportReq(BaseModel):
    emails: list[str]


class DeleteReq(BaseModel):
    emails: list[str]


def _get_engine() -> RegEngine:
    from services.engine import get_engine
    return get_engine()


def verify_token(authorization: str | None = None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing credentials")
    token = authorization.split(" ", 1)[1]
    if token not in _authorized_tokens:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return token


@router.post("/api/login", response_model=LoginResp)
async def login(req: LoginReq) -> LoginResp:
    cfg = get_config()
    if req.password == cfg.web_password:
        token = secrets.token_hex(16)
        _authorized_tokens.add(token)
        return LoginResp(status="success", token=token)
    return LoginResp(status="error", message="密码错误")


@router.get("/api/status", response_model=StatusResp)
async def get_status(
    token: str = Depends(verify_token),
    engine: RegEngine = Depends(_get_engine),
) -> StatusResp:
    return StatusResp(
        is_running=engine.is_running(),
        state=engine._state.name if hasattr(engine, "_state") else "UNKNOWN",
        stats=engine.stats.snapshot() if engine.is_running() else None,
    )


@router.post("/api/start", response_model=StartResp)
async def start_task(
    token: str = Depends(verify_token),
    engine: RegEngine = Depends(_get_engine),
) -> StartResp:
    if engine.is_running():
        return StartResp(status="error", message="任务已经在运行中！")
    ok = engine.start()
    return StartResp(
        status="success" if ok else "error",
        message=None if ok else "启动失败",
    )


@router.post("/api/stop", response_model=StartResp)
async def stop_task(
    token: str = Depends(verify_token),
    engine: RegEngine = Depends(_get_engine),
) -> StartResp:
    ok = engine.stop()
    return StartResp(
        status="success" if ok else "error",
        message=None if ok else "停止失败或引擎未运行",
    )


@router.get("/api/accounts")
async def list_accounts(
    page: int = 1,
    page_size: int = 50,
    hide_reg_only: str = "0",
    token: str = Depends(verify_token),
) -> AccountsPageResp:
    result = db.get_accounts_page(
        page=page,
        page_size=min(page_size, 200),
        hide_reg_only=hide_reg_only == "1",
    )
    return AccountsPageResp(**result)


@router.post("/api/accounts/export")
async def export_accounts(
    req: ExportReq,
    token: str = Depends(verify_token),
) -> dict[str, Any]:
    tokens = db.get_tokens_by_emails(req.emails)
    return {"status": "success", "count": len(tokens), "data": tokens}


@router.post("/api/accounts/delete")
async def delete_accounts(
    req: DeleteReq,
    token: str = Depends(verify_token),
) -> dict[str, Any]:
    deleted = db.delete_accounts(req.emails)
    return {"status": "success", "deleted": deleted}


@router.get("/api/logs")
async def get_logs(
    n: int = 100,
    token: str = Depends(verify_token),
) -> dict[str, Any]:
    return {"status": "success", "logs": get_recent_logs(min(n, 500))}
