import time
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

warranty_app = FastAPI(title="VendorWarrantyService Stub", version="1.0.0")


class StubState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.delay_sec: float = 0.0
        self.fail_next_n: int = 0
        self.always_fail: bool = False
        self.call_count: int = 0
        self.received_request_ids: list[str] = []


stub_state = StubState()


class StubBehaviorRequest(BaseModel):
    delay_sec: float = 0.0
    fail_next_n: int = 0
    always_fail: bool = False
    reset_counter: bool = True


@warranty_app.post("/admin/behavior")
def configure_stub(payload: StubBehaviorRequest):
    stub_state.delay_sec = payload.delay_sec
    stub_state.fail_next_n = payload.fail_next_n
    stub_state.always_fail = payload.always_fail
    if payload.reset_counter:
        stub_state.call_count = 0
        stub_state.received_request_ids.clear()
    return {"status": "configured", "delay_sec": stub_state.delay_sec}


@warranty_app.get("/admin/stats")
def get_stub_stats():
    return {
        "call_count": stub_state.call_count,
        "received_request_ids": stub_state.received_request_ids,
    }


@warranty_app.get("/api/v1/warranty/{serial_number}")
def check_warranty(
    serial_number: str,
    x_request_id: str | None = Header(default=None),
):
    stub_state.call_count += 1
    if x_request_id:
        stub_state.received_request_ids.append(x_request_id)

    if stub_state.delay_sec > 0:
        time.sleep(stub_state.delay_sec)

    if stub_state.always_fail:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VendorWarrantyService тимчасово недоступний",
        )

    if stub_state.fail_next_n > 0:
        stub_state.fail_next_n -= 1
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Тимчасова помилка шлюзу виробника (503)",
        )

    return {
        "serial_number": serial_number,
        "warranty_active": True,
        "coverage_until": "2027-12-31",
        "vendor": "AuthorizedServicePartner",
    }