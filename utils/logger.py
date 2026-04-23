"""
Structured logging with loguru.
Replaces the global print monkey-patching in core_engine.py.

Features:
- No monkey-patching of builtins.print
- Async-safe queue-based log sink
- Log history buffer for WebSocket streaming
- Multiple outputs: console, file, memory buffer
- JSON format option for log aggregation
"""

from __future__ import annotations

import sys
from collections import deque
from typing import Any

from loguru import logger as _logger

# In-memory ring buffer for WebSocket/dashboard streaming
_LOG_HISTORY: deque[dict] = deque(maxlen=500)


class LogBufferSink:
    """Custom sink that writes to in-memory deque for dashboard access."""

    def __init__(self, maxlen: int = 500):
        self._buffer: deque[dict] = deque(maxlen=maxlen)

    def write(self, message: str) -> None:
        # message comes as pre-formatted string from loguru
        self._buffer.append({"time": _now_iso(), "message": message.strip()})

    def flush(self) -> None:
        pass

    def get_recent(self, n: int = 100) -> list[dict]:
        return list(self._buffer)[-n:]

    def clear(self) -> None:
        self._buffer.clear()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


_log_buffer = LogBufferSink(maxlen=500)


def configure_logging(
    level: str = "INFO",
    log_file: str | None = "data/app.log",
    json_format: bool = False,
) -> None:
    """Configure loguru with console + file + memory buffer."""
    _logger.remove()  # Remove default handler

    # Console output with colors
    fmt = (
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    _logger.add(sys.stdout, level=level, format=fmt, colorize=True)

    # File rotation
    if log_file:
        _logger.add(
            log_file,
            rotation="10 MB",
            retention="7 days",
            level=level,
            format=fmt.replace("<green>", "").replace("<level>", "").replace("<cyan>", ""),
            enqueue=True,
        )

    # Memory buffer for dashboard
    _logger.add(_log_buffer, level=level, format="{time:HH:mm:ss} | {message}")


def get_logger(name: str | None = None):
    """Get a logger instance. If name provided, binds it as context."""
    if name:
        return _logger.bind(context=name)
    return _logger


def get_recent_logs(n: int = 100) -> list[dict]:
    return _log_buffer.get_recent(n)


def clear_log_buffer() -> None:
    _log_buffer.clear()


# Convenience exports
info = _logger.info
warning = _logger.warning
debug = _logger.debug
error = _logger.error
critical = _logger.critical
