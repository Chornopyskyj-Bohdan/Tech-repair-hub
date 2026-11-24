from datetime import timedelta
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.auth import issue_test_access_token
from src.gateway.gateway_app import create_gateway_app
from src.gateway.warranty_stub import warranty_app

client = TestClient(app)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_1_allowed_access_owner_and_supervisor():
    """Перевірка 1: Дозволений доступ власника (tech-alice) та керівника (sup-carol)."""
    alice_token = issue_test_access_token(sub="tech-alice", role="technician")
    carol_token = issue_test_access_token(sub="sup-carol", role="supervisor")

    create_resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "Lenovo", "model": "ThinkPad X1", "serial_number": "LN-101"},
        headers=_auth_header(alice_token),
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["id"]

    # Власник читає та змінює статус своєї заявки
    get_own = client.get(f"/api/v2/repair-orders/{order_id}", headers=_auth_header(alice_token))
    assert get_own.status_code == 200

    patch_own = client.patch(
        f"/api/v2/repair-orders/{order_id}/status",
        json={"status": "IN_DIAGNOSTICS"},
        headers=_auth_header(alice_token),
    )
    assert patch_own.status_code == 200
    assert patch_own.json()["status"] == "IN_DIAGNOSTICS"

    # Керівник (supervisor) має доступ до заявки будь-якого інженера
    get_sup = client.get(f"/api/v2/repair-orders/{order_id}", headers=_auth_header(carol_token))
    assert get_sup.status_code == 200


def test_2_missing_token_returns_401():
    """Перевірка 2: Відсутній токен повертає 401 Unauthorized."""
    resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "Asus", "model": "ZenBook", "serial_number": "AS-202"},
    )
    assert resp.status_code == 401


def test_3_tampered_signature_returns_401():
    """Перевірка 3: Змінений підпис JWT повертає 401 Unauthorized."""
    valid_token = issue_test_access_token(sub="tech-alice", role="technician")
    header, payload, signature = valid_token.split(".")
    tampered_sig = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered_token = f"{header}.{payload}.{tampered_sig}"

    resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "Asus", "model": "ZenBook", "serial_number": "AS-303"},
        headers=_auth_header(tampered_token),
    )
    assert resp.status_code == 401


def test_4_expired_token_returns_401():
    """Перевірка 4: Прострочений токен (exp у минулому) повертає 401 Unauthorized."""
    expired_token = issue_test_access_token(
        sub="tech-alice",
        role="technician",
        expires_delta=timedelta(minutes=-5),
    )
    resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "HP", "model": "EliteBook", "serial_number": "HP-404"},
        headers=_auth_header(expired_token),
    )
    assert resp.status_code == 401


def test_5_wrong_audience_returns_401():
    """Перевірка 5: Неправильна аудиторія (aud) повертає 401 Unauthorized."""
    wrong_aud_token = issue_test_access_token(
        sub="tech-alice",
        role="technician",
        audience="another-external-service",
    )
    resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "HP", "model": "ProBook", "serial_number": "HP-505"},
        headers=_auth_header(wrong_aud_token),
    )
    assert resp.status_code == 401


def test_6_wrong_issuer_returns_401():
    """Перевірка 6: Неправильний емітент (iss) повертає 401 Unauthorized."""
    wrong_iss_token = issue_test_access_token(
        sub="tech-alice",
        role="technician",
        issuer="untrusted-identity-provider",
    )
    resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "Dell", "model": "XPS", "serial_number": "DL-606"},
        headers=_auth_header(wrong_iss_token),
    )
    assert resp.status_code == 401


def test_7_forbidden_role_preserves_state():
    """Перевірка 7: Заборонена роль (technician викликає DELETE) -> 403, стан не змінився."""
    alice_token = issue_test_access_token(sub="tech-alice", role="technician")

    create_resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "Apple", "model": "MacBook Pro", "serial_number": "AP-707"},
        headers=_auth_header(alice_token),
    )
    order_id = create_resp.json()["id"]

    # technician не має права на привілейовану операцію видалення
    del_resp = client.delete(
        f"/api/v2/repair-orders/{order_id}",
        headers=_auth_header(alice_token),
    )
    assert del_resp.status_code == 403

    # Перевіряємо, що захищений об'єкт залишився незмінним у сховищі
    check_resp = client.get(
        f"/api/v2/repair-orders/{order_id}",
        headers=_auth_header(alice_token),
    )
    assert check_resp.status_code == 200
    assert check_resp.json()["status"] == "NEW"


def test_8_cross_owner_access_same_role_preserves_state():
    """Перевірка 8: Доступ до чужого об'єкта під тією самою роллю (tech-bob -> об'єкт tech-alice) -> 403."""
    alice_token = issue_test_access_token(sub="tech-alice", role="technician")
    bob_token = issue_test_access_token(sub="tech-bob", role="technician")

    create_resp = client.post(
        "/api/v2/repair-orders",
        json={"brand": "Acer", "model": "Swift 3", "serial_number": "AC-808"},
        headers=_auth_header(alice_token),
    )
    order_id = create_resp.json()["id"]

    # tech-bob намагається прочитати чужу заявку
    bob_get = client.get(
        f"/api/v2/repair-orders/{order_id}",
        headers=_auth_header(bob_token),
    )
    assert bob_get.status_code == 403

    # tech-bob намагається змінити статус чужої заявки
    bob_patch = client.patch(
        f"/api/v2/repair-orders/{order_id}/status",
        json={"status": "IN_DIAGNOSTICS"},
        headers=_auth_header(bob_token),
    )
    assert bob_patch.status_code == 403

    # Перевіряємо, що стан заявки власника tech-alice залишився NEW
    alice_check = client.get(
        f"/api/v2/repair-orders/{order_id}",
        headers=_auth_header(alice_token),
    )
    assert alice_check.status_code == 200
    assert alice_check.json()["status"] == "NEW"


def test_sensitivity_point_timeout_parameter_experiment():
    """Завдання 5: Експеримент зі зміною параметра per_attempt_timeout_sec на точці чутливості."""
    import httpx
    from tests.test_gateway_resilience import _BackgroundServer

    warranty_srv = _BackgroundServer(warranty_app, "127.0.0.1", 18002)
    warranty_srv.start()
    try:
        warranty_client = httpx.Client(base_url="http://127.0.0.1:18002")
        gw = TestClient(
            create_gateway_app(
                orders_client=TestClient(app),
                warranty_client=warranty_client,
            )
        )
        # Залежність відповідає стабільно за 180 мс
        warranty_client.post(
            "/admin/behavior",
            json={"delay_sec": 0.18, "always_fail": False, "reset_counter": True},
        )

        # Конфігурація A: per_attempt_timeout = 0.25s (> 0.18s) -> успіх 200
        gw.post(
            "/gateway/admin/reset",
            json={"per_attempt_timeout_sec": 0.25, "overall_deadline_sec": 0.80},
        )
        resp_a = gw.get("/gateway/warranty/SN-SENS-A")
        assert resp_a.status_code == 200

        # Конфігурація B: зменшуємо per_attempt_timeout до 0.10s (< 0.18s) -> відмова 504
        gw.post(
            "/gateway/admin/reset",
            json={"per_attempt_timeout_sec": 0.10, "overall_deadline_sec": 0.35},
        )
        resp_b = gw.get("/gateway/warranty/SN-SENS-B")
        assert resp_b.status_code == 504
        warranty_client.close()
    finally:
        warranty_srv.stop()