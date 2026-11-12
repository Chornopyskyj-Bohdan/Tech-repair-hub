from typing import Dict, Set

class WarehouseService:
    """Учасник 1: Керує залишками запчастин."""
    def __init__(self):
        self.inventory: Dict[str, int] = {"SCREEN_IPHONE13": 5}
        self.processed_commands: Set[str] = set()
        self.simulate_compensation_failure = False

    def reserve_parts(self, saga_id: str, part_id: str, quantity: int) -> bool:
        command_id = f"reserve_{saga_id}"
        # Ідемпотентність: якщо команда вже виконувалася, просто повертаємо успіх
        if command_id in self.processed_commands:
            return True

        if self.inventory.get(part_id, 0) >= quantity:
            self.inventory[part_id] -= quantity
            self.processed_commands.add(command_id)
            return True
        return False

    def release_parts(self, saga_id: str, part_id: str, quantity: int) -> bool:
        """Компенсаційна дія."""
        if self.simulate_compensation_failure:
            raise Exception("Помилка під час компенсації (симуляція відмови)")

        command_id = f"release_{saga_id}"
        # Ідемпотентність для компенсації
        if command_id in self.processed_commands:
            return True

        self.inventory[part_id] = self.inventory.get(part_id, 0) + quantity
        self.processed_commands.add(command_id)
        return True


class RepairService:
    """Учасник 2: Керує статусом заявок."""
    def __init__(self):
        self.orders_status: Dict[str, str] = {"ORDER_1": "WAITING_FOR_APPROVAL"}
        self.processed_commands: Set[str] = set()
        self.simulate_approval_failure = False

    def approve_repair(self, saga_id: str, order_id: str) -> bool:
        command_id = f"approve_{saga_id}"
        if command_id in self.processed_commands:
            return True

        if self.simulate_approval_failure:
            raise ValueError(f"Неможливо затвердити ремонт {order_id} через бізнес-правило.")

        if self.orders_status.get(order_id) == "WAITING_FOR_APPROVAL":
            self.orders_status[order_id] = "IN_PROGRESS"
            self.processed_commands.add(command_id)
            return True
        return False