"""
Auto-push newly registered accounts to Codex Hub.
Runs asynchronously so it never blocks the registration thread.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

import requests

from app.config import AppConfig
from utils.logger import get_logger

logger = get_logger("hub_pusher")

# Thread-safe queue for fire-and-forget pushes
_push_queue: list[Dict[str, Any]] = []
_queue_lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None


class HubPusher:
    """
    Singleton pusher that queues account pushes and drains them
    in a background thread to avoid blocking registration.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.cfg = config
        self._token: str | None = None
        self._token_acquired_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def enqueue(self, email: str, password: str, token_data: str | dict) -> None:
        """Fire-and-forget: add to queue, background worker will send."""
        if not self._enabled:
            return
        try:
            payload = self._build_payload(email, password, token_data)
        except Exception as exc:
            logger.warning(f"[Hub] Failed to build push payload: {exc}")
            return

        with _queue_lock:
            _push_queue.append(payload)
        self._ensure_worker()
        logger.info(f"[Hub] Queued account {email} for push")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @property
    def _enabled(self) -> bool:
        c = self.cfg or self._get_cfg()
        return c.hub.enable and c.hub.url and c.hub.admin_password

    def _get_cfg(self) -> AppConfig:
        from app.config import get_config
        return get_config()

    def _build_payload(
        self, email: str, password: str, token_data: str | dict
    ) -> Dict[str, Any]:
        if isinstance(token_data, str):
            token_data = json.loads(token_data)
        return {
            "email": email,
            "password": password,
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token", ""),
            "id_token": token_data.get("id_token", ""),
            "account_id": token_data.get("account_id", ""),
        }

    def _ensure_worker(self) -> None:
        global _worker_thread
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        _worker_thread.start()

    def _worker_loop(self) -> None:
        logger.info("[Hub] Background push worker started")
        while True:
            payload: Optional[Dict[str, Any]] = None
            with _queue_lock:
                if _push_queue:
                    payload = _push_queue.pop(0)
            if payload is None:
                time.sleep(2)
                continue
            self._send_one(payload)

    def _send_one(self, payload: Dict[str, Any]) -> None:
        cfg = self._get_cfg()
        hub_url = cfg.hub.url.rstrip("/")
        email = payload["email"]

        # Obtain / refresh admin token
        token = self._get_admin_token(cfg, hub_url)
        if not token:
            logger.error(f"[Hub] Cannot obtain admin token for {hub_url}")
            self._requeue(payload)
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if cfg.hub.api_key:
            headers["X-API-Key"] = cfg.hub.api_key

        url = f"{hub_url}/admin/accounts"
        for attempt in range(cfg.hub.retry_times):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                if resp.status_code == 200:
                    logger.info(f"[Hub] Pushed {email} successfully")
                    return
                if resp.status_code == 409:
                    logger.info(f"[Hub] {email} already exists in hub, skipped")
                    return
                if resp.status_code == 401:
                    logger.warning("[Hub] Token expired, will re-auth next attempt")
                    self._token = None
                logger.warning(
                    f"[Hub] Push attempt {attempt + 1} failed: {resp.status_code} {resp.text[:200]}"
                )
            except Exception as exc:
                logger.warning(f"[Hub] Push attempt {attempt + 1} error: {exc}")
            time.sleep(cfg.hub.retry_delay)

        logger.error(f"[Hub] Failed to push {email} after {cfg.hub.retry_times} retries")

    def _get_admin_token(self, cfg: AppConfig, hub_url: str) -> str | None:
        if self._token and (time.time() - self._token_acquired_at) < 3600:
            return self._token
        try:
            resp = requests.post(
                f"{hub_url}/admin/login",
                json={"password": cfg.hub.admin_password},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    self._token = data.get("token")
                    self._token_acquired_at = time.time()
                    return self._token
        except Exception as exc:
            logger.warning(f"[Hub] Login failed: {exc}")
        return None

    def _requeue(self, payload: Dict[str, Any]) -> None:
        with _queue_lock:
            _push_queue.insert(0, payload)


# Global singleton accessor
_pusher_instance: Optional[HubPusher] = None


def get_pusher() -> HubPusher:
    global _pusher_instance
    if _pusher_instance is None:
        _pusher_instance = HubPusher()
    return _pusher_instance


def push_account(email: str, password: str, token_data: str | dict) -> None:
    """Convenience helper called from database layer after save."""
    get_pusher().enqueue(email, password, token_data)
