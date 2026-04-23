"""
Registration worker with improved proxy rotation and error classification.
Replaces the inline thread logic scattered in core_engine.py.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Optional

from app.config import AppConfig
from models.database import db
from services.engine import EngineStats
from services.openai_register import RegistrationService
from utils.http_client import ErrorCategory, HttpClient, classify_error
from utils.logger import get_logger

logger = get_logger("registration")


class ProxyRotator:
    """Thread-safe proxy rotation with health tracking."""

    def __init__(self, config: AppConfig):
        self._cfg = config
        self._index = 0
        self._lock = threading.Lock()
        self._proxies: list[str] = []
        self._failed_proxies: dict[str, int] = {}
        self._build_pool()

    def _build_pool(self) -> None:
        if self._cfg.raw_proxy.enable and self._cfg.raw_proxy.proxy_list:
            self._proxies = self._cfg.raw_proxy.proxy_list
        elif self._cfg.proxy_pool.enable:
            # Would integrate with clash_manager for live proxy list
            self._proxies = []
        else:
            self._proxies = [self._cfg.default_proxy] if self._cfg.default_proxy else []

    def next(self) -> Optional[str]:
        if not self._proxies:
            return None
        with self._lock:
            # Skip recently failed proxies
            attempts = 0
            while attempts < len(self._proxies):
                proxy = self._proxies[self._index % len(self._proxies)]
                self._index += 1
                if self._failed_proxies.get(proxy, 0) < 3:
                    return proxy
                attempts += 1
            # All proxies marked bad, reset and return first
            self._failed_proxies.clear()
            return self._proxies[0]

    def mark_failed(self, proxy: str) -> None:
        with self._lock:
            self._failed_proxies[proxy] = self._failed_proxies.get(proxy, 0) + 1

    def mark_success(self, proxy: str) -> None:
        with self._lock:
            self._failed_proxies.pop(proxy, None)


class RegistrationWorker:
    def __init__(
        self,
        config: AppConfig,
        stats: EngineStats,
        stop_event: threading.Event,
        http_client: Optional[HttpClient] = None,
    ):
        self._cfg = config
        self._stats = stats
        self._stop = stop_event
        self._http = http_client or HttpClient()
        self._proxy_rotator = ProxyRotator(config)

    def loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._do_one_registration()
            except Exception as exc:
                logger.warning(f"Registration cycle error: {exc}")
                self._stats.increment("failed")

            # Adaptive sleep based on failure rate
            sleep_time = self._adaptive_sleep()
            for _ in range(int(sleep_time * 10)):
                if self._stop.is_set():
                    return
                time.sleep(0.1)

    def _do_one_registration(self) -> None:
        proxy = self._proxy_rotator.next()
        logger.debug(f"Using proxy: {proxy or 'direct'}")

        service = RegistrationService(
            config=self._cfg,
            stats=self._stats,
            http_client=self._http,
        )
        token_json, password = service.run(proxy=proxy)

        if token_json:
            logger.info("Registration successful, token saved to DB")
            self._proxy_rotator.mark_success(proxy)
        else:
            logger.warning("Registration failed")
            if proxy:
                self._proxy_rotator.mark_failed(proxy)

    def _adaptive_sleep(self) -> float:
        total = self._stats.success + self._stats.failed
        if total < 5:
            return random.uniform(self._cfg.normal_sleep_min, self._cfg.normal_sleep_max)
        fail_rate = self._stats.failed / total
        if fail_rate > 0.5:
            # Back off if failing too much
            return min(self._cfg.normal_sleep_max * 2, 60)
        return random.uniform(self._cfg.normal_sleep_min, self._cfg.normal_sleep_max)
