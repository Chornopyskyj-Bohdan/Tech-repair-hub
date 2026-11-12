from abc import ABC, abstractmethod
import uuid
from typing import Optional
from src.domain.aggregate import RepairOrder

class IRepairOrderRepository(ABC):
    @abstractmethod
    def save(self, order: RepairOrder) -> None:
        pass

    @abstractmethod
    def get_by_id(self, order_id: uuid.UUID) -> Optional[RepairOrder]:
        pass