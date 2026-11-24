import logging
import uuid
import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.gateway.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    DeadlineExceededError,
    FixedWindowRateLimiter,
    ResilienceConfig,
    execute_with_resilience,
)

logger = logging.getLogger("techrepair.gateway")


class GatewayAdminResetRequest(BaseModel):
    rate_limit_max_requests: int = 100
    cb_failure_threshold: int = 3
    cb_recovery_timeout_sec: float = 1.0
    per_attempt_timeout_sec: float = 0.20
    overall_deadline_sec: float = 0.65
    enable_resilience: bool = True


def create_gateway_app(
    orders_client: httpx.Client,
    warranty_client: httpx.Client,
    config: ResilienceConfig | None = None,
) -> FastAPI:
    """Фабрика API Gateway з ін'єкцією HTTP-клієнтів для локального запуску та тестів."""
    gateway = FastAPI(title="TechRepair Hub API Gateway", version="1.0.0")
    cfg = config or ResilienceConfig()
    limiter = FixedWindowRateLimiter(
        max_requests=cfg.rate_limit_max_requests,
        window_sec=cfg.rate_limit_window_sec,
    )
    warranty_breaker = CircuitBreaker(
        name="VendorWarrantyService",
        failure_threshold=cfg.cb_failure_threshold,
        recovery_timeout_sec=cfg.cb_recovery_timeout_sec,
        half_open_max_calls=cfg.cb_half_open_max_calls,
    )
    state = {"enable_resilience": True}

    @gateway.middleware("http")
    async def gateway_cross_cutting_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Адмін-ендпоінт для скидання стану на стенді не обмежується лімітом
        if not request.url.path.startswith("/gateway/admin"):
            client_key = request.headers.get("X-Client-ID", "anonymous-client")
            allowed, retry_after = limiter.allow_request(client_key)
            if not allowed:
                logger.warning(
                    "[request_id=%s] Rate limit перевищено для клієнта %s",
                    request_id,
                    client_key,
                )
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too Many Requests: перевищено ліміт запитів"},
                    headers={
                        "X-Request-ID": request_id,
                        "Retry-After": str(retry_after),
                    },
                )

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @gateway.post("/gateway/admin/reset")
    def admin_reset(payload: GatewayAdminResetRequest):
        cfg.per_attempt_timeout_sec = payload.per_attempt_timeout_sec
        cfg.overall_deadline_sec = payload.overall_deadline_sec
        warranty_breaker.failure_threshold = payload.cb_failure_threshold
        warranty_breaker.recovery_timeout_sec = payload.cb_recovery_timeout_sec
        warranty_breaker.reset()
        limiter.reset(max_requests=payload.rate_limit_max_requests)
        state["enable_resilience"] = payload.enable_resilience
        return {"status": "reset_ok", "breaker_state": warranty_breaker.state.value}

    @gateway.get("/gateway/admin/status")
    def admin_status():
        return {
            "breaker_state": warranty_breaker.state.value,
            "consecutive_failures": warranty_breaker.consecutive_failures,
            "enable_resilience": state["enable_resilience"],
        }

    # --- Маршрут 1: Читання гарантії (із захистом Retry + Deadline + Circuit Breaker) ---
    @gateway.get("/gateway/warranty/{serial_number}")
    def get_device_warranty(serial_number: str, request: Request):
        req_id = request.state.request_id
        url = f"/api/v1/warranty/{serial_number}"

        # Режим "ДО захисту" для порівняльного досліду (Завдання 5)
        if not state["enable_resilience"]:
            try:
                resp = warranty_client.get(
                    url,
                    headers={"X-Request-ID": req_id},
                    timeout=1.5,
                )
                return JSONResponse(status_code=resp.status_code, content=resp.json())
            except httpx.TimeoutException:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Upstream warranty timeout (unprotected)",
                )

        try:
            resp = execute_with_resilience(
                client=warranty_client,
                method="GET",
                url=url,
                request_id=req_id,
                config=cfg,
                breaker=warranty_breaker,
                allow_retry=True,
            )
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except CircuitBreakerOpenError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
        except (httpx.TimeoutException, DeadlineExceededError):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gateway Timeout: перевищено час очікування сервісу гарантії",
            )

    # --- Маршрут 2: Створення заявки (зміна стану -> БЕЗ автоповторів!) ---
    @gateway.post("/gateway/repair-orders")
    async def proxy_create_repair_order(request: Request):
        req_id = request.state.request_id
        body = await request.json()
        try:
            resp = execute_with_resilience(
                client=orders_client,
                method="POST",
                url="/api/v1/repair-orders",
                request_id=req_id,
                config=cfg,
                breaker=None,
                allow_retry=False,  # Зміна стану не повторюється без політики ідемпотентності
                json_body=body,
            )
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except (httpx.TimeoutException, DeadlineExceededError):
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Gateway Timeout: невідомий результат створення заявки (повтор заборонено)",
            )

    return gateway