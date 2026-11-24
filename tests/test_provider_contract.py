import json
from pathlib import Path
from fastapi.testclient import TestClient
from src.api.app import app

CONTRACT_PATH = Path(__file__).parent.parent / "contracts" / "repair_order_contract.json"
client = TestClient(app)

TYPE_MAP = {
    "str": str,
    "bool": bool,
    "int": int,
    "float": float,
    "dict": dict,
}


def test_provider_fulfills_consumer_contract():
    """Перевіряє реальний FastAPI-провайдер на відповідність контракту споживача."""
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    interaction = contract["interactions"][0]

    req = interaction["request"]
    expected = interaction["expected_response"]

    response = client.request(req["method"], req["path"], json=req["body"])
    assert response.status_code == expected["status"]

    actual_body = response.json()
    for field_name, expected_type_name in expected["required_fields"].items():
        assert field_name in actual_body, f"Контракт порушено: відсутнє поле '{field_name}'"
        expected_type = TYPE_MAP[expected_type_name]
        assert isinstance(actual_body[field_name], expected_type), (
            f"Контракт порушено: поле '{field_name}' має тип {type(actual_body[field_name]).__name__}, "
            f"очікувався {expected_type_name}"
        )