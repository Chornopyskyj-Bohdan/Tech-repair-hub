import logging
from src.saga.services import WarehouseService, RepairService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SagaOrchestrator")

class RepairApprovalSaga:
    def __init__(self, warehouse: WarehouseService, repair: RepairService):
        self.warehouse = warehouse
        self.repair = repair
        self.journal = []

    def execute(self, saga_id: str, order_id: str, part_id: str, quantity: int) -> str:
        self.journal.append(f"[{saga_id}] START SAGA")

        # Крок 1: Резерв деталей
        logger.info(f"[{saga_id}] Step 1: Reserving {quantity}x {part_id}")
        reserve_ok = self.warehouse.reserve_parts(saga_id, part_id, quantity)
        
        if not reserve_ok:
            self.journal.append(f"[{saga_id}] ABORT: Failed to reserve parts")
            return "FAILED_AT_RESERVE"
        
        self.journal.append(f"[{saga_id}] SUCCESS: Parts reserved")

        # Крок 2: Затвердження ремонту
        logger.info(f"[{saga_id}] Step 2: Approving order {order_id}")
        try:
            approve_ok = self.repair.approve_repair(saga_id, order_id)
            if approve_ok:
                self.journal.append(f"[{saga_id}] SUCCESS: Order approved")
                return "COMPLETED"
        except Exception as e:
            logger.error(f"[{saga_id}] Step 2 Failed: {str(e)}. Initiating compensation.")
            self.journal.append(f"[{saga_id}] ERROR: {str(e)}")

        # Компенсація Кроку 1 (якщо Крок 2 впав)
        logger.info(f"[{saga_id}] Compensation: Releasing {quantity}x {part_id}")
        try:
            self.warehouse.release_parts(saga_id, part_id, quantity)
            self.journal.append(f"[{saga_id}] COMPENSATED: Parts released")
            return "COMPENSATED"
        except Exception as comp_e:
            logger.critical(f"[{saga_id}] Compensation Failed: {str(comp_e)}. Manual intervention required!")
            self.journal.append(f"[{saga_id}] COMPENSATION_FAILED: {str(comp_e)}")
            return "COMPENSATION_FAILED"