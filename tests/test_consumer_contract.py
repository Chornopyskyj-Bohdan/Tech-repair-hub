import json
from pathlib import Path
import httpx
from src.client.repair_client import RepairOrderClient

CONTRACT_PATH = Path(__file__).parent.parent / "contracts" / "repair_order_contract.json"


def test_consumer_expectations_on_mocked_response():
    """Перевіряє, що клієнт коректно обробляє очікувану відповідь з контракту."""
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    interaction = contract["interactions"][0]
    expected_resp = interaction["expected_response"]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=expected_resp["status"],
            json=expected_resp["sample_body"],
        )

    mock_client = httpx.Client(
        transport=httpx.MockTransport(mock_handler),
        base_url="http://testserver",
    )
    consumer = RepairOrderClient(mock_client)

    req_body = interaction["request"]["body"]
    result = consumer.create_order(
        brand=req_body["brand"],
        model=req_body["model"],
        serial_number=req_body["serial_number"],
    )

    assert result["id"] == expected_resp["sample_body"]["id"]
    assert result["status"] == "NEW"
    assert result["diagnostic_completed"] is False
    assert result["device"]["serial_number"] == "PF2X9876"