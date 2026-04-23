"""
Refactored registration engine.
Replaces the monolithic core_engine.py with a service-oriented design.

Key improvements:
- State machine pattern (Idle -> Running -> Stopping -> Idle)
- Lock-free statistics via atomic counters (threading.Event / queue)
- Decoupled from global state
- Pluggable mode handlers (Normal, CPA, Sub2API)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

from app.config import AppConfig
from utils.logger import get_logger

logger = get_logger("engine")


class EngineState(Enum):
    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    ERROR = auto()


@dataclass
class EngineStats:
    success: int = 0
    failed: int = 0
    retries: int = 0
    pwd_blocked: int = 0
    phone_verify: int = 0
    start_time: float = 0.0
    target: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def increment(self, field_name: str, amount: int = 1) -> None:
        with self._lock:
            current = getattr(self, field_name, 0)
            setattr(self, field_name, current + amount)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self.success + self.failed
            elapsed = round(time.time() - self.start_time, 1) if self.start_time > 0 else 0
            return {
                "success": self.success,
                "failed": self.failed,
                "retries": self.retries,
                "pwd_blocked": self.pwd_blocked,
                "phone_verify": self.phone_verify,
                "total": total,
                "target": self.target if self.target > 0 else "∞",
                "success_rate": f"{round(self.success / total * 100, 2) if total > 0 else 0}%",
                "elapsed": f"{elapsed}s",
                "avg_time": f"{round(elapsed / self.success, 1) if self.success > 0 else 0}s",
                "progress_pct": f"{min(100, round(self.success / self.target * 100, 1)) if self.target > 0 else 0}%",
            }

    def reset(self) -> None:
        with self._lock:
            self.success = 0
            self.failed = 0
            self.retries = 0
            self.pwd_blocked = 0
            self.phone_verify = 0
            self.start_time = 0.0
            self.target = 0


class ModeHandler:
    """Base class for mode-specific logic."""

    def run(self, config: AppConfig, stats: EngineStats, stop_event: threading.Event) -> None:
        raise NotImplementedError


class NormalModeHandler(ModeHandler):
    def run(self, config: AppConfig, stats: EngineStats, stop_event: threading.Event) -> None:
        from services.registration import RegistrationWorker

        worker = RegistrationWorker(config, stats, stop_event)
        target = config.normal_target_count or 0
        stats.target = target

        threads = []
        thread_count = config.reg_threads if config.enable_multi_thread_reg else 1

        for _ in range(thread_count):
            if stop_event.is_set():
                break
            t = threading.Thread(target=worker.loop, daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=1)


class CPAModeHandler(ModeHandler):
    def run(self, config: AppConfig, stats: EngineStats, stop_event: threading.Event) -> None:
        from services.cpa_manager import CPAManager

        manager = CPAManager(config, stats, stop_event)
        manager.run()


class Sub2APIModeHandler(ModeHandler):
    def run(self, config: AppConfig, stats: EngineStats, stop_event: threading.Event) -> None:
        from services.sub2api_manager import Sub2APIManager

        manager = Sub2APIManager(config, stats, stop_event)
        manager.run()


class RegEngine:
    """
    Thread-safe registration engine with explicit state machine.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or get_config()
        self._state = EngineState.IDLE
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._stats = EngineStats()
        self._worker_thread: Optional[threading.Thread] = None
        self._handlers: dict[str, ModeHandler] = {
            "normal": NormalModeHandler(),
            "cpa": CPAModeHandler(),
            "sub2api": Sub2APIModeHandler(),
        }

    @property
    def stats(self) -> EngineStats:
        return self._stats

    def is_running(self) -> bool:
        with self._state_lock:
            return self._state == EngineState.RUNNING

    def is_stopping(self) -> bool:
        with self._state_lock:
            return self._state == EngineState.STOPPING

    def _set_state(self, state: EngineState) -> None:
        with self._state_lock:
            old = self._state
            self._state = state
            logger.info(f"Engine state: {old.name} -> {state.name}")

    def start(self, mode: str | None = None) -> bool:
        if self.is_running():
            logger.warning("Engine already running")
            return False

        self._stop_event.clear()
        self._stats.reset()
        self._stats.start_time = time.time()
        self._set_state(EngineState.RUNNING)

        handler = self._handlers.get(mode or self._detect_mode())
        if not handler:
            self._set_state(EngineState.ERROR)
            return False

        def _run():
            try:
                handler.run(self._config, self._stats, self._stop_event)
            except Exception as exc:
                logger.exception("Engine runtime error")
                self._set_state(EngineState.ERROR)
            finally:
                self._set_state(EngineState.IDLE)

        self._worker_thread = threading.Thread(target=_run, daemon=True)
        self._worker_thread.start()
        return True

    def stop(self) -> bool:
        if not self.is_running():
            return False
        self._set_state(EngineState.STOPPING)
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)
        self._set_state(EngineState.IDLE)
        return True

    def _detect_mode(self) -> str:
        if self._config.is_cpa_mode():
            return "cpa"
        if self._config.is_sub2api_mode():
            return "sub2api"
        return "normal"


def get_engine() -> RegEngine:
    """Factory for singleton engine instance."""
    return RegEngine()
