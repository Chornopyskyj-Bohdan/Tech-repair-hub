from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

@dataclass(frozen=True)
class RepairOrderCompletedEvent:
    order_id: uuid.UUID
    occurred_on: datetime = field(default_factory=lambda: datetime.now(timezone.utc))