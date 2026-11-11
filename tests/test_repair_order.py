import pytest
import uuid
from src.domain.value_objects import DeviceSpecification, Money
from src.domain.aggregate import RepairOrder, RepairStatus
from src.domain.exceptions import DiagnosticRequiredException, InvalidMoneyAmountException
from src.infrastructure.in_memory_repository import InMemoryRepairOrderRepository

def test_create_repair_order_success():
    """Перевірка коректного створення агрегату."""
    device = DeviceSpecification(brand="Apple", model="iPhone 13", serial_number="SN123456")
    order_id = uuid.uuid4()
    order = RepairOrder(order_id, device)
    
    assert order.id == order_id
    assert order.status == RepairStatus.NEW
    assert order.device.brand == "Apple"

def test_device_specification_invalid_serial():
    """Перевірка недопустимого значення (порожній серійний номер)."""
    with pytest.raises(ValueError, match="Серійний номер пристрою обов'язковий"):
        DeviceSpecification(brand="Samsung", model="Galaxy S22", serial_number="")

def test_money_invalid_amount():
    """Перевірка недопустимого значення (від'ємна сума)."""
    with pytest.raises(InvalidMoneyAmountException):
        Money(amount=-100, currency="UAH")

def test_start_repair_without_diagnostics_fails():
    """Порушення інваріанта: не можна почати ремонт без діагностики."""
    device = DeviceSpecification(brand="Dell", model="XPS 15", serial_number="DELL789")
    order = RepairOrder(uuid.uuid4(), device)
    
    with pytest.raises(DiagnosticRequiredException):
        order.approve_and_start_repair()

def test_full_repair_lifecycle_and_event_generation():
    """Перевірка дозволених переходів стану та формування події."""
    device = DeviceSpecification(brand="Sony", model="PlayStation 5", serial_number="PS5-999")
    order = RepairOrder(uuid.uuid4(), device)
    
    order.start_diagnostics()
    assert order.status == RepairStatus.IN_DIAGNOSTICS
    
    cost = Money(amount=1500)
    order.complete_diagnostics(estimated_cost=cost)
    assert order.status == RepairStatus.WAITING_FOR_APPROVAL
    
    order.approve_and_start_repair()
    assert order.status == RepairStatus.IN_PROGRESS
    
    order.complete_repair()
    assert order.status == RepairStatus.COMPLETED
    # Перевірка, що подія успішно згенерована
    assert len(order.domain_events) == 1
    assert order.domain_events[0].order_id == order.id

def test_repository_save_and_retrieve():
    """Перевірка збереження та отримання агрегату з In-Memory репозиторію."""
    repo = InMemoryRepairOrderRepository()
    device = DeviceSpecification(brand="Asus", model="ROG", serial_number="ASUS123")
    order = RepairOrder(uuid.uuid4(), device)
    
    repo.save(order)
    retrieved_order = repo.get_by_id(order.id)
    
    assert retrieved_order is not None
    assert retrieved_order.id == order.id
    assert retrieved_order.device.serial_number == "ASUS123"