from datetime import datetime, timezone
import uuid
from pydantic import BaseModel, Field


class RepairCompletedData(BaseModel):
    brand: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    serial_number: str = Field(..., min_length=3)
    final_cost: float = Field(..., gt=0)
    currency: str = Field("UAH", min_length=3, max_length=3)


class RepairOrderCompletedEventMessage(BaseModel):
    """Контракт інтеграційної події (Event-Carried State Transfer)."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = Field("RepairOrderCompleted", pattern="^RepairOrderCompleted$")
    schema_version: str = Field("1.0", pattern="^1\\.0$")
    occurred_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    order_id: str
    data: RepairCompletedData