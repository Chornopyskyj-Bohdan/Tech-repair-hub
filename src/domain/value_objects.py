from dataclasses import dataclass
from src.domain.exceptions import InvalidMoneyAmountException

@dataclass(frozen=True)
class Money:
    amount: float
    currency: str = "UAH"

    def __post_init__(self):
        if self.amount < 0:
            raise InvalidMoneyAmountException("Сума не може бути від'ємною")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Неможливо додавати різні валюти")
        return Money(self.amount + other.amount, self.currency)

@dataclass(frozen=True)
class DeviceSpecification:
    brand: str
    model: str
    serial_number: str

    def __post_init__(self):
        if not self.serial_number or not self.serial_number.strip():
            raise ValueError("Серійний номер пристрою обов'язковий")