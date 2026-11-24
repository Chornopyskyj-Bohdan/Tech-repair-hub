import httpx


class RepairOrderClient:
    """Клієнт (Consumer) для взаємодії з TechRepair Hub API."""

    def __init__(self, client: httpx.Client):
        self._client = client

    def create_order(self, brand: str, model: str, serial_number: str) -> dict:
        resp = self._client.post(
            "/api/v1/repair-orders",
            json={"brand": brand, "model": model, "serial_number": serial_number},
        )
        resp.raise_for_status()
        return resp.json()

    def get_order(self, order_id: str) -> dict:
        resp = self._client.get(f"/api/v1/repair-orders/{order_id}")
        resp.raise_for_status()
        return resp.json()

    def update_status(
        self,
        order_id: str,
        status: str,
        estimated_cost: float | None = None,
        currency: str = "UAH",
    ) -> dict:
        body: dict = {"status": status}
        if estimated_cost is not None:
            body["estimated_cost"] = estimated_cost
            body["currency"] = currency

        resp = self._client.patch(
            f"/api/v1/repair-orders/{order_id}/status",
            json=body,
        )
        resp.raise_for_status()
        return resp.json()

    def run_full_repair_workflow(self, brand: str, model: str, serial_number: str) -> dict:
        """Завершений сценарій: створення -> читання -> діагностика -> ремонт -> завершення."""
        created = self.create_order(brand, model, serial_number)
        order_id = created["id"]

        fetched = self.get_order(order_id)
        assert fetched["status"] == "NEW"

        self.update_status(order_id, "IN_DIAGNOSTICS")
        self.update_status(order_id, "WAITING_FOR_APPROVAL", estimated_cost=1200.0, currency="UAH")
        self.update_status(order_id, "IN_PROGRESS")
        completed = self.update_status(order_id, "COMPLETED")
        return completed