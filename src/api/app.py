import uuid
from typing import Optional
from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from src.api.auth import AuthenticatedUser, get_current_user
from src.domain.aggregate import RepairOrder, RepairStatus
from src.domain.value_objects import DeviceSpecification, Money
from src.domain.exceptions import (
    InvalidStateTransitionException,
    DiagnosticRequiredException,
    InvalidMoneyAmountException,
)
from src.infrastructure.in_memory_repository import InMemoryRepairOrderRepository

app = FastAPI(title="TechRepair Hub API", version="1.0.0")

# Єдине сховище (власник даних — сервіс ремонту)
repository = InMemoryRepairOrderRepository()

# Реєстр володіння об'єктами: order_id -> owner_sub (інженер, який створив заявку)
_ORDER_OWNERS: dict[uuid.UUID, str] = {}


# --- Pydantic-схеми контракту ---
class CreateRepairOrderRequest(BaseModel):
    brand: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    serial_number: str = Field(..., min_length=3, max_length=100)


class UpdateStatusRequest(BaseModel):
    status: RepairStatus
    estimated_cost: Optional[float] = Field(None, gt=0)
    currency: str = Field("UAH", min_length=3, max_length=3)


class DeviceResponse(BaseModel):
    brand: str
    model: str
    serial_number: str


class RepairOrderResponse(BaseModel):
    id: str
    status: str
    diagnostic_completed: bool
    estimated_cost: Optional[float] = None
    currency: Optional[str] = None
    device: DeviceResponse


def _to_response(order: RepairOrder) -> RepairOrderResponse:
    return RepairOrderResponse(
        id=str(order.id),
        status=order.status.value,
        diagnostic_completed=order.diagnostic_completed,
        estimated_cost=order.estimated_cost.amount if order.estimated_cost else None,
        currency=order.estimated_cost.currency if order.estimated_cost else None,
        device=DeviceResponse(
            brand=order.device.brand,
            model=order.device.model,
            serial_number=order.device.serial_number,
        ),
    )


def _assert_order_access(order_id: uuid.UUID, user: AuthenticatedUser) -> None:
    """Перевірка принципу найменших привілеїв на рівні конкретного об'єкта (Object-Level)."""
    owner_sub = _ORDER_OWNERS.get(order_id)
    if owner_sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявку не знайдено")
    if user.role == "supervisor":
        return
    if owner_sub != user.sub:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ заборонено: об'єкт належить іншому інженеру",
        )


# --- Ендпоінти v1 (контракт ЛР 5) ---
@app.post(
    "/api/v1/repair-orders",
    response_model=RepairOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repair_order(payload: CreateRepairOrderRequest):
    try:
        device = DeviceSpecification(
            brand=payload.brand,
            model=payload.model,
            serial_number=payload.serial_number,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    order = RepairOrder(order_id=uuid.uuid4(), device=device)
    repository.save(order)
    return _to_response(order)


@app.get(
    "/api/v1/repair-orders/{order_id}",
    response_model=RepairOrderResponse,
    status_code=status.HTTP_200_OK,
)
def get_repair_order(order_id: uuid.UUID):
    order = repository.get_by_id(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Заявку з ID {order_id} не знайдено",
        )
    return _to_response(order)


@app.patch(
    "/api/v1/repair-orders/{order_id}/status",
    response_model=RepairOrderResponse,
    status_code=status.HTTP_200_OK,
)
def update_repair_order_status(order_id: uuid.UUID, payload: UpdateStatusRequest):
    order = repository.get_by_id(order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Заявку з ID {order_id} не знайдено",
        )

    try:
        if payload.status == RepairStatus.IN_DIAGNOSTICS:
            order.start_diagnostics()
        elif payload.status == RepairStatus.WAITING_FOR_APPROVAL:
            if payload.estimated_cost is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Для завершення діагностики необхідно вказати estimated_cost",
                )
            cost = Money(amount=payload.estimated_cost, currency=payload.currency)
            order.complete_diagnostics(estimated_cost=cost)
        elif payload.status == RepairStatus.IN_PROGRESS:
            order.approve_and_start_repair()
        elif payload.status == RepairStatus.COMPLETED:
            order.complete_repair()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Перехід у статус {payload.status.value} не підтримується через цей ендпоінт",
            )
    except (InvalidStateTransitionException, DiagnosticRequiredException) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidMoneyAmountException as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    repository.save(order)
    return _to_response(order)


# --- Ендпоінти v2 (захищені JWT + RBAC + Object Ownership, ЛР 8) ---
@app.post(
    "/api/v2/repair-orders",
    response_model=RepairOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_protected_repair_order(
    payload: CreateRepairOrderRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Створення заявки: дозволено ролям technician та supervisor; власником стає user.sub."""
    order_id = uuid.uuid4()
    try:
        device = DeviceSpecification(
            brand=payload.brand.strip(),
            model=payload.model.strip(),
            serial_number=payload.serial_number.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    order = RepairOrder(order_id=order_id, device=device)
    repository.save(order)
    _ORDER_OWNERS[order_id] = user.sub
    return _to_response(order)


@app.get("/api/v2/repair-orders/{order_id}", response_model=RepairOrderResponse)
def get_protected_repair_order(
    order_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Читання заявки: technician читає тільки свої, supervisor — будь-які."""
    order = repository.get_by_id(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявку не знайдено")
    _assert_order_access(order_id, user)
    return _to_response(order)


@app.patch("/api/v2/repair-orders/{order_id}/status", response_model=RepairOrderResponse)
def update_protected_repair_order_status(
    order_id: uuid.UUID,
    payload: UpdateStatusRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Зміна стану заявки: technician змінює тільки свої, supervisor — будь-які."""
    order = repository.get_by_id(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявку не знайдено")
    _assert_order_access(order_id, user)

    try:
        if payload.status == RepairStatus.IN_DIAGNOSTICS:
            order.start_diagnostics()
        elif payload.status == RepairStatus.WAITING_FOR_APPROVAL:
            if payload.estimated_cost is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Для переходу у WAITING_FOR_APPROVAL потрібна estimated_cost",
                )
            order.complete_diagnostics(Money(payload.estimated_cost, payload.currency))
        elif payload.status == RepairStatus.IN_PROGRESS:
            order.approve_and_start_repair()
        elif payload.status == RepairStatus.COMPLETED:
            order.complete_repair()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Перехід у статус {payload.status.value} не підтримується через цей ендпоінт",
            )
    except (InvalidStateTransitionException, DiagnosticRequiredException) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvalidMoneyAmountException as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    repository.save(order)
    return _to_response(order)


@app.delete("/api/v2/repair-orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_protected_repair_order(
    order_id: uuid.UUID,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Видалення/анулювання заявки: привілейована операція ТІЛЬКИ для ролі supervisor."""
    if user.role != "supervisor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостатньо прав: потрібна роль supervisor",
        )
    if order_id not in _ORDER_OWNERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявку не знайдено")
    del _ORDER_OWNERS[order_id]