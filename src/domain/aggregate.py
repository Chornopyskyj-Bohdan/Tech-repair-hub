from enum import Enum
import uuid
from typing import List, Optional
from src.domain.value_objects import Money, DeviceSpecification
from src.domain.events import RepairOrderCompletedEvent
from src.domain.exceptions import InvalidStateTransitionException, DiagnosticRequiredException

class RepairStatus(Enum):
    NEW = "NEW"
    IN_DIAGNOSTICS = "IN_DIAGNOSTICS"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

class RepairOrder:
    def __init__(self, order_id: uuid.UUID, device: DeviceSpecification):
        self.id: uuid.UUID = order_id
        self.device: DeviceSpecification = device
        self.status: RepairStatus = RepairStatus.NEW
        self.estimated_cost: Optional[Money] = None
        self.diagnostic_completed: bool = False
        self.domain_events: List[object] = []

    def start_diagnostics(self) -> None:
        """Перехід у статус діагностики."""
        if self.status != RepairStatus.NEW:
            raise InvalidStateTransitionException("Діагностика можлива тільки для нових заявок")
        self.status = RepairStatus.IN_DIAGNOSTICS

    def complete_diagnostics(self, estimated_cost: Money) -> None:
        """Завершення діагностики та розрахунок кошторису."""
        if self.status != RepairStatus.IN_DIAGNOSTICS:
            raise InvalidStateTransitionException("Заявка має перебувати в процесі діагностики")
        self.estimated_cost = estimated_cost
        self.diagnostic_completed = True
        self.status = RepairStatus.WAITING_FOR_APPROVAL

    def approve_and_start_repair(self) -> None:
        """Інваріант 1: Заборонено почати ремонт без проведеної діагностики та погодженого кошторису."""
        if not self.diagnostic_completed or self.estimated_cost is None:
            raise DiagnosticRequiredException("Неможливо розпочати ремонт без проведеної діагностики")
        if self.status != RepairStatus.WAITING_FOR_APPROVAL:
            raise InvalidStateTransitionException("Ремонт можна почати лише після узгодження кошторисів")
        self.status = RepairStatus.IN_PROGRESS

    def complete_repair(self) -> None:
        """Інваріант 2: Перехід у COMPLETED та публікація доменної події."""
        if self.status != RepairStatus.IN_PROGRESS:
            raise InvalidStateTransitionException("Завершити можна тільки ремонт, який знаходиться в роботі")
        self.status = RepairStatus.COMPLETED
        self.domain_events.append(RepairOrderCompletedEvent(order_id=self.id))