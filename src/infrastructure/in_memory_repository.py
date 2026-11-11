import uuid
from typing import Dict, Optional
from src.domain.aggregate import RepairOrder
from src.domain.repository_port import IRepairOrderRepository

class InMemoryRepairOrderRepository(IRepairOrderRepository):
    def __init__(self):
        self._storage: Dict[uuid.UUID, RepairOrder] = {}

    def save(self, order: RepairOrder) -> None:
        self._storage[order.id] = order

    def get_by_id(self, order_id: uuid.UUID) -> Optional[RepairOrder]:
        return self._storage.get(order_id)