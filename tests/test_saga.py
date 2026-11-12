import pytest
from src.saga.services import WarehouseService, RepairService
from src.saga.orchestrator import RepairApprovalSaga

@pytest.fixture
def setup_saga():
    warehouse = WarehouseService()
    repair = RepairService()
    orchestrator = RepairApprovalSaga(warehouse, repair)
    return warehouse, repair, orchestrator

def test_saga_success(setup_saga):
    """1. Успішний процес: Резерв деталей -> Затвердження ремонту."""
    warehouse, repair, orchestrator = setup_saga
    saga_id = "SAGA_001"
    
    # Початковий стан
    assert warehouse.inventory["SCREEN_IPHONE13"] == 5
    assert repair.orders_status["ORDER_1"] == "WAITING_FOR_APPROVAL"

    result = orchestrator.execute(saga_id, "ORDER_1", "SCREEN_IPHONE13", 1)

    # Кінцевий стан
    assert result == "COMPLETED"
    assert warehouse.inventory["SCREEN_IPHONE13"] == 4
    assert repair.orders_status["ORDER_1"] == "IN_PROGRESS"
    assert f"[{saga_id}] SUCCESS: Order approved" in orchestrator.journal

def test_saga_failure_with_compensation(setup_saga):
    """2. Відмова другого кроку з компенсацією (повернення деталей)."""
    warehouse, repair, orchestrator = setup_saga
    saga_id = "SAGA_002"
    
    # Симулюємо бізнес-помилку на 2-му кроці
    repair.simulate_approval_failure = True

    result = orchestrator.execute(saga_id, "ORDER_1", "SCREEN_IPHONE13", 1)

    # Кінцевий стан: Сага відкотилася
    assert result == "COMPENSATED"
    assert warehouse.inventory["SCREEN_IPHONE13"] == 5
    assert repair.orders_status["ORDER_1"] == "WAITING_FOR_APPROVAL"
    assert f"[{saga_id}] COMPENSATED: Parts released" in orchestrator.journal

def test_saga_idempotency_retry(setup_saga):
    """3. Повтор команд без повторного ефекту (Ідемпотентність)."""
    warehouse, repair, orchestrator = setup_saga
    saga_id = "SAGA_003"
    
    # Виконуємо сагу вперше
    orchestrator.execute(saga_id, "ORDER_1", "SCREEN_IPHONE13", 1)
    assert warehouse.inventory["SCREEN_IPHONE13"] == 4

    # Виконуємо ТУ САМУ сагу вдруге (імітація дублювання запиту)
    result_retry = orchestrator.execute(saga_id, "ORDER_1", "SCREEN_IPHONE13", 1)
    
    # Стан не повинен змінитися вдруге (деталь не списується двічі)
    assert result_retry == "COMPLETED"
    assert warehouse.inventory["SCREEN_IPHONE13"] == 4
    assert "reserve_SAGA_003" in warehouse.processed_commands

def test_saga_compensation_failure_and_retry(setup_saga):
    """4. Помилка компенсації з подальшим повтором."""
    warehouse, repair, orchestrator = setup_saga
    saga_id = "SAGA_004"
    
    # Симулюємо падіння і на 2-му кроці, і під час компенсації
    repair.simulate_approval_failure = True
    warehouse.simulate_compensation_failure = True

    result = orchestrator.execute(saga_id, "ORDER_1", "SCREEN_IPHONE13", 1)

    # Система в підвислому стані: ремонт не затверджено, деталі зарезервовано, компенсація впала
    assert result == "COMPENSATION_FAILED"
    assert warehouse.inventory["SCREEN_IPHONE13"] == 4

    # РОБИМО ПОВТОР (Retry) компенсації: усуваємо проблему на складі
    warehouse.simulate_compensation_failure = False
    
    # Повторюємо виклик компенсаційної команди безпосередньо (імітація job-ретраю)
    retry_ok = warehouse.release_parts(saga_id, "SCREEN_IPHONE13", 1)
    
    assert retry_ok is True
    assert warehouse.inventory["SCREEN_IPHONE13"] == 5