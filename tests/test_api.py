import uuid
from fastapi.testclient import TestClient
from src.api.app import app
from src.client.repair_client import RepairOrderClient

client = TestClient(app)


def test_full_happy_path_via_client():
    """Перевірка успішного сценарію через HTTP-клієнт."""
    repair_client = RepairOrderClient(client)
    result = repair_client.run_full_repair_workflow("Dell", "XPS 15", "DL998877")

    assert result["status"] == "COMPLETED"
    assert result["diagnostic_completed"] is True
    assert result["estimated_cost"] == 1200.0
    assert result["currency"] == "UAH"


def test_invalid_input_returns_422():
    """Перевірка некоректних вхідних даних (порожній серійний номер)."""
    resp = client.post(
        "/api/v1/repair-orders",
        json={"brand": "Asus", "model": "ROG", "serial_number": "  "},
    )
    assert resp.status_code == 422


def test_missing_resource_returns_404():
    """Перевірка запиту неіснуючої заявки."""
    random_id = uuid.uuid4()
    resp = client.get(f"/api/v1/repair-orders/{random_id}")
    assert resp.status_code == 404


def test_forbidden_state_transition_returns_409():
    """Перевірка забороненого переходу (спроба почати ремонт без діагностики)."""
    create_resp = client.post(
        "/api/v1/repair-orders",
        json={"brand": "HP", "model": "Pavilion", "serial_number": "HP123456"},
    )
    order_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/v1/repair-orders/{order_id}/status",
        json={"status": "IN_PROGRESS"},
    )
    assert patch_resp.status_code == 409