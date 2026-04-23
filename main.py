"""
Optimized main entry point.
Replaces wfxl_openai_regst.py.

Improvements:
- Graceful shutdown with signal handlers
- Structured lifespan events
- Health check endpoint
- No os._exit(0) on shutdown
- uvicorn programmatic startup with config
"""

from __future__ import annotations

import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes import router
from app.config import get_config, reload_config
from models.database import db
from services.engine import RegEngine
from utils.logger import configure_logging, get_logger

logger = get_logger("main")

# Global engine instance (managed by lifespan)
_engine: RegEngine | None = None


def _signal_handler(signum: int, _) -> None:
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    if _engine and _engine.is_running():
        _engine.stop()
    sys.exit(0)


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init on start, cleanup on stop."""
    global _engine

    # Startup
    configure_logging(level=get_config().log_level)
    logger.info("=" * 50)
    logger.info("OpenAI Codex Manager — Optimized Edition")
    logger.info("=" * 50)

    db.init()
    _engine = RegEngine()
    logger.info("Database and engine initialized")

    yield

    # Shutdown
    logger.info("Shutting down gracefully...")
    if _engine and _engine.is_running():
        _engine.stop()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Wenfxl Codex Manager (Optimized)",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/static", StaticFiles(directory="static"), name="static")
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "engine_state": _engine._state.name if _engine else "unknown"}

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,  # We use loguru
        access_log=False,
    )
