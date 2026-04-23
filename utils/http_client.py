"""
Unified HTTP client with smart retry, backoff, and circuit breaker patterns.
Replaces the scattered retry logic in register.py, core_engine.py, etc.

Features:
- Exponential backoff with jitter
- Per-domain circuit breaker (fail-fast after N consecutive failures)
- Session reuse (connection pooling)
- Structured error classification
- Async-compatible interface
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from curl_cffi import requests as curl_requests

T = TypeVar("T")


class ErrorCategory(Enum):
    TRANSIENT = "transient"      # Retryable: timeout, 502, 503
    AUTH = "auth"                # 401, 403 — no retry
    RATE_LIMIT = "rate_limit"    # 429 — retry with longer backoff
    CLIENT = "client"            # 4xx — no retry
    NETWORK = "network"          # DNS, connection refused — retry
    UNKNOWN = "unknown"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retry_on: set[ErrorCategory] = field(
        default_factory=lambda: {
            ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMIT, ErrorCategory.NETWORK
        }
    )


@dataclass
class CircuitBreaker:
    """Simple circuit breaker per domain."""
    failure_threshold: int = 5
    recovery_timeout: float = 30.0

    _failures: dict[str, list[float]] = field(default_factory=dict)
    _open_circuits: set[str] = field(default_factory=set)

    def record_failure(self, domain: str) -> None:
        now = time.time()
        self._failures.setdefault(domain, [])
        self._failures[domain].append(now)
        # Clean old failures outside window
        window = self.failure_threshold * self.recovery_timeout
        self._failures[domain] = [t for t in self._failures[domain] if now - t < window]
        if len(self._failures[domain]) >= self.failure_threshold:
            self._open_circuits.add(domain)

    def record_success(self, domain: str) -> None:
        self._failures.pop(domain, None)
        self._open_circuits.discard(domain)

    def is_open(self, domain: str) -> bool:
        if domain in self._open_circuits:
            # Check if recovery timeout passed
            last_failures = self._failures.get(domain, [])
            if last_failures and time.time() - last_failures[-1] > self.recovery_timeout:
                self._open_circuits.discard(domain)
                return False
            return True
        return False


def classify_error(exc: Exception, status_code: int | None = None) -> ErrorCategory:
    if status_code is not None:
        if status_code in (502, 503, 504):
            return ErrorCategory.TRANSIENT
        if status_code == 429:
            return ErrorCategory.RATE_LIMIT
        if status_code in (401, 403):
            return ErrorCategory.AUTH
        if 400 <= status_code < 500:
            return ErrorCategory.CLIENT
        if status_code >= 500:
            return ErrorCategory.TRANSIENT
    msg = str(exc).lower()
    if any(k in msg for k in ("timeout", "timed out", "slow down")):
        return ErrorCategory.TRANSIENT
    if any(k in msg for k in ("connection", "refused", "dns", "resolve")):
        return ErrorCategory.NETWORK
    if "rate" in msg or "too many" in msg:
        return ErrorCategory.RATE_LIMIT
    return ErrorCategory.UNKNOWN


def _backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    delay = policy.base_delay * (policy.exponential_base ** attempt)
    delay = min(delay, policy.max_delay)
    if policy.jitter:
        delay = delay * (0.5 + random.random())
    return delay


class HttpClient:
    """
    Unified HTTP client wrapping curl_cffi with retry and circuit breaker.
    """

    def __init__(
        self,
        default_timeout: int = 30,
        default_retry: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self._session = curl_requests.Session()
        self._default_timeout = default_timeout
        self._default_retry = default_retry or RetryPolicy()
        self._cb = circuit_breaker or CircuitBreaker()

    @property
    def session(self) -> curl_requests.Session:
        return self._session

    def _extract_domain(self, url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc or "unknown"

    def request(
        self,
        method: str,
        url: str,
        *,
        retry: RetryPolicy | None = None,
        **kwargs: Any,
    ) -> curl_requests.Response:
        """Execute HTTP request with retry and circuit breaker."""
        policy = retry or self._default_retry
        domain = self._extract_domain(url)

        if self._cb.is_open(domain):
            raise RuntimeError(f"Circuit breaker OPEN for {domain}")

        last_exc: Exception | None = None
        status_code: int | None = None

        for attempt in range(policy.max_retries + 1):
            try:
                resp = self._session.request(
                    method,
                    url,
                    timeout=kwargs.pop("timeout", self._default_timeout),
                    impersonate=kwargs.pop("impersonate", "chrome110"),
                    **kwargs,
                )
                status_code = resp.status_code
                if status_code >= 500 or status_code == 429:
                    raise RuntimeError(f"HTTP {status_code}")
                self._cb.record_success(domain)
                return resp
            except Exception as exc:
                last_exc = exc
                cat = classify_error(exc, status_code)
                if cat not in policy.retry_on or attempt >= policy.max_retries:
                    break
                delay = _backoff_delay(attempt, policy)
                time.sleep(delay)

        self._cb.record_failure(domain)
        raise last_exc or RuntimeError(f"Request failed after {policy.max_retries} retries")

    def get(self, url: str, **kwargs: Any) -> curl_requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> curl_requests.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> curl_requests.Response:
        return self.request("PATCH", url, **kwargs)

    def close(self) -> None:
        self._session.close()


# Global singleton instance
http = HttpClient()
