import logging
import socket
import statistics
import threading
import time
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from src.api.app import app as core_orders_app
from src.gateway.gateway_app import create_gateway_app
from src.gateway.warranty_stub import warranty_app


class _BackgroundServer:
    """Запускає справжній HTTP-сервер uvicorn у фоновому потоці для чесних мережевих таймаутів."""

    def __init__(self, app, host: str, port: int):
        self.config = uvicorn.Config(app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                with socket.create_connection((self.config.host, self.config.port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"Не вдалося запустити сервер на порту {self.config.port}")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=3.0)


@pytest.fixture(scope="module")
def live_upstream_servers():
    orders_srv = _BackgroundServer(core_orders_app, "127.0.0.1", 18000)
    warranty_srv = _BackgroundServer(warranty_app, "127.0.0.1", 18001)
    orders_srv.start()
    warranty_srv.start()
    yield "http://127.0.0.1:18000", "http://127.0.0.1:18001"
    warranty_srv.stop()
    orders_srv.stop()


@pytest.fixture
def gateway_env(live_upstream_servers):
    """Підіймає шлюз перед реальними локальними HTTP-серверами."""
    orders_url, warranty_url = live_upstream_servers
    orders_client = httpx.Client(base_url=orders_url)
    warranty_client = httpx.Client(base_url=warranty_url)

    gw_app = create_gateway_app(orders_client=orders_client, warranty_client=warranty_client)
    gw_client = TestClient(gw_app)

    gw_client.post(
        "/gateway/admin/reset",
        json={
            "rate_limit_max_requests": 1000,
            "cb_failure_threshold": 3,
            "cb_recovery_timeout_sec": 0.4,
            "per_attempt_timeout_sec": 0.15,
            "overall_deadline_sec": 0.45,
            "enable_resilience": True,
        },
    )
    warranty_client.post(
        "/admin/behavior",
        json={"delay_sec": 0.0, "fail_next_n": 0, "always_fail": False, "reset_counter": True},
    )
    yield gw_client, warranty_client
    orders_client.close()
    warranty_client.close()


def test_scenario_1_normal_response(gateway_env, caplog):
    """Сценарій 1: Нормальна відповідь та прокидання X-Request-ID до залежності."""
    caplog.set_level(logging.INFO)
    gw, stub = gateway_env

    t0 = time.perf_counter()
    resp = gw.get(
        "/gateway/warranty/SN-1001",
        headers={"X-Client-ID": "reception-1", "X-Request-ID": "req-normal-001"},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    stats = stub.get("/admin/stats").json()
    print(f"\n[Сценарій 1] HTTP={resp.status_code}, час={elapsed_ms:.1f}ms, викликів залежності={stats['call_count']}")

    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "req-normal-001"
    assert stats["call_count"] == 1
    assert "req-normal-001" in stats["received_request_ids"]


def test_scenario_2_hang_exceeds_deadline(gateway_env, caplog):
    """Сценарій 2: Зависання залежності впирається в per-attempt timeout та загальний deadline."""
    caplog.set_level(logging.INFO)
    gw, stub = gateway_env

    # Затримка 0.25s перевищує per_attempt_timeout (0.15s); повтори впираються в deadline (0.45s)
    stub.post("/admin/behavior", json={"delay_sec": 0.25, "reset_counter": True})

    t0 = time.perf_counter()
    resp = gw.get(
        "/gateway/warranty/SN-HANG",
        headers={"X-Client-ID": "reception-1", "X-Request-ID": "req-hang-002"},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    stats = stub.get("/admin/stats").json()
    print(f"\n[Сценарій 2] HTTP={resp.status_code}, час={elapsed_ms:.1f}ms, викликів залежності={stats['call_count']}")

    assert resp.status_code == 504
    assert elapsed_ms < 750
    assert 2 <= stats["call_count"] <= 3


def test_scenario_3_transient_error_recovers_with_retry(gateway_env, caplog):
    """Сценарій 3: Тимчасова помилка 503 на перших 2 спробах успішно відновлюється на 3-й."""
    caplog.set_level(logging.INFO)
    gw, stub = gateway_env

    stub.post("/admin/behavior", json={"fail_next_n": 2, "reset_counter": True})

    t0 = time.perf_counter()
    resp = gw.get(
        "/gateway/warranty/SN-RETRY",
        headers={"X-Client-ID": "reception-1", "X-Request-ID": "req-retry-003"},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    stats = stub.get("/admin/stats").json()
    print(f"\n[Сценарій 3] HTTP={resp.status_code}, час={elapsed_ms:.1f}ms, викликів залежності={stats['call_count']}")

    assert resp.status_code == 200
    assert stats["call_count"] == 3


def test_scenario_4_circuit_breaker_open_and_half_open_recovery(gateway_env, caplog):
    """Сценарій 4: Відкриття breaker без звернень до залежності та відновлення через HALF_OPEN."""
    caplog.set_level(logging.INFO)
    gw, stub = gateway_env

    stub.post("/admin/behavior", json={"always_fail": True, "reset_counter": True})

    for i in range(3):
        r = gw.get("/gateway/warranty/SN-CB", headers={"X-Request-ID": f"req-cb-fail-{i}"})
        assert r.status_code == 503

    calls_when_opened = stub.get("/admin/stats").json()["call_count"]
    assert gw.get("/gateway/admin/status").json()["breaker_state"] == "OPEN"

    t0 = time.perf_counter()
    fast_fail_resp = gw.get("/gateway/warranty/SN-CB", headers={"X-Request-ID": "req-cb-fastfail"})
    fast_fail_ms = (time.perf_counter() - t0) * 1000
    calls_after_fast_fail = stub.get("/admin/stats").json()["call_count"]

    print(
        f"\n[Сценарій 4 - OPEN] HTTP={fast_fail_resp.status_code}, час={fast_fail_ms:.2f}ms, "
        f"викликів до={calls_when_opened}, після={calls_after_fast_fail}"
    )
    assert fast_fail_resp.status_code == 503
    assert calls_after_fast_fail == calls_when_opened

    time.sleep(0.45)
    stub.post("/admin/behavior", json={"always_fail": False, "reset_counter": False})

    t1 = time.perf_counter()
    recovered_resp = gw.get("/gateway/warranty/SN-CB", headers={"X-Request-ID": "req-cb-probe"})
    recovered_ms = (time.perf_counter() - t1) * 1000

    print(
        f"[Сценарій 4 - HALF_OPEN->CLOSED] HTTP={recovered_resp.status_code}, "
        f"час={recovered_ms:.2f}ms, стан={gw.get('/gateway/admin/status').json()['breaker_state']}"
    )
    assert recovered_resp.status_code == 200
    assert gw.get("/gateway/admin/status").json()["breaker_state"] == "CLOSED"


def test_scenario_5_rate_limiting_returns_429(gateway_env, caplog):
    """Сценарій 5: Перевищення ліміту запитів по X-Client-ID повертає 429 Too Many Requests."""
    caplog.set_level(logging.INFO)
    gw, stub = gateway_env

    gw.post("/gateway/admin/reset", json={"rate_limit_max_requests": 3})

    codes = []
    t0 = time.perf_counter()
    for i in range(4):
        resp = gw.get(
            "/gateway/warranty/SN-RL",
            headers={"X-Client-ID": "mobile-client-42", "X-Request-ID": f"req-rl-{i}"},
        )
        codes.append(resp.status_code)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    stats = stub.get("/admin/stats").json()
    print(f"\n[Сценарій 5] Коди={codes}, загальний час={elapsed_ms:.1f}ms, викликів залежності={stats['call_count']}")

    assert codes == [200, 200, 200, 429]
    assert stats["call_count"] == 3


def test_state_changing_post_is_not_retried_without_idempotency():
    """Окрема перевірка: операція зміни стану (POST) виконує лише 1 спробу навіть при збої."""
    attempts = {"count": 0}

    def flaky_orders_handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(status_code=503, json={"detail": "Temporary failure"})

    mock_orders = httpx.Client(
        transport=httpx.MockTransport(flaky_orders_handler),
        base_url="http://orders-service",
    )
    gw = TestClient(create_gateway_app(orders_client=mock_orders, warranty_client=TestClient(warranty_app)))

    resp = gw.post(
        "/gateway/repair-orders",
        json={"brand": "Dell", "model": "Latitude", "serial_number": "DL-999"},
        headers={"X-Request-ID": "req-post-noretry"},
    )
    assert resp.status_code == 503
    assert attempts["count"] == 1


def test_benchmark_30_requests_before_and_after_protection(gateway_env):
    """Завдання 5: Порівняння 30 однакових запитів ДО та ПІСЛЯ захисту за однакового збою."""
    gw, stub = gateway_env
    total_requests = 30

    def run_series(enable_resilience: bool) -> dict:
        gw.post(
            "/gateway/admin/reset",
            json={
                "rate_limit_max_requests": 1000,
                "cb_failure_threshold": 3,
                "cb_recovery_timeout_sec": 5.0,
                "per_attempt_timeout_sec": 0.15,
                "overall_deadline_sec": 0.45,
                "enable_resilience": enable_resilience,
            },
        )
        stub.post(
            "/admin/behavior",
            json={"delay_sec": 0.12, "always_fail": True, "reset_counter": True},
        )

        durations_ms = []
        successes = 0
        failures = 0

        for i in range(total_requests):
            t0 = time.perf_counter()
            resp = gw.get(f"/gateway/warranty/SN-BENCH-{i}")
            durations_ms.append((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                successes += 1
            else:
                failures += 1

        stub_calls = stub.get("/admin/stats").json()["call_count"]
        return {
            "successes": successes,
            "failures": failures,
            "stub_calls": stub_calls,
            "median_ms": statistics.median(durations_ms),
            "max_ms": max(durations_ms),
            "total_ms": sum(durations_ms),
        }

    before = run_series(enable_resilience=False)
    after = run_series(enable_resilience=True)

    print("\n=== ПОРІВНЯННЯ 30 ЗАПИТІВ (ДО ТА ПІСЛЯ ЗАХИСТУ) ===")
    print(f"ДО захисту:    успіхів={before['successes']}, відмов={before['failures']}, викликів залежності={before['stub_calls']}, медіана={before['median_ms']:.1f}ms, макс={before['max_ms']:.1f}ms, сумарно={before['total_ms']:.0f}ms")
    print(f"ПІСЛЯ захисту: успіхів={after['successes']}, відмов={after['failures']}, викликів залежності={after['stub_calls']}, медіана={after['median_ms']:.1f}ms, макс={after['max_ms']:.1f}ms, сумарно={after['total_ms']:.0f}ms")

    assert before["failures"] == 30
    assert after["failures"] == 30
    assert after["stub_calls"] < before["stub_calls"]
    assert after["median_ms"] < before["median_ms"]