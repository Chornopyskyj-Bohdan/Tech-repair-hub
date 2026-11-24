import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Set
import httpx

logger = logging.getLogger("techrepair.gateway")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Виняток швидкої відмови (Fast Fail), коли Circuit Breaker у стані OPEN."""


class DeadlineExceededError(Exception):
    """Вичерпано загальний бюджет часу (overall deadline) на виконання запиту."""


@dataclass
class ResilienceConfig:
    # Таймаути та повтори (для безпечних GET-операцій)
    per_attempt_timeout_sec: float = 0.20
    overall_deadline_sec: float = 0.65
    max_attempts: int = 3
    base_backoff_sec: float = 0.04
    max_jitter_sec: float = 0.02
    retryable_status_codes: Set[int] = field(default_factory=lambda: {502, 503, 504})

    # Circuit Breaker
    cb_failure_threshold: int = 3
    cb_recovery_timeout_sec: float = 1.0
    cb_half_open_max_calls: int = 1

    # Rate Limiting (Fixed Window по ключу клієнта)
    rate_limit_max_requests: int = 100
    rate_limit_window_sec: float = 60.0


class FixedWindowRateLimiter:
    """Обмежувач частоти запитів за ключем клієнта (X-Client-ID)."""

    def __init__(self, max_requests: int, window_sec: float):
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._windows: dict[str, tuple[float, int]] = {}

    def allow_request(self, client_key: str) -> tuple[bool, int]:
        """Повертає (дозволено, retry_after_sec)."""
        now = time.monotonic()
        window_start, count = self._windows.get(client_key, (now, 0))

        if now - window_start >= self.window_sec:
            window_start = now
            count = 0

        if count >= self.max_requests:
            retry_after = max(1, int(self.window_sec - (now - window_start)))
            return False, retry_after

        self._windows[client_key] = (window_start, count + 1)
        return True, 0

    def reset(self, max_requests: int | None = None) -> None:
        if max_requests is not None:
            self.max_requests = max_requests
        self._windows.clear()


class CircuitBreaker:
    """Реалізація патерну Circuit Breaker (CLOSED -> OPEN -> HALF_OPEN)."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_sec: float = 1.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.half_open_max_calls = half_open_max_calls

        self.state: CircuitState = CircuitState.CLOSED
        self.consecutive_failures: int = 0
        self.opened_at: float = 0.0
        self.half_open_in_flight: int = 0

    def before_call(self, request_id: str) -> None:
        now = time.monotonic()
        if self.state == CircuitState.OPEN:
            if now - self.opened_at >= self.recovery_timeout_sec:
                self._transition(CircuitState.HALF_OPEN, request_id)
                self.half_open_in_flight = 0
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit Breaker '{self.name}' is OPEN (fast fail)"
                )

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_in_flight >= self.half_open_max_calls:
                raise CircuitBreakerOpenError(
                    f"Circuit Breaker '{self.name}' HALF_OPEN probe limit reached"
                )
            self.half_open_in_flight += 1

    def record_success(self, request_id: str) -> None:
        if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            self._transition(CircuitState.CLOSED, request_id)
        self.consecutive_failures = 0
        self.half_open_in_flight = 0

    def record_failure(self, request_id: str) -> None:
        self.consecutive_failures += 1
        if self.state == CircuitState.HALF_OPEN:
            self.opened_at = time.monotonic()
            self._transition(CircuitState.OPEN, request_id)
            self.half_open_in_flight = 0
        elif (
            self.state == CircuitState.CLOSED
            and self.consecutive_failures >= self.failure_threshold
        ):
            self.opened_at = time.monotonic()
            self._transition(CircuitState.OPEN, request_id)

    def _transition(self, new_state: CircuitState, request_id: str) -> None:
        if self.state != new_state:
            logger.warning(
                "[request_id=%s] CircuitBreaker(%s): %s -> %s",
                request_id,
                self.name,
                self.state.value,
                new_state.value,
            )
            self.state = new_state

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.opened_at = 0.0
        self.half_open_in_flight = 0


def execute_with_resilience(
    client: httpx.Client,
    method: str,
    url: str,
    request_id: str,
    config: ResilienceConfig,
    breaker: CircuitBreaker | None = None,
    allow_retry: bool = False,
    json_body: dict | None = None,
) -> httpx.Response:
    """
    Виконує HTTP-виклик до внутрішнього сервісу з урахуванням Circuit Breaker,
    per-attempt timeout, overall deadline та exponential backoff + jitter.
    """
    if breaker is not None:
        breaker.before_call(request_id)

    deadline = time.monotonic() + config.overall_deadline_sec
    max_attempts = config.max_attempts if allow_retry else 1
    last_exc: Exception | None = None
    last_response: httpx.Response | None = None

    for attempt in range(1, max_attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if breaker is not None:
                breaker.record_failure(request_id)
            raise DeadlineExceededError("Перевищено загальний deadline запиту")

        attempt_timeout = min(config.per_attempt_timeout_sec, remaining)
        logger.info(
            "[request_id=%s] Виклик %s %s (спроба %d/%d, timeout=%.3fs)",
            request_id,
            method,
            url,
            attempt,
            max_attempts,
            attempt_timeout,
        )

        try:
            response = client.request(
                method=method,
                url=url,
                json=json_body,
                headers={"X-Request-ID": request_id},
                timeout=attempt_timeout,
            )

            # Перевіряємо, чи є статус тимчасовою помилкою, яку можна повторити
            if response.status_code in config.retryable_status_codes:
                last_response = response
                logger.warning(
                    "[request_id=%s] Тимчасова HTTP-помилка %d на спробі %d/%d",
                    request_id,
                    response.status_code,
                    attempt,
                    max_attempts,
                )
                if attempt < max_attempts:
                    _sleep_backoff(attempt, deadline, config, request_id)
                    continue
                if breaker is not None:
                    breaker.record_failure(request_id)
                return response

            # Успішна відповідь або клієнтська помилка (4xx — не повторюється і не ламає breaker)
            if breaker is not None:
                breaker.record_success(request_id)
            return response

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            logger.warning(
                "[request_id=%s] Мережевий збій/таймаут (%s) на спробі %d/%d",
                request_id,
                type(exc).__name__,
                attempt,
                max_attempts,
            )
            if attempt < max_attempts:
                _sleep_backoff(attempt, deadline, config, request_id)
                continue

    if breaker is not None:
        breaker.record_failure(request_id)

    if last_response is not None:
        return last_response
    raise last_exc if last_exc is not None else DeadlineExceededError("Запит не виконано")


def _sleep_backoff(
    attempt: int, deadline: float, config: ResilienceConfig, request_id: str
) -> None:
    exp_delay = config.base_backoff_sec * (2 ** (attempt - 1))
    jitter = random.uniform(0, config.max_jitter_sec)
    sleep_time = exp_delay + jitter

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceededError("Вичерпано deadline перед наступною спробою")

    actual_sleep = min(sleep_time, max(0.0, remaining - 0.005))
    logger.info(
        "[request_id=%s] Очікування backoff+jitter: %.3fs",
        request_id,
        actual_sleep,
    )
    if actual_sleep > 0:
        time.sleep(actual_sleep)